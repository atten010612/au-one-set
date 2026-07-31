"""Strong-burn and AD15n authorization steps for packaged firmware."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Iterable


class FirmwareAutomationError(RuntimeError):
    """Expected firmware generation or authorization failure."""


def no_window_creation_flags() -> int:
    if os.name != "nt":
        return 0
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def expand_environment_path(value: str) -> Path:
    expanded = re.sub(
        r"%([^%]+)%",
        lambda match: os.environ.get(match.group(1), match.group(0)),
        value,
    )
    return Path(os.path.expandvars(expanded)).expanduser()


def resolve_config_path(config_path: Path, value: str) -> Path:
    path = expand_environment_path(value)
    if not path.is_absolute():
        path = config_path.parent / path
    return path.resolve()


def _signature(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return stat.st_size, stat.st_mtime_ns


def _firmware_signatures(directories: Iterable[Path]) -> dict[Path, tuple[int, int]]:
    signatures: dict[Path, tuple[int, int]] = {}
    for directory in directories:
        if not directory.is_dir():
            continue
        for path in directory.glob("*.fw"):
            signature = _signature(path)
            if signature is not None:
                signatures[path.resolve()] = signature
    return signatures


def clear_previous_authorized_firmware(
    authorization_directory: Path,
    source_firmware: Path,
) -> None:
    """Delete previous authorization outputs without deleting the new input."""
    source = source_firmware.resolve()
    for path in authorization_directory.glob("*.fw"):
        if path.resolve() == source:
            continue
        try:
            path.unlink()
        except OSError as error:
            raise FirmwareAutomationError(
                f"无法删除旧授权固件 {path}：{error}"
            ) from error


def generate_firmware(
    dir_music: Path,
    strong_burn_directory: Path,
    toy_directory_name: str,
    download_batch_name: str,
    firmware_name: str,
    timeout_seconds: int,
) -> Path:
    """Copy dir_music, run download.bat, and require a newly generated firmware."""
    if not dir_music.is_file():
        raise FirmwareAutomationError(f"找不到待强烧的文件：{dir_music}")
    if not strong_burn_directory.is_dir():
        raise FirmwareAutomationError(f"找不到强烧工具目录：{strong_burn_directory}")
    batch = strong_burn_directory / download_batch_name
    if not batch.is_file():
        raise FirmwareAutomationError(f"找不到强烧脚本：{batch}")
    toy_directory = strong_burn_directory / toy_directory_name
    if not toy_directory.is_dir():
        raise FirmwareAutomationError(f"找不到强烧 toy 目录：{toy_directory}")

    staged = toy_directory / dir_music.name
    firmware = toy_directory / firmware_name
    if staged.resolve() != dir_music.resolve():
        shutil.copy2(dir_music, staged)
    firmware.unlink(missing_ok=True)

    comspec = os.environ.get("COMSPEC", "cmd.exe")
    try:
        process = subprocess.run(
            [comspec, "/d", "/c", "call", str(batch)],
            cwd=str(strong_burn_directory),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout_seconds,
            creationflags=no_window_creation_flags(),
        )
    except subprocess.TimeoutExpired as error:
        raise FirmwareAutomationError(
            f"{download_batch_name} 执行超过 {timeout_seconds} 秒"
        ) from error
    if process.returncode:
        detail = process.stdout.strip()
        raise FirmwareAutomationError(
            f"{download_batch_name} 退出代码 {process.returncode}"
            + (f"：{detail}" if detail else "")
        )
    if not firmware.is_file():
        detail = process.stdout.strip()
        raise FirmwareAutomationError(
            f"{download_batch_name} 结束但未生成 {firmware}"
            + (f"：{detail}" if detail else "")
        )
    return firmware


def _click_control_by_text(window: Any, text: str, occurrence: int = 0) -> Any:
    matches = []
    for control in window.descendants():
        try:
            if control.window_text().strip() == text and control.is_enabled():
                matches.append(control)
        except Exception:
            continue
    if len(matches) <= occurrence:
        raise FirmwareAutomationError(
            f"授权工具中没有找到第 {occurrence + 1} 个“{text}”控件"
        )
    control = matches[occurrence]
    try:
        control.click_input()
    except Exception:
        control.click()
    return control


def _process_window_handles(process_id: int) -> set[int]:
    from pywinauto import Desktop

    return {
        int(window.handle)
        for window in Desktop(backend="win32").windows(
            process=process_id,
            visible_only=True,
        )
        if getattr(window, "handle", None)
    }


def _wait_for_process_dialog(
    process_id: int,
    previous_handles: set[int],
    timeout_seconds: int,
) -> Any:
    from pywinauto import Desktop

    desktop = Desktop(backend="win32")
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        for dialog in desktop.windows(process=process_id, visible_only=True):
            handle = int(getattr(dialog, "handle", 0))
            if handle and handle not in previous_handles:
                return dialog
        time.sleep(0.1)
    raise FirmwareAutomationError("点击“打开”后没有出现该授权工具的文件选择窗口")


def _filename_edit(dialog: Any) -> Any:
    for control_id in (1148, 1152):
        try:
            edit = dialog.child_window(control_id=control_id, class_name="Edit")
            edit.wait("exists enabled", timeout=1)
            return edit
        except Exception:
            continue
    raise FirmwareAutomationError(
        "文件选择窗口中没有找到文件名控件（control id 1148/1152）"
    )


def _choose_file(
    application: Any,
    window: Any,
    path: Path,
    occurrence: int,
    timeout_seconds: int,
) -> None:
    previous_handles = _process_window_handles(application.process)
    _click_control_by_text(window, "打开", occurrence)
    dialog = _wait_for_process_dialog(
        application.process,
        previous_handles,
        timeout_seconds,
    )
    edit = _filename_edit(dialog)
    edit.set_edit_text(str(path))
    edit.set_focus()
    edit.type_keys("{ENTER}")
    try:
        dialog.wait_not("visible", timeout=timeout_seconds)
    except Exception as error:
        raise FirmwareAutomationError("提交文件后选择窗口仍未关闭") from error


def _radio_is_selected(control: Any) -> bool:
    for method_name in ("get_check_state", "get_toggle_state", "is_checked"):
        method = getattr(control, method_name, None)
        if callable(method):
            try:
                return bool(method())
            except Exception:
                pass
    if os.name == "nt" and getattr(control, "handle", None):
        import ctypes

        return bool(
            ctypes.windll.user32.SendMessageW(
                int(control.handle),
                0x00F0,
                0,
                0,
            )
        )
    return False


def _select_unlimited_radio(window: Any) -> None:
    controls = []
    for control in window.descendants():
        try:
            class_name = control.class_name().casefold()
            if (
                control.window_text().strip() == "无限制"
                and control.is_enabled()
                and (
                    "radio" in class_name
                    or any(
                        callable(getattr(control, method, None))
                        for method in (
                            "get_check_state",
                            "get_toggle_state",
                            "is_checked",
                        )
                    )
                )
            ):
                controls.append(control)
        except Exception:
            continue
    if not controls:
        raise FirmwareAutomationError("授权工具中没有找到“无限制”单选控件")
    control = controls[0]
    if not _radio_is_selected(control):
        try:
            control.click_input()
        except Exception:
            control.click()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if _radio_is_selected(control):
            return
        time.sleep(0.1)
    raise FirmwareAutomationError("点击“无限制”后未能确认该选项已选中")


def authorize_firmware(
    firmware: Path,
    authorization_directory: Path,
    executable_name: str,
    key_name: str,
    window_title_regex: str,
    timeout_seconds: int,
) -> Path:
    """Authorize firmware through the AD15n GUI and return the updated .fw."""
    from pywinauto import Application

    executable = authorization_directory / executable_name
    key_file = authorization_directory / key_name
    if not executable.is_file():
        raise FirmwareAutomationError(f"找不到授权工具：{executable}")
    if not key_file.is_file():
        raise FirmwareAutomationError(f"找不到授权 KEY 文件：{key_file}")
    if not firmware.is_file():
        raise FirmwareAutomationError(f"找不到待授权固件：{firmware}")

    clear_previous_authorized_firmware(authorization_directory, firmware)
    output_directories = (authorization_directory, firmware.parent)
    application = Application(backend="win32").start(
        f'"{executable}"',
        work_dir=str(authorization_directory),
        create_new_console=False,
    )
    window = application.window(title_re=window_title_regex)
    try:
        window.wait("visible enabled ready", timeout=timeout_seconds)
        _choose_file(application, window, firmware, 0, timeout_seconds)
        _choose_file(application, window, key_file, 1, timeout_seconds)
        _select_unlimited_radio(window)
        previous = _firmware_signatures(output_directories)
        _click_control_by_text(window, "授权")

        deadline = time.monotonic() + timeout_seconds
        stable_path: Path | None = None
        stable_signature: tuple[int, int] | None = None
        stable_polls = 0
        while time.monotonic() < deadline:
            current = _firmware_signatures(output_directories)
            changed = [
                path
                for path, signature in current.items()
                if previous.get(path) != signature
            ]
            if changed:
                candidate = max(
                    changed,
                    key=lambda path: path.stat().st_mtime_ns,
                )
                signature = current[candidate]
                if signature[0] > 0 and (
                    candidate == stable_path and signature == stable_signature
                ):
                    stable_polls += 1
                else:
                    stable_path = candidate
                    stable_signature = signature
                    stable_polls = 1
                if stable_polls >= 3:
                    return candidate
            else:
                stable_path = None
                stable_signature = None
                stable_polls = 0
            time.sleep(0.25)
        raise FirmwareAutomationError(
            f"点击授权后 {timeout_seconds} 秒内未检测到新增或更新的 .fw 文件"
        )
    except Exception as error:
        diagnostics = authorization_directory / "authorization-controls.txt"
        try:
            window.print_control_identifiers(filename=str(diagnostics))
        except Exception:
            pass
        if isinstance(error, FirmwareAutomationError):
            raise
        raise FirmwareAutomationError(
            f"授权工具自动操作失败：{error}；控件信息：{diagnostics}"
        ) from error
    finally:
        try:
            application.kill()
        except Exception:
            pass


def run_firmware_workflow(
    dir_music: Path,
    config: Any,
    config_path: Path,
) -> Path:
    """Generate jl_isd.fw and authorize it when firmware processing is enabled."""
    if not config.firmware_enabled:
        return dir_music
    strong_burn_directory = resolve_config_path(
        config_path,
        config.strong_burn_directory,
    )
    authorization_directory = resolve_config_path(
        config_path,
        config.authorization_directory,
    )
    print(f"[强烧] 复制 {dir_music.name} 到 toy 并执行强烧……", flush=True)
    firmware = generate_firmware(
        dir_music,
        strong_burn_directory,
        config.strong_burn_toy_directory_name,
        config.strong_burn_batch_name,
        config.strong_burn_firmware_name,
        config.strong_burn_timeout_seconds,
    )
    print(f"[强烧] 已生成并校验：{firmware}", flush=True)
    print("[授权] 选择固件与 KEY，设置“无限制”并执行授权……", flush=True)
    authorized = authorize_firmware(
        firmware,
        authorization_directory,
        config.authorization_executable_name,
        config.authorization_key_name,
        config.authorization_window_title_regex,
        config.authorization_timeout_seconds,
    )
    print(f"[授权] 已授权固件：{authorized}", flush=True)
    return authorized
