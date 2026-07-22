#!/usr/bin/env python3
"""Windows-friendly batch speech processing powered by FFmpeg.

The script intentionally has no third-party Python dependencies. It can accept
files/directories dropped onto the launcher, scan the current directory, or
process explicitly supplied paths.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SUPPORTED_EXTENSIONS = {
    ".wav",
    ".mp3",
    ".m4a",
    ".aac",
    ".flac",
    ".ogg",
    ".opus",
    ".wma",
}
ALL_STEPS = {"denoise", "trim", "normalize"}
REPORT_NAME = "processing-report.json"
PRINT_LOCK = threading.Lock()
OUTPUT_LOCK = threading.Lock()
RESERVED_OUTPUTS: set[str] = set()


class ProcessingError(RuntimeError):
    """An expected processing failure for one input file."""


@dataclass(frozen=True)
class MediaInfo:
    duration: float
    sample_rate: int
    channels: int
    codec: str
    bit_rate: int | None


@dataclass
class Result:
    source: str
    source_sha256: str
    output: str | None
    status: str
    message: str
    settings_signature: str
    completed_steps_before: list[str]
    applied_steps: list[str]
    duration_before: float | None = None
    duration_after: float | None = None
    measured_lufs: float | None = None


def log(message: str) -> None:
    with PRINT_LOCK:
        print(message, flush=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="批量处理纯人声音频：降噪、裁剪头尾静音、响度归一化。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        help="音频文件或文件夹；不填写时扫描当前文件夹",
    )
    parser.add_argument("-o", "--output", help="统一输出目录；默认在每个源目录建立 processed")
    parser.add_argument("-r", "--recursive", action="store_true", help="递归扫描子文件夹")
    parser.add_argument("--workers", type=int, default=4, help="并发处理文件数")
    parser.add_argument(
        "--completed-plan",
        metavar="CSV",
        help="按文件声明已经完成的步骤，格式见 processing-plan.example.csv",
    )
    parser.add_argument("--no-denoise", action="store_true", help="本批次不执行降噪")
    parser.add_argument("--no-trim", action="store_true", help="本批次不裁剪头尾")
    parser.add_argument("--no-normalize", action="store_true", help="本批次不做响度归一化")
    parser.add_argument("--noise-reduction", type=float, default=12.0, help="降噪量（dB）")
    parser.add_argument("--noise-floor", type=float, default=-50.0, help="估计底噪（dBFS）")
    parser.add_argument("--silence-threshold", type=float, default=-45.0, help="静音阈值（dBFS）")
    parser.add_argument(
        "--speech-confirmation",
        "--silence-duration",
        dest="speech_confirmation",
        type=float,
        default=0.02,
        help="确认进入人声所需的连续非静音时长（秒）",
    )
    parser.add_argument("--keep-silence", type=float, default=0.15, help="头尾保留静音（秒）")
    parser.add_argument("--target-lufs", type=float, default=-16.0, help="目标综合响度（LUFS）")
    parser.add_argument("--true-peak", type=float, default=-1.5, help="目标真峰值（dBTP）")
    parser.add_argument("--lra", type=float, default=11.0, help="目标响度范围（LU）")
    parser.add_argument(
        "--loudness-tolerance",
        type=float,
        default=0.5,
        help="实测响度在目标正负此范围内时不再归一化",
    )
    parser.add_argument(
        "--install-ffmpeg",
        action="store_true",
        help="找不到 FFmpeg 时尝试通过 winget 安装（仅 Windows）",
    )
    parser.add_argument("--ffmpeg", help="ffmpeg.exe 的明确路径")
    parser.add_argument("--ffprobe", help="ffprobe.exe 的明确路径")
    parser.add_argument("--overwrite", action="store_true", help="覆盖同名输出文件")
    parser.add_argument("--version", action="version", version="audio-processor 1.0.0")
    args = parser.parse_args(argv)

    if args.workers < 1:
        parser.error("--workers 必须大于等于 1")
    if not -70 <= args.silence_threshold <= -10:
        parser.error("--silence-threshold 应在 -70 到 -10 dBFS 之间")
    if args.keep_silence < 0 or args.speech_confirmation < 0:
        parser.error("静音时长不能为负数")
    return args


def executable_candidates(name: str) -> Iterable[Path]:
    executable = f"{name}.exe" if os.name == "nt" else name
    script_dir = Path(__file__).resolve().parent
    yield script_dir / executable
    yield script_dir / "tools" / executable
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            yield Path(local_app_data) / "Microsoft" / "WinGet" / "Links" / executable


def find_executable(name: str, explicit: str | None = None) -> str | None:
    if explicit:
        path = Path(explicit).expanduser()
        return str(path.resolve()) if path.is_file() else None
    for candidate in executable_candidates(name):
        if candidate.is_file():
            return str(candidate)
    return shutil.which(name)


def install_ffmpeg_with_winget() -> bool:
    if os.name != "nt":
        return False
    winget = shutil.which("winget")
    if not winget:
        log("未找到 winget，无法自动安装 FFmpeg。")
        return False
    log("正在通过 winget 安装 FFmpeg，请稍候……")
    command = [
        winget,
        "install",
        "--id",
        "Gyan.FFmpeg",
        "-e",
        "--accept-package-agreements",
        "--accept-source-agreements",
    ]
    return subprocess.run(command, check=False).returncode == 0


def resolve_ffmpeg(args: argparse.Namespace) -> tuple[str, str]:
    ffmpeg = find_executable("ffmpeg", args.ffmpeg)
    ffprobe = find_executable("ffprobe", args.ffprobe)
    should_install = args.install_ffmpeg
    if not ffmpeg or not ffprobe:
        if os.name == "nt" and not should_install and sys.stdin.isatty():
            answer = input("未找到 FFmpeg，是否现在通过 winget 安装？[Y/n] ").strip().lower()
            should_install = answer in {"", "y", "yes"}
        if should_install and install_ffmpeg_with_winget():
            ffmpeg = find_executable("ffmpeg", args.ffmpeg)
            ffprobe = find_executable("ffprobe", args.ffprobe)
    if not ffmpeg or not ffprobe:
        raise SystemExit(
            "找不到 ffmpeg/ffprobe。请将它们放在脚本旁边的 tools 文件夹，"
            "或运行：python audio_processor.py --install-ffmpeg"
        )
    return ffmpeg, ffprobe


def run(command: list[str], context: str) -> subprocess.CompletedProcess[str]:
    process = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    if process.returncode:
        detail = process.stderr.strip().splitlines()
        last_lines = "\n".join(detail[-8:])
        raise ProcessingError(f"{context}失败：\n{last_lines}")
    return process


def probe(path: Path, ffprobe: str) -> MediaInfo:
    command = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=codec_name,sample_rate,channels,bit_rate:format=duration,bit_rate",
        "-of",
        "json",
        str(path),
    ]
    process = run(command, f"读取 {path.name} 的媒体信息")
    data = json.loads(process.stdout)
    if not data.get("streams"):
        raise ProcessingError("文件中没有音频轨道")
    stream = data["streams"][0]
    media_format = data.get("format", {})
    bit_rate_raw = stream.get("bit_rate") or media_format.get("bit_rate")
    return MediaInfo(
        duration=float(media_format.get("duration") or 0),
        sample_rate=int(stream.get("sample_rate") or 44100),
        channels=int(stream.get("channels") or 1),
        codec=str(stream.get("codec_name") or ""),
        bit_rate=int(bit_rate_raw) if bit_rate_raw else None,
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_plan_steps(value: str) -> set[str]:
    tokens = {token.strip().lower() for token in re.split(r"[|;+\s]+", value) if token.strip()}
    if "all" in tokens:
        return set(ALL_STEPS)
    if "none" in tokens or not tokens:
        return set()
    unknown = tokens - ALL_STEPS
    if unknown:
        raise ValueError(f"未知步骤：{', '.join(sorted(unknown))}")
    return tokens


def load_plan(path: str | None) -> dict[str, set[str]]:
    if not path:
        return {}
    plan_path = Path(path).expanduser().resolve()
    plan: dict[str, set[str]] = {}
    with plan_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if not reader.fieldnames or not {"file", "completed_steps"} <= set(reader.fieldnames):
            raise SystemExit("处理计划 CSV 必须包含 file 和 completed_steps 两列")
        for line_number, row in enumerate(reader, start=2):
            key = (row.get("file") or "").strip()
            if not key:
                continue
            try:
                steps = normalized_plan_steps(row.get("completed_steps") or "")
            except ValueError as error:
                raise SystemExit(f"{plan_path.name} 第 {line_number} 行：{error}") from error
            plan[key.casefold()] = steps
            candidate = Path(key).expanduser()
            if candidate.is_absolute():
                plan[str(candidate.resolve()).casefold()] = steps
    return plan


def steps_for_file(path: Path, plan: dict[str, set[str]]) -> set[str]:
    absolute_key = str(path.resolve()).casefold()
    return set(plan.get(absolute_key, plan.get(path.name.casefold(), set())))


def collect_files(
    inputs: list[str],
    recursive: bool,
    explicit_output: Path | None,
) -> list[Path]:
    raw_inputs = inputs or [str(Path.cwd())]
    collected: list[Path] = []
    seen: set[str] = set()
    output_resolved = explicit_output.resolve() if explicit_output else None

    for raw in raw_inputs:
        source = Path(raw).expanduser().resolve()
        if not source.exists():
            log(f"[跳过] 路径不存在：{source}")
            continue
        candidates: Iterable[Path]
        if source.is_file():
            candidates = [source]
        else:
            candidates = source.rglob("*") if recursive else source.glob("*")
        for candidate in candidates:
            if not candidate.is_file() or candidate.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            resolved = candidate.resolve()
            if REPORT_NAME in resolved.parts or "processed" in {
                part.casefold() for part in resolved.parts
            }:
                continue
            if output_resolved and (resolved == output_resolved or output_resolved in resolved.parents):
                continue
            key = str(resolved).casefold()
            if key not in seen:
                seen.add(key)
                collected.append(resolved)
    return sorted(collected, key=lambda item: str(item).casefold())


def output_directory(source: Path, explicit_output: Path | None) -> Path:
    return explicit_output if explicit_output else source.parent / "processed"


def load_reports(output_dirs: Iterable[Path]) -> dict[str, dict[str, Any]]:
    successful: dict[str, dict[str, Any]] = {}
    for directory in set(output_dirs):
        report = directory / REPORT_NAME
        if not report.is_file():
            continue
        try:
            data = json.loads(report.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for result in data.get("results", []):
            if result.get("status") in {"processed", "copied", "skipped"}:
                successful[result_key(result)] = result
    return successful


def choose_output(source: Path, directory: Path, overwrite: bool) -> Path:
    with OUTPUT_LOCK:
        target = directory / source.name
        key = str(target.resolve()).casefold()
        is_source = target.resolve() == source.resolve()
        if (
            not is_source
            and key not in RESERVED_OUTPUTS
            and (overwrite or not target.exists())
        ):
            RESERVED_OUTPUTS.add(key)
            return target
        index = 1
        while True:
            candidate = directory / f"{source.stem}_{index}{source.suffix}"
            key = str(candidate.resolve()).casefold()
            if key not in RESERVED_OUTPUTS and not candidate.exists():
                RESERVED_OUTPUTS.add(key)
                return candidate
            index += 1


def settings_signature(
    args: argparse.Namespace, completed_steps: Iterable[str] = ()
) -> str:
    settings = {
        "denoise": not args.no_denoise,
        "trim": not args.no_trim,
        "normalize": not args.no_normalize,
        "noise_reduction": args.noise_reduction,
        "noise_floor": args.noise_floor,
        "silence_threshold": args.silence_threshold,
        "speech_confirmation": args.speech_confirmation,
        "keep_silence": args.keep_silence,
        "target_lufs": args.target_lufs,
        "true_peak": args.true_peak,
        "lra": args.lra,
        "loudness_tolerance": args.loudness_tolerance,
        "completed_steps": sorted(completed_steps),
    }
    serialized = json.dumps(settings, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]


def preprocessing_filter(args: argparse.Namespace, steps: set[str]) -> str | None:
    filters: list[str] = []
    if "denoise" in steps:
        filters.append(
            f"afftdn=nr={args.noise_reduction:g}:nf={args.noise_floor:g}:tn=1"
        )
    if "trim" in steps:
        trim = (
            "silenceremove="
            f"start_periods=1:start_duration={args.speech_confirmation:g}:"
            f"start_threshold={args.silence_threshold:g}dB:"
            f"start_silence={args.keep_silence:g}:detection=rms:window=0.02"
        )
        filters.extend([trim, "areverse", trim, "areverse"])
    return ",".join(filters) or None


def make_lossless_intermediate(
    source: Path,
    destination: Path,
    info: MediaInfo,
    ffmpeg: str,
    audio_filter: str | None,
) -> None:
    command = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-i", str(source), "-map", "0:a:0"]
    if audio_filter:
        command += ["-af", audio_filter]
    command += [
        "-map_metadata",
        "0",
        "-ar",
        str(info.sample_rate),
        "-ac",
        str(info.channels),
        "-c:a",
        "flac",
        str(destination),
    ]
    run(command, f"预处理 {source.name}")


def loudness_measure(
    source: Path,
    ffmpeg: str,
    target: float,
    lra: float,
    true_peak: float,
) -> dict[str, Any]:
    audio_filter = (
        f"loudnorm=I={target:g}:LRA={lra:g}:TP={true_peak:g}:print_format=json"
    )
    process = run(
        [
            ffmpeg,
            "-hide_banner",
            "-nostdin",
            "-i",
            str(source),
            "-af",
            audio_filter,
            "-f",
            "null",
            "-",
        ],
        f"测量 {source.name} 的响度",
    )
    matches = re.findall(r"\{[\s\S]*?\}", process.stderr)
    if not matches:
        raise ProcessingError("FFmpeg 未返回响度测量结果")
    try:
        return json.loads(matches[-1])
    except json.JSONDecodeError as error:
        raise ProcessingError("无法解析 FFmpeg 响度测量结果") from error


def codec_arguments(source: Path, info: MediaInfo) -> list[str]:
    extension = source.suffix.lower()
    if extension == ".wav":
        codec = info.codec if info.codec.startswith(("pcm_", "adpcm_")) else "pcm_s16le"
        return ["-c:a", codec]
    if extension == ".flac":
        return ["-c:a", "flac"]
    if extension == ".mp3":
        arguments = ["-c:a", "libmp3lame"]
    elif extension in {".m4a", ".aac"}:
        arguments = ["-c:a", "aac"]
    elif extension == ".opus" or (extension == ".ogg" and info.codec == "opus"):
        arguments = ["-c:a", "libopus"]
    elif extension == ".ogg":
        arguments = ["-c:a", "libvorbis"]
    elif extension == ".wma":
        arguments = ["-c:a", "wmav2"]
    else:
        arguments = []
    if info.bit_rate and arguments:
        arguments += ["-b:a", str(info.bit_rate)]
    return arguments


def encode_output(
    source: Path,
    destination: Path,
    original: Path,
    info: MediaInfo,
    ffmpeg: str,
    normalize_filter: str | None,
) -> None:
    command = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-i", str(source), "-map", "0:a:0"]
    if normalize_filter:
        command += ["-af", normalize_filter]
    command += [
        "-map_metadata",
        "0",
        "-ar",
        str(info.sample_rate),
        "-ac",
        str(info.channels),
        *codec_arguments(original, info),
        str(destination),
    ]
    run(command, f"输出 {destination.name}")


def loudnorm_second_pass_filter(
    measurement: dict[str, Any],
    target: float,
    lra: float,
    true_peak: float,
) -> str:
    required = {
        "input_i",
        "input_lra",
        "input_tp",
        "input_thresh",
        "target_offset",
    }
    if not required <= measurement.keys():
        raise ProcessingError("FFmpeg 响度测量结果缺少必要字段")
    return (
        f"loudnorm=I={target:g}:LRA={lra:g}:TP={true_peak:g}:"
        f"measured_I={measurement['input_i']}:"
        f"measured_LRA={measurement['input_lra']}:"
        f"measured_TP={measurement['input_tp']}:"
        f"measured_thresh={measurement['input_thresh']}:"
        f"offset={measurement['target_offset']}:linear=true:print_format=summary"
    )


def process_one(
    source: Path,
    args: argparse.Namespace,
    ffmpeg: str,
    ffprobe: str,
    explicit_output: Path | None,
    plan: dict[str, set[str]],
    previous: dict[str, dict[str, Any]],
) -> Result:
    source_hash = sha256(source)
    completed = steps_for_file(source, plan)
    signature = settings_signature(args, completed)
    previous_key = f"{str(source).casefold()}::{source_hash}::{signature}"
    prior = previous.get(previous_key)
    if prior and prior.get("output") and Path(prior["output"]).is_file():
        return Result(
            source=str(source),
            source_sha256=source_hash,
            output=prior["output"],
            status="skipped",
            message="源文件未改变，已有成功输出",
            settings_signature=signature,
            completed_steps_before=prior.get("completed_steps_before", sorted(completed)),
            applied_steps=prior.get("applied_steps", []),
            duration_before=prior.get("duration_before"),
            duration_after=prior.get("duration_after"),
            measured_lufs=prior.get("measured_lufs"),
        )

    requested = set(ALL_STEPS)
    if args.no_denoise:
        requested.discard("denoise")
    if args.no_trim:
        requested.discard("trim")
    if args.no_normalize:
        requested.discard("normalize")
    steps = requested - completed

    destination_dir = output_directory(source, explicit_output)
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = choose_output(source, destination_dir, args.overwrite)
    info = probe(source, ffprobe)

    if not steps:
        shutil.copy2(source, destination)
        return Result(
            source=str(source),
            source_sha256=source_hash,
            output=str(destination),
            status="copied",
            message="本批次所需步骤均已完成，已原样复制",
            settings_signature=signature,
            completed_steps_before=sorted(completed),
            applied_steps=[],
            duration_before=info.duration,
            duration_after=info.duration,
        )

    # Normalization must be re-checked after any earlier processing step, even
    # when a plan says it was previously complete.
    should_check_normalization = "normalize" in requested and (
        "normalize" in steps or bool(steps & {"denoise", "trim"})
    )
    applied: list[str] = sorted(steps & {"denoise", "trim"})

    with tempfile.TemporaryDirectory(prefix="audio-processor-") as temp_dir:
        intermediate = Path(temp_dir) / "intermediate.flac"
        make_lossless_intermediate(
            source,
            intermediate,
            info,
            ffmpeg,
            preprocessing_filter(args, steps),
        )
        intermediate_info = probe(intermediate, ffprobe)
        if intermediate_info.duration < 0.05:
            raise ProcessingError("裁剪后没有有效音频；请调低静音阈值或检查源文件")

        measurement: dict[str, Any] | None = None
        measured_lufs: float | None = None
        normalize_filter: str | None = None
        if should_check_normalization:
            measurement = loudness_measure(
                intermediate, ffmpeg, args.target_lufs, args.lra, args.true_peak
            )
            try:
                measured_lufs = float(measurement["input_i"])
            except (KeyError, TypeError, ValueError) as error:
                raise ProcessingError("无法读取实测综合响度") from error
            if not math.isfinite(measured_lufs):
                raise ProcessingError("无法测得有效响度；文件可能只有静音")
            if abs(measured_lufs - args.target_lufs) > args.loudness_tolerance:
                normalize_filter = loudnorm_second_pass_filter(
                    measurement, args.target_lufs, args.lra, args.true_peak
                )
                applied.append("normalize")

        encode_output(
            intermediate,
            destination,
            source,
            info,
            ffmpeg,
            normalize_filter,
        )
        final_info = probe(destination, ffprobe)

    return Result(
        source=str(source),
        source_sha256=source_hash,
        output=str(destination),
        status="processed",
        message="处理完成",
        settings_signature=signature,
        completed_steps_before=sorted(completed),
        applied_steps=applied,
        duration_before=round(info.duration, 4),
        duration_after=round(final_info.duration, 4),
        measured_lufs=round(measured_lufs, 2) if measured_lufs is not None else None,
    )


def result_key(result: dict[str, Any]) -> str:
    return (
        f"{str(result.get('source', '')).casefold()}::"
        f"{result.get('source_sha256', '')}::"
        f"{result.get('settings_signature', '')}"
    )


def write_reports(
    results: list[Result],
    output_dirs: Iterable[Path],
    result_directories: dict[str, Path],
    args: argparse.Namespace,
) -> None:
    generated_at = datetime.now(timezone.utc).isoformat()
    for directory in set(output_dirs):
        directory.mkdir(parents=True, exist_ok=True)
        directory_results = [
            result
            for result in results
            if result_directories.get(result.source, Path()) == directory
        ]
        report_path = directory / REPORT_NAME
        merged: dict[str, dict[str, Any]] = {}
        if report_path.is_file():
            try:
                existing = json.loads(report_path.read_text(encoding="utf-8"))
                for old_result in existing.get("results", []):
                    if isinstance(old_result, dict):
                        merged[result_key(old_result)] = old_result
            except (OSError, json.JSONDecodeError):
                pass
        for result in directory_results:
            serialized_result = asdict(result)
            merged[result_key(serialized_result)] = serialized_result
        payload = {
            "version": "1.0.0",
            "generated_at": generated_at,
            "settings": {
                "target_lufs": args.target_lufs,
                "true_peak": args.true_peak,
                "silence_threshold": args.silence_threshold,
                "noise_reduction": args.noise_reduction,
            },
            "results": list(merged.values()),
        }
        temporary = directory / f".{REPORT_NAME}.tmp"
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(directory / REPORT_NAME)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    ffmpeg, ffprobe = resolve_ffmpeg(args)
    explicit_output = Path(args.output).expanduser().resolve() if args.output else None
    plan_path = args.completed_plan
    if not plan_path:
        automatic_plans = [
            Path.cwd() / "processing-plan.csv",
            Path(__file__).resolve().parent / "processing-plan.csv",
        ]
        automatic_plan = next((path for path in automatic_plans if path.is_file()), None)
        if automatic_plan:
            plan_path = str(automatic_plan)
            log(f"使用处理计划：{automatic_plan}")
    try:
        plan = load_plan(plan_path)
    except OSError as error:
        raise SystemExit(f"无法读取处理计划：{error}") from error

    files = collect_files(args.inputs, args.recursive, explicit_output)
    if not files:
        log("没有找到支持的音频文件。")
        return 1

    output_dirs = [output_directory(source, explicit_output) for source in files]
    previous = load_reports(output_dirs)
    log(f"找到 {len(files)} 个音频文件，使用 {min(args.workers, len(files))} 个并发任务。")

    results: list[Result] = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                process_one,
                source,
                args,
                ffmpeg,
                ffprobe,
                explicit_output,
                plan,
                previous,
            ): source
            for source in files
        }
        for future in as_completed(futures):
            source = futures[future]
            try:
                result = future.result()
                results.append(result)
                label = {"processed": "完成", "copied": "复制", "skipped": "跳过"}[result.status]
                log(f"[{label}] {source.name}：{result.message}")
            except Exception as error:  # Keep the other files running.
                results.append(
                    Result(
                        source=str(source),
                        source_sha256="",
                        output=None,
                        status="failed",
                        message=str(error),
                        settings_signature=settings_signature(
                            args, steps_for_file(source, plan)
                        ),
                        completed_steps_before=sorted(steps_for_file(source, plan)),
                        applied_steps=[],
                    )
                )
                log(f"[失败] {source.name}：{error}")

    result_directories = {
        str(source): output_directory(source, explicit_output) for source in files
    }
    write_reports(results, output_dirs, result_directories, args)
    counts = {
        status: sum(result.status == status for result in results)
        for status in ("processed", "copied", "skipped", "failed")
    }
    log(
        "处理结束："
        f"完成 {counts['processed']}，原样复制 {counts['copied']}，"
        f"跳过 {counts['skipped']}，失败 {counts['failed']}。"
    )
    return 2 if counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
