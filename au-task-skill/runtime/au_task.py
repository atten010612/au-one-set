#!/usr/bin/env python3
"""Standalone AU Task conversion and packaging CLI."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Iterable, Sequence

from converter_runtime import (
    ensure_pywinauto,
    load_converter_config,
    run_configured_converter,
)
from packer_runtime import run_configured_packer


SKILL_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = SKILL_ROOT / "audio_processor_config.json"
SOURCE_EXTENSIONS = {
    ".wav",
    ".mp3",
    ".m4a",
    ".aac",
    ".flac",
    ".ogg",
    ".opus",
    ".wma",
}
PACKED_EXTENSIONS = {".a", ".e", ".f1a", ".f1b", ".f1c", ".ump3"}


class AUTaskError(RuntimeError):
    """Expected standalone workflow error."""


def sanitized_name(name: str) -> str:
    path = Path(name)
    stem = re.sub(r"\s+", "", path.stem) or "audio"
    return f"{stem}{path.suffix}"


def collect_audio(
    inputs: Sequence[str],
    extensions: set[str],
) -> list[Path]:
    collected: list[Path] = []
    seen: set[str] = set()
    for raw in inputs:
        source = Path(raw).expanduser().resolve()
        if not source.exists():
            raise AUTaskError(f"输入路径不存在：{source}")
        candidates: Iterable[Path] = [source] if source.is_file() else source.rglob("*")
        for candidate in candidates:
            ignored = {
                part.casefold()
                for part in candidate.parts
            } & {".venv", "vendor", "converted"}
            if (
                ignored
                or not candidate.is_file()
                or candidate.suffix.lower() not in extensions
            ):
                continue
            resolved = candidate.resolve()
            key = str(resolved).casefold()
            if key not in seen:
                seen.add(key)
                collected.append(resolved)
    return sorted(collected, key=lambda path: str(path).casefold())


def prepare_sanitized_copies(
    sources: Sequence[Path],
    destination: Path,
) -> list[Path]:
    prepared: list[Path] = []
    reserved: set[str] = set()
    for source in sources:
        desired = Path(sanitized_name(source.name))
        candidate = desired
        index = 1
        while candidate.name.casefold() in reserved:
            candidate = desired.with_name(
                f"{desired.stem}_{index}{desired.suffix}"
            )
            index += 1
        reserved.add(candidate.name.casefold())
        target = destination / candidate.name
        shutil.copy2(source, target)
        if source.name != target.name:
            print(f"[重命名] {source.name} → {target.name}", flush=True)
        prepared.append(target)
    return prepared


def output_basis(inputs: Sequence[str], sources: Sequence[Path]) -> list[str]:
    if len(inputs) == 1 and Path(inputs[0]).expanduser().is_dir():
        return [str(Path(inputs[0]).expanduser().resolve())]
    parents = {source.parent for source in sources}
    if len(parents) == 1:
        return [str(next(iter(parents)))]
    return []


def normalize_packed_names(directory: Path) -> None:
    reserved = {
        path.name.casefold()
        for path in directory.iterdir()
        if path.is_file()
        and path.suffix.lower() in PACKED_EXTENSIONS
        and sanitized_name(path.name) == path.name
    }
    for source in sorted(directory.iterdir(), key=lambda path: path.name.casefold()):
        if not source.is_file() or source.suffix.lower() not in PACKED_EXTENSIONS:
            continue
        desired = source.with_name(sanitized_name(source.name))
        if desired == source:
            continue
        candidate = desired
        index = 1
        while candidate.name.casefold() in reserved or candidate.exists():
            candidate = desired.with_name(
                f"{desired.stem}_{index}{desired.suffix}"
            )
            index += 1
        source.rename(candidate)
        reserved.add(candidate.name.casefold())
        print(f"[重命名] {source.name} → {candidate.name}", flush=True)


def locate_converted(inputs: Sequence[str]) -> Path:
    candidates: list[Path] = []
    for raw in inputs:
        path = Path(raw).expanduser().resolve()
        if path.is_file():
            path = path.parent
        candidate = path if path.name.casefold() == "converted" else path / "converted"
        if candidate.is_dir():
            candidates.append(candidate)
    if not inputs and (SKILL_ROOT / "converted").is_dir():
        candidates.append(SKILL_ROOT / "converted")
    unique = list(dict.fromkeys(path.resolve() for path in candidates))
    if len(unique) != 1:
        raise AUTaskError(
            "仅打包模式需要明确提供一个 converted 文件夹；"
            f"当前找到 {len(unique)} 个"
        )
    if not any(
        path.is_file() and path.suffix.lower() in PACKED_EXTENSIONS
        for path in unique[0].iterdir()
    ):
        raise AUTaskError(f"{unique[0]} 中没有杰理转换文件")
    return unique[0]


def run_conversion(inputs: Sequence[str], include_packer: bool) -> Path:
    sources = collect_audio(inputs, SOURCE_EXTENSIONS)
    if not sources:
        raise AUTaskError("没有找到可转换的音频文件")
    print(f"找到 {len(sources)} 个现有音频文件。", flush=True)
    with tempfile.TemporaryDirectory(prefix="au-task-input-") as temporary:
        prepared = prepare_sanitized_copies(sources, Path(temporary))
        result = run_configured_converter(
            prepared,
            output_basis(inputs, sources),
            SKILL_ROOT,
            CONFIG_PATH,
            include_packer=include_packer,
        )
    if result is None:
        raise AUTaskError("转换工具未返回输出目录")
    return result


def run_packaging(inputs: Sequence[str]) -> Path:
    converted = locate_converted(inputs)
    normalize_packed_names(converted)
    config = load_converter_config(CONFIG_PATH)
    ensure_pywinauto(config.auto_install_pywinauto)
    config.packer_enabled = True
    result = run_configured_packer(converted, config, CONFIG_PATH)
    if result is None:
        raise AUTaskError("打包工具未返回 dir_music")
    return result


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Standalone AD140 conversion and packaging workflow"
    )
    parser.add_argument("inputs", nargs="*", help="Audio files or folders")
    parser.add_argument(
        "--mode",
        type=int,
        choices=(0, 1, 2),
        required=True,
        help="0 convert+package, 1 convert only, 2 package only",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if os.name != "nt":
        print("[失败] AU Task GUI workflow only supports Windows.", flush=True)
        return 3
    try:
        if args.mode == 0:
            output = run_conversion(args.inputs, include_packer=True)
        elif args.mode == 1:
            output = run_conversion(args.inputs, include_packer=False)
        else:
            output = run_packaging(args.inputs)
        print(f"[AU-TASK完成] {output}", flush=True)
        return 0
    except Exception as error:
        print(f"[AU-TASK失败] {error}", flush=True)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
