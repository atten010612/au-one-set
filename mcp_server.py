"""Cursor MCP server for the local Windows audio workflow."""

from __future__ import annotations

import atexit
import json
import os
import queue
import re
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from fastmcp import FastMCP
except ImportError:  # Allows diagnostics/tests before setup_mcp.bat is run.
    FastMCP = None  # type: ignore[assignment,misc]


PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = PROJECT_ROOT / "audio_processor_config.json"
WORKFLOW_NAMES = {
    0: "音频处理 → 转换 → 合成",
    1: "仅音频处理",
    2: "转换 → 合成",
    3: "仅转换",
    4: "仅合成",
}
TERMINAL_STATES = {"completed", "failed", "cancelled"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class WorkflowJob:
    job_id: str
    input_paths: list[str]
    workflow_step: int
    status: str = "queued"
    phase: str = "queued"
    percent: float = 0.0
    current: int = 0
    total: int = 0
    exit_code: int | None = None
    error: str | None = None
    created_at: str = field(default_factory=utc_now)
    started_at: str | None = None
    finished_at: str | None = None
    logs: list[str] = field(default_factory=list)
    process: subprocess.Popen[str] | None = field(default=None, repr=False)


class WorkflowManager:
    """Single-active-job queue for desktop GUI automation."""

    def __init__(
        self,
        project_root: Path = PROJECT_ROOT,
        start_dispatcher: bool = True,
    ) -> None:
        self.project_root = project_root.resolve()
        self.jobs: dict[str, WorkflowJob] = {}
        self.pending: queue.Queue[str] = queue.Queue()
        self.lock = threading.RLock()
        self.dispatcher: threading.Thread | None = None
        if start_dispatcher:
            self.dispatcher = threading.Thread(
                target=self._dispatch,
                name="audio-workflow-dispatcher",
                daemon=True,
            )
            self.dispatcher.start()

    def start(self, input_paths: list[str] | None, workflow_step: int) -> dict[str, Any]:
        if workflow_step not in WORKFLOW_NAMES:
            raise ValueError("workflow_step 必须是 0、1、2、3 或 4")
        resolved: list[str] = []
        for raw in input_paths or []:
            path = Path(raw).expanduser()
            if not path.is_absolute():
                path = self.project_root / path
            path = path.resolve()
            if not path.exists():
                raise ValueError(f"输入路径不存在：{path}")
            resolved.append(str(path))
        job = WorkflowJob(
            job_id=uuid.uuid4().hex,
            input_paths=resolved,
            workflow_step=workflow_step,
        )
        with self.lock:
            self.jobs[job.job_id] = job
            self.pending.put(job.job_id)
        return self.snapshot(job.job_id)

    def snapshot(self, job_id: str) -> dict[str, Any]:
        with self.lock:
            job = self._get(job_id)
            return {
                "job_id": job.job_id,
                "status": job.status,
                "workflow_step": job.workflow_step,
                "workflow": WORKFLOW_NAMES[job.workflow_step],
                "phase": job.phase,
                "percent": round(job.percent, 1),
                "current": job.current,
                "total": job.total,
                "input_paths": list(job.input_paths),
                "exit_code": job.exit_code,
                "error": job.error,
                "created_at": job.created_at,
                "started_at": job.started_at,
                "finished_at": job.finished_at,
                "logs": list(job.logs[-100:]),
                "artifacts": self._artifacts(job),
            }

    def list_jobs(self) -> list[dict[str, Any]]:
        with self.lock:
            ordered = sorted(
                self.jobs.values(),
                key=lambda job: job.created_at,
                reverse=True,
            )
            return [self.snapshot(job.job_id) for job in ordered[:50]]

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self.lock:
            job = self._get(job_id)
            if job.status in TERMINAL_STATES:
                return self.snapshot(job_id)
            job.status = "cancelled"
            job.phase = "cancelled"
            job.error = "用户取消"
            job.finished_at = utc_now()
            process = job.process
        if process and process.poll() is None:
            self._terminate_process_tree(process.pid)
        return self.snapshot(job_id)

    def cancel_all(self) -> None:
        with self.lock:
            ids = [
                job.job_id
                for job in self.jobs.values()
                if job.status not in TERMINAL_STATES
            ]
        for job_id in ids:
            self.cancel(job_id)

    def _get(self, job_id: str) -> WorkflowJob:
        try:
            return self.jobs[job_id]
        except KeyError as error:
            raise ValueError(f"未知 job_id：{job_id}") from error

    def _dispatch(self) -> None:
        while True:
            job_id = self.pending.get()
            try:
                with self.lock:
                    job = self.jobs.get(job_id)
                    if not job or job.status == "cancelled":
                        continue
                self._run(job)
            finally:
                self.pending.task_done()

    def _run(self, job: WorkflowJob) -> None:
        command = [
            sys.executable,
            str(self.project_root / "audio_processor.py"),
            *job.input_paths,
            "--workflow-step",
            str(job.workflow_step),
            "--converter-config",
            str(self.project_root / "audio_processor_config.json"),
        ]
        environment = os.environ.copy()
        environment.update(
            {
                "PYTHONUTF8": "1",
                "PYTHONUNBUFFERED": "1",
            }
        )
        creation_flags = (
            subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        )
        with self.lock:
            if job.status == "cancelled":
                return
            job.status = "running"
            job.phase = "starting"
            job.started_at = utc_now()
        try:
            process = subprocess.Popen(
                command,
                cwd=str(self.project_root),
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creation_flags,
            )
            with self.lock:
                job.process = process
            assert process.stdout is not None
            for raw_line in process.stdout:
                line = raw_line.rstrip()
                if line:
                    self._consume_line(job, line)
            exit_code = process.wait()
            with self.lock:
                job.process = None
                job.exit_code = exit_code
                if job.status == "cancelled":
                    return
                job.finished_at = utc_now()
                if exit_code == 0:
                    job.status = "completed"
                    job.phase = "completed"
                    job.percent = 100.0
                else:
                    job.status = "failed"
                    job.phase = "failed"
                    job.error = (
                        job.logs[-1]
                        if job.logs
                        else f"工作流退出代码：{exit_code}"
                    )
        except Exception as error:
            with self.lock:
                job.process = None
                if job.status != "cancelled":
                    job.status = "failed"
                    job.phase = "failed"
                    job.error = str(error)
                    job.finished_at = utc_now()

    def _consume_line(self, job: WorkflowJob, line: str) -> None:
        with self.lock:
            job.logs.append(line)
            del job.logs[:-300]
            found = re.search(r"找到 (\d+) 个(?:音频|现有音频)文件", line)
            if found:
                job.total = int(found.group(1))
                job.current = 0
            if re.match(r"^\[(完成|复制|跳过|失败)\]", line):
                job.current += 1
                fraction = job.current / max(job.total, 1)
                self._set_stage_progress(job, "processing", fraction)
            progress = re.search(r"已发现 (\d+)/(\d+) 个结果", line)
            if progress:
                job.current = int(progress.group(1))
                job.total = int(progress.group(2))
                self._set_stage_progress(
                    job,
                    "conversion",
                    job.current / max(job.total, 1),
                )
            batch = re.search(r"添加文件批次 (\d+)/(\d+)", line)
            if batch:
                self._set_stage_progress(
                    job,
                    "conversion",
                    int(batch.group(1)) / max(int(batch.group(2)), 1) * 0.3,
                )
            if "点击开始转换" in line:
                self._set_stage_progress(job, "conversion", 0.35)
            if "已完成并校验" in line and line.startswith("[转换]"):
                self._set_stage_progress(job, "conversion", 1.0)
            if line.startswith("[合成]"):
                synthesis_markers = (
                    ("选择磁盘", 0.05),
                    ("逐层进入", 0.15),
                    ("已加载", 0.30),
                    ("点击保存", 0.40),
                    ("已生成并校验", 0.55),
                    ("已复制", 0.70),
                    ("执行", 0.80),
                    ("输出成功", 1.0),
                    ("最终输出已就绪", 1.0),
                )
                for marker, fraction in synthesis_markers:
                    if marker in line:
                        self._set_stage_progress(job, "synthesis", fraction)
                        break

    def _set_stage_progress(
        self,
        job: WorkflowJob,
        stage: str,
        fraction: float,
    ) -> None:
        ranges = {
            0: {
                "processing": (0, 60),
                "conversion": (60, 90),
                "synthesis": (90, 100),
            },
            1: {"processing": (0, 100)},
            2: {"conversion": (0, 75), "synthesis": (75, 100)},
            3: {"conversion": (0, 100)},
            4: {"synthesis": (0, 100)},
        }
        start, end = ranges[job.workflow_step].get(stage, (0, 100))
        job.phase = stage
        job.percent = max(
            job.percent,
            min(100.0, start + (end - start) * max(0.0, min(1.0, fraction))),
        )

    def _terminate_process_tree(self, pid: int) -> None:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            try:
                os.kill(pid, 15)
            except OSError:
                pass

    def _artifacts(self, job: WorkflowJob) -> dict[str, Any]:
        artifacts: dict[str, Any] = {}
        roots = [
            Path(path) if Path(path).is_dir() else Path(path).parent
            for path in job.input_paths
        ] or [self.project_root]
        for folder_name in ("processed", "converted"):
            matches: list[str] = []
            for root in roots:
                direct = root if root.name.casefold() == folder_name else root / folder_name
                if direct.is_dir():
                    matches.append(str(direct.resolve()))
            if matches:
                artifacts[folder_name] = sorted(set(matches))
        try:
            from converter_automation import expand_environment_path

            config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            test_dir = expand_environment_path(
                config.get("packres_input_directory", "")
            )
            if not test_dir.is_absolute():
                test_dir = self.project_root / test_dir
            for name in ("OUTPUT.LST", config.get("packres_output_name", "dir_music")):
                path = test_dir / name
                if path.is_file():
                    artifacts[name] = str(path.resolve())
        except Exception:
            pass
        return artifacts


def check_environment() -> dict[str, Any]:
    """Return portable tool/dependency readiness without modifying the system."""
    from audio_processor import find_executable
    from converter_automation import expand_environment_path

    expected = {
        "ffmpeg": PROJECT_ROOT / "tools" / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg"),
        "ffprobe": PROJECT_ROOT / "tools" / ("ffprobe.exe" if os.name == "nt" else "ffprobe"),
    }
    config: dict[str, Any] = {}
    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    resolved_config_paths: dict[str, Path] = {}
    for key in ("converter_path", "packer_path", "packres_input_directory"):
        value = config.get(key)
        if value:
            path = expand_environment_path(value)
            if not path.is_absolute():
                path = PROJECT_ROOT / path
            resolved_config_paths[key] = path
            expected[key] = path
    test_dir = resolved_config_paths.get("packres_input_directory")
    if test_dir:
        expected["packres.exe"] = test_dir / "packres.exe"
        expected["new_packres.bat"] = test_dir / config.get(
            "packres_batch_name",
            "new_packres.bat",
        )
    checks = {
        name: {
            "path": str(path.resolve()),
            "exists": path.exists(),
        }
        for name, path in expected.items()
    }
    skill_home = os.environ.get("AU_TASK_SKILL_HOME", "")
    checks["AU_TASK_SKILL_HOME"] = {
        "path": skill_home,
        "exists": bool(skill_home) and Path(skill_home).is_dir(),
    }
    checks["ffmpeg"]["detected_path"] = find_executable("ffmpeg")
    checks["ffprobe"]["detected_path"] = find_executable("ffprobe")
    missing = [
        name
        for name, result in checks.items()
        if not result["exists"]
        and not result.get("detected_path")
    ]
    return {
        "ready": os.name == "nt" and not missing,
        "platform": sys.platform,
        "python": sys.version,
        "project_root": str(PROJECT_ROOT),
        "checks": checks,
        "missing": missing,
        "notes": (
            []
            if os.name == "nt"
            else ["GUI自动化仅支持本地Windows桌面会话"]
        ),
    }


manager = WorkflowManager()
atexit.register(manager.cancel_all)

if FastMCP is not None:
    mcp = FastMCP("Windows Audio Workflow")

    @mcp.tool
    def start_audio_workflow(
        input_paths: list[str] | None = None,
        workflow_step: int = 0,
    ) -> dict[str, Any]:
        """Queue an audio workflow. Steps: 0 all, 1 process, 2 convert+pack, 3 convert, 4 pack."""
        if os.name != "nt":
            raise ValueError("音频GUI工作流只能在本地Windows Cursor中运行")
        return manager.start(input_paths, workflow_step)

    @mcp.tool
    def get_audio_workflow_status(job_id: str) -> dict[str, Any]:
        """Get progress, recent logs, errors, and artifacts for one job."""
        return manager.snapshot(job_id)

    @mcp.tool
    def cancel_audio_workflow(job_id: str) -> dict[str, Any]:
        """Cancel a queued/running job and terminate its child process tree."""
        return manager.cancel(job_id)

    @mcp.tool
    def list_audio_workflows() -> list[dict[str, Any]]:
        """List up to 50 recent audio workflow jobs."""
        return manager.list_jobs()

    @mcp.tool
    def check_audio_environment() -> dict[str, Any]:
        """Check Python, FFmpeg, vendor tools, and portable paths."""
        return check_environment()
else:
    mcp = None


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        result = check_environment()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ready"] else 2
    if mcp is None:
        print(
            "缺少 fastmcp。请先运行 setup_mcp.bat。",
            file=sys.stderr,
        )
        return 1
    mcp.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
