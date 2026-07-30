"""Standalone Cursor MCP server for AU Task conversion and packaging."""

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
except ImportError:
    FastMCP = None  # type: ignore[assignment,misc]


RUNTIME_ROOT = Path(__file__).resolve().parent
SKILL_ROOT = RUNTIME_ROOT.parent
CONFIG_PATH = SKILL_ROOT / "audio_processor_config.json"
WORKFLOW_TO_MODE = {2: 0, 3: 1, 4: 2}
WORKFLOW_NAMES = {
    2: "转换 → 打包",
    3: "仅转换",
    4: "仅打包",
}
TERMINAL = {"completed", "failed", "cancelled"}


def no_window_creation_flags(*, new_process_group: bool = False) -> int:
    """Return Windows background-process flags portably."""
    if os.name != "nt":
        return 0
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if new_process_group:
        flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return flags


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Job:
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
    created_at: str = field(default_factory=now)
    started_at: str | None = None
    finished_at: str | None = None
    logs: list[str] = field(default_factory=list)
    process: subprocess.Popen[str] | None = field(default=None, repr=False)


class JobManager:
    def __init__(self, start_dispatcher: bool = True) -> None:
        self.jobs: dict[str, Job] = {}
        self.pending: queue.Queue[str] = queue.Queue()
        self.lock = threading.RLock()
        if start_dispatcher:
            threading.Thread(
                target=self._dispatch,
                name="au-task-dispatcher",
                daemon=True,
            ).start()

    def start(self, input_paths: list[str], workflow_step: int) -> dict[str, Any]:
        if workflow_step not in WORKFLOW_TO_MODE:
            raise ValueError("workflow_step 必须是 2、3 或 4")
        if not input_paths:
            raise ValueError("请拖入或@指定音频文件/文件夹")
        resolved: list[str] = []
        for raw in input_paths:
            path = Path(raw).expanduser()
            if not path.is_absolute():
                path = Path.cwd() / path
            path = path.resolve()
            if not path.exists():
                raise ValueError(f"输入路径不存在：{path}")
            resolved.append(str(path))
        job = Job(uuid.uuid4().hex, resolved, workflow_step)
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
                "logs": list(job.logs[-100:]),
                "created_at": job.created_at,
                "started_at": job.started_at,
                "finished_at": job.finished_at,
                "artifacts": discover_artifacts(job.input_paths),
            }

    def list(self) -> list[dict[str, Any]]:
        with self.lock:
            jobs = sorted(
                self.jobs.values(),
                key=lambda job: job.created_at,
                reverse=True,
            )
            return [self.snapshot(job.job_id) for job in jobs[:50]]

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self.lock:
            job = self._get(job_id)
            if job.status in TERMINAL:
                return self.snapshot(job_id)
            job.status = "cancelled"
            job.phase = "cancelled"
            job.error = "用户取消"
            job.finished_at = now()
            process = job.process
        if process and process.poll() is None:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                creationflags=no_window_creation_flags(),
            )
        return self.snapshot(job_id)

    def cancel_all(self) -> None:
        with self.lock:
            ids = [job.job_id for job in self.jobs.values() if job.status not in TERMINAL]
        for job_id in ids:
            self.cancel(job_id)

    def _get(self, job_id: str) -> Job:
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

    def _run(self, job: Job) -> None:
        command = [
            sys.executable,
            str(RUNTIME_ROOT / "au_task.py"),
            *job.input_paths,
            "--mode",
            str(WORKFLOW_TO_MODE[job.workflow_step]),
        ]
        environment = os.environ.copy()
        environment.update({"PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"})
        with self.lock:
            if job.status == "cancelled":
                return
            job.status = "running"
            job.phase = "starting"
            job.started_at = now()
        try:
            process = subprocess.Popen(
                command,
                cwd=str(SKILL_ROOT),
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=no_window_creation_flags(new_process_group=True),
            )
            with self.lock:
                job.process = process
            assert process.stdout is not None
            for raw in process.stdout:
                line = raw.rstrip()
                if line:
                    self._consume(job, line)
            exit_code = process.wait()
            with self.lock:
                job.process = None
                job.exit_code = exit_code
                if job.status == "cancelled":
                    return
                job.finished_at = now()
                if exit_code == 0:
                    job.status = "completed"
                    job.phase = "completed"
                    job.percent = 100.0
                else:
                    job.status = "failed"
                    job.phase = "failed"
                    job.error = job.logs[-1] if job.logs else f"退出代码 {exit_code}"
        except Exception as error:
            with self.lock:
                job.process = None
                if job.status != "cancelled":
                    job.status = "failed"
                    job.phase = "failed"
                    job.error = str(error)
                    job.finished_at = now()

    def _consume(self, job: Job, line: str) -> None:
        with self.lock:
            job.logs.append(line)
            del job.logs[:-300]
            found = re.search(r"找到 (\d+) 个现有音频文件", line)
            if found:
                job.total = int(found.group(1))
            converted = re.search(r"已发现 (\d+)/(\d+) 个结果", line)
            if converted:
                job.current = int(converted.group(1))
                job.total = int(converted.group(2))
                fraction = job.current / max(job.total, 1)
                self._progress(job, "conversion", fraction)
            if "[转换] 已完成并校验" in line:
                self._progress(job, "conversion", 1.0)
            if line.startswith("[合成]"):
                markers = (
                    ("选择磁盘", 0.1),
                    ("已加载", 0.3),
                    ("已生成并校验", 0.55),
                    ("已复制", 0.7),
                    ("执行", 0.85),
                    ("输出成功", 1.0),
                    ("最终输出已就绪", 1.0),
                )
                for marker, fraction in markers:
                    if marker in line:
                        self._progress(job, "packaging", fraction)
                        break

    def _progress(self, job: Job, phase: str, fraction: float) -> None:
        ranges = {
            2: {"conversion": (0, 75), "packaging": (75, 100)},
            3: {"conversion": (0, 100)},
            4: {"packaging": (0, 100)},
        }
        start, end = ranges[job.workflow_step].get(phase, (0, 100))
        job.phase = phase
        job.percent = max(
            job.percent,
            start + (end - start) * max(0.0, min(1.0, fraction)),
        )


def load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def resolve_config_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (SKILL_ROOT / path).resolve()


def check_environment() -> dict[str, Any]:
    config = load_config()
    expected = {
        "converter": resolve_config_path(config["converter_path"]),
        "pRFiles": resolve_config_path(config["packer_path"]),
        "test_dir": resolve_config_path(config["packres_input_directory"]),
    }
    expected["packres.exe"] = expected["test_dir"] / "packres.exe"
    expected["new_packres.bat"] = expected["test_dir"] / config.get(
        "packres_batch_name",
        "new_packres.bat",
    )
    checks = {
        name: {"path": str(path), "exists": path.exists()}
        for name, path in expected.items()
    }
    missing = [name for name, result in checks.items() if not result["exists"]]
    return {
        "ready": os.name == "nt" and not missing,
        "platform": sys.platform,
        "skill_root": str(SKILL_ROOT),
        "checks": checks,
        "missing": missing,
    }


def discover_artifacts(input_paths: list[str]) -> dict[str, Any]:
    artifacts: dict[str, Any] = {}
    converted: list[str] = []
    for raw in input_paths:
        path = Path(raw)
        root = path if path.is_dir() else path.parent
        candidate = root if root.name.casefold() == "converted" else root / "converted"
        if candidate.is_dir():
            converted.append(str(candidate.resolve()))
    if converted:
        artifacts["converted"] = sorted(set(converted))
    try:
        config = load_config()
        test_dir = resolve_config_path(config["packres_input_directory"])
        for name in ("OUTPUT.LST", config.get("packres_output_name", "dir_music")):
            path = test_dir / name
            if path.is_file():
                artifacts[name] = str(path.resolve())
    except Exception:
        pass
    return artifacts


manager = JobManager()
atexit.register(manager.cancel_all)

if FastMCP is not None:
    mcp = FastMCP("AU Task Workflow")

    @mcp.tool
    def start_audio_workflow(
        input_paths: list[str],
        workflow_step: int,
    ) -> dict[str, Any]:
        """Start AU Task workflow: step 2 convert+pack, 3 convert, 4 pack."""
        if os.name != "nt":
            raise ValueError("AU Task只能在本地Windows Cursor中运行")
        return manager.start(input_paths, workflow_step)

    @mcp.tool
    def get_audio_workflow_status(job_id: str) -> dict[str, Any]:
        """Return progress, logs, errors, and artifacts."""
        return manager.snapshot(job_id)

    @mcp.tool
    def cancel_audio_workflow(job_id: str) -> dict[str, Any]:
        """Cancel one queued or running AU Task job."""
        return manager.cancel(job_id)

    @mcp.tool
    def list_audio_workflows() -> list[dict[str, Any]]:
        """List recent AU Task jobs."""
        return manager.list()

    @mcp.tool
    def check_audio_environment() -> dict[str, Any]:
        """Check standalone vendor tool placement."""
        return check_environment()
else:
    mcp = None


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        result = check_environment()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ready"] else 2
    if mcp is None:
        print("Missing fastmcp. Run install_global_skills.bat.", file=sys.stderr)
        return 1
    mcp.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
