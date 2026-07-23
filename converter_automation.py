"""Automation for AD140 音频文件转换工具 1.2.2 on Windows."""

from __future__ import annotations

import json
import importlib
import os
import site
import subprocess
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence


PYWINAUTO_VERSION = "0.6.9"
FORMATS = {"A", "E", "F1A", "F1C", "UMP3"}
SAMPLE_RATES = {"8K", "12K", "16K", "24K", "32K"}
BIT_RATES = {"8K", "16K", "24K", "32K", "40K", "48K", "56K", "64K"}
CONVERTER_INPUT_EXTENSIONS = {
    ".wav",
    ".mp3",
    ".m4a",
    ".aac",
    ".flac",
    ".ogg",
    ".opus",
    ".wma",
}


class ConverterAutomationError(RuntimeError):
    """Expected converter setup or automation failure."""


@dataclass
class ConverterConfig:
    enabled: bool = True
    converter_path: str = ""
    format: str = "F1A"
    sample_rate: str = "32K"
    bit_rate: str = "32K"
    output_folder_name: str = "converted"
    auto_install_pywinauto: bool = True
    clear_existing_files: bool = True
    window_title_regex: str = r".*音频文件转换工具.*"
    startup_timeout_seconds: int = 20
    conversion_timeout_seconds: int = 120
    packer_enabled: bool = True
    packer_path: str = ""
    packer_window_title_regex: str = r".*调整文件顺序.*"
    packer_output_name: str = "OUTPUT.LST"
    packer_timeout_seconds: int = 30
    packres_input_directory: str = "test_dir"
    packres_batch_name: str = "new_packres.bat"
    packres_output_name: str = "dir_music"
    packres_timeout_seconds: int = 60

    def validate(self) -> None:
        self.format = self.format.upper()
        self.sample_rate = self.sample_rate.upper()
        self.bit_rate = self.bit_rate.upper()
        if self.format not in FORMATS:
            raise ConverterAutomationError(
                f"不支持的转换格式 {self.format!r}；可选值：{', '.join(sorted(FORMATS))}"
            )
        if self.sample_rate not in SAMPLE_RATES:
            raise ConverterAutomationError(
                "不支持的采样率 "
                f"{self.sample_rate!r}；可选值：{', '.join(sorted(SAMPLE_RATES))}"
            )
        if self.bit_rate not in BIT_RATES:
            raise ConverterAutomationError(
                f"不支持的码率 {self.bit_rate!r}；可选值：{', '.join(sorted(BIT_RATES))}"
            )
        if not self.output_folder_name.strip():
            raise ConverterAutomationError("output_folder_name 不能为空")
        if self.startup_timeout_seconds < 1:
            raise ConverterAutomationError("startup_timeout_seconds 必须大于 0")
        if self.conversion_timeout_seconds < 1:
            raise ConverterAutomationError("conversion_timeout_seconds 必须大于 0")
        if not self.packer_output_name.strip():
            raise ConverterAutomationError("packer_output_name 不能为空")
        if self.packer_timeout_seconds < 1:
            raise ConverterAutomationError("packer_timeout_seconds 必须大于 0")
        if not self.packres_input_directory.strip():
            raise ConverterAutomationError("packres_input_directory 不能为空")
        if not self.packres_batch_name.strip():
            raise ConverterAutomationError("packres_batch_name 不能为空")
        if not self.packres_output_name.strip():
            raise ConverterAutomationError("packres_output_name 不能为空")
        if self.packres_timeout_seconds < 1:
            raise ConverterAutomationError("packres_timeout_seconds 必须大于 0")


def load_converter_config(path: Path) -> ConverterConfig:
    if not path.is_file():
        raise ConverterAutomationError(f"找不到转换配置文件：{path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise ConverterAutomationError(f"无法读取转换配置：{error}") from error
    if not isinstance(raw, dict):
        raise ConverterAutomationError("转换配置的顶层必须是 JSON 对象")
    known_fields = set(ConverterConfig.__dataclass_fields__)
    unknown = set(raw) - known_fields
    if unknown:
        raise ConverterAutomationError(
            f"转换配置包含未知字段：{', '.join(sorted(unknown))}"
        )
    config = ConverterConfig(**raw)
    config.validate()
    return config


def save_converter_config(path: Path, config: ConverterConfig) -> None:
    path.write_text(
        json.dumps(asdict(config), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def choose_converter_executable() -> Path | None:
    if os.name != "nt":
        return None
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askopenfilename(
            title="请选择音频文件转换工具 EXE",
            filetypes=[("Windows 程序", "*.exe"), ("所有文件", "*.*")],
        )
        root.destroy()
    except Exception as error:
        raise ConverterAutomationError(f"无法打开 EXE 选择窗口：{error}") from error
    return Path(selected).resolve() if selected else None


def resolve_converter_executable(
    config: ConverterConfig,
    config_path: Path,
) -> Path:
    configured = Path(config.converter_path).expanduser() if config.converter_path else None
    if configured and configured.is_file():
        return configured.resolve()
    selected = choose_converter_executable()
    if not selected:
        if configured:
            raise ConverterAutomationError(
                f"转换工具路径无效：{configured}。请修改 {config_path.name} 中的 converter_path。"
            )
        raise ConverterAutomationError(
            f"尚未选择转换工具。请填写 {config_path.name} 中的 converter_path。"
        )
    config.converter_path = str(selected)
    save_converter_config(config_path, config)
    return selected


def conversion_output_directory(
    raw_inputs: Sequence[str],
    script_directory: Path,
    folder_name: str,
) -> Path:
    if not raw_inputs:
        base = Path.cwd()
    elif len(raw_inputs) == 1 and Path(raw_inputs[0]).expanduser().is_dir():
        supplied = Path(raw_inputs[0]).expanduser().resolve()
        base = supplied.parent if supplied.name.casefold() == "processed" else supplied
    else:
        base = script_directory.resolve()
    output = base / folder_name
    output.mkdir(parents=True, exist_ok=True)
    return output


def ensure_pywinauto(auto_install: bool) -> None:
    try:
        importlib.import_module("win32api")
        importlib.import_module("pywinauto")
        return
    except ImportError:
        pass
    if not auto_install:
        raise ConverterAutomationError(
            f"缺少 pywinauto。请运行：{sys.executable} -m pip install "
            f"pywinauto=={PYWINAUTO_VERSION}"
        )
    print(f"正在安装 Windows 自动化组件 pywinauto {PYWINAUTO_VERSION}……", flush=True)
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        f"pywinauto=={PYWINAUTO_VERSION}",
    ]
    process = subprocess.run(command, check=False)
    if process.returncode:
        raise ConverterAutomationError(
            "pywinauto 安装失败。请联网后手动运行：" + " ".join(command)
        )
    # pip installed pywin32 into the already-running interpreter. Its
    # pywin32.pth file (which adds site-packages/win32 for win32api) is normally
    # processed only at Python startup, so process it now before importing.
    package_directories = list(site.getsitepackages())
    user_site = site.getusersitepackages()
    if isinstance(user_site, str):
        package_directories.append(user_site)
    for directory in package_directories:
        if Path(directory).is_dir():
            site.addsitedir(directory)
    importlib.invalidate_caches()
    sys.modules.pop("win32api", None)
    sys.modules.pop("pywinauto", None)
    try:
        importlib.import_module("win32api")
        importlib.import_module("pywinauto")
    except ImportError as error:
        raise ConverterAutomationError(
            "自动化组件已安装，但当前 Python 进程尚未识别 win32api。"
            "请关闭此窗口并重新运行“处理音频.bat”。"
        ) from error


def file_dialog_text(files: Iterable[Path]) -> str:
    return " ".join(f'"{path.resolve()}"' for path in files)


def file_batches(
    files: Sequence[Path],
    max_files: int = 8,
    max_characters: int = 3000,
) -> list[list[Path]]:
    batches: list[list[Path]] = []
    current: list[Path] = []
    current_length = 0
    for path in files:
        item_length = len(str(path.resolve())) + 3
        if current and (
            len(current) >= max_files
            or current_length + item_length > max_characters
        ):
            batches.append(current)
            current = []
            current_length = 0
        current.append(path)
        current_length += item_length
    if current:
        batches.append(current)
    return batches


def whole_folder_selection_candidate(files: Sequence[Path]) -> Path | None:
    if not files:
        return None
    resolved = [path.resolve() for path in files]
    parents = {path.parent for path in resolved}
    if len(parents) != 1:
        return None
    parent = next(iter(parents))
    requested = {str(path).casefold() for path in resolved}
    available = {
        str(path.resolve()).casefold()
        for path in parent.iterdir()
        if path.is_file() and path.suffix.lower() in CONVERTER_INPUT_EXTENSIONS
    }
    return parent if available == requested else None


def _visible_controls(window: Any, control_type: str) -> list[Any]:
    return [
        control
        for control in window.descendants(control_type=control_type)
        if control.is_visible() and control.is_enabled()
    ]


def _click_button(window: Any, title: str) -> None:
    try:
        button = window.child_window(title=title, control_type="Button")
        button.wait("visible enabled", timeout=2)
        button.click()
        return
    except Exception:
        pass
    normalized_title = "".join(title.split())
    for button in _visible_controls(window, "Button"):
        if "".join(button.window_text().split()) == normalized_title:
            button.click()
            return
    raise ConverterAutomationError(f"没有找到按钮：{title}")


def _select_radio(window: Any, title: str, column: int) -> None:
    radios = _visible_controls(window, "RadioButton")
    if not radios:
        raise ConverterAutomationError("转换工具中没有找到格式、采样率或码率选项")

    left_positions = sorted({control.rectangle().left for control in radios})
    columns: list[list[int]] = []
    for left in left_positions:
        if not columns or left - columns[-1][-1] > 30:
            columns.append([left])
        else:
            columns[-1].append(left)
    if len(columns) < 3:
        raise ConverterAutomationError(
            f"只识别到 {len(columns)} 组单选按钮，预期至少 3 组"
        )
    center = sum(columns[column]) / len(columns[column])
    matches = [
        control
        for control in radios
        if control.window_text().strip().upper() == title.upper()
    ]
    if not matches:
        raise ConverterAutomationError(f"没有找到选项：{title}")
    selected = min(matches, key=lambda control: abs(control.rectangle().left - center))
    errors: list[str] = []
    for method_name in ("select", "click"):
        try:
            getattr(selected, method_name)()
            time.sleep(0.1)
            if selected.is_selected():
                return
        except Exception as error:
            errors.append(f"{method_name}: {error}")
    raise ConverterAutomationError(
        f"选项 {title} 未被选中；" + "；".join(errors)
    )


def _native_window_text(control: Any) -> str:
    handle = getattr(control, "handle", None)
    if os.name != "nt" or not handle:
        return ""
    try:
        import ctypes

        user32 = ctypes.windll.user32
        user32.GetWindowTextLengthW.argtypes = [ctypes.c_void_p]
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_int,
        ]
        user32.GetWindowTextW.restype = ctypes.c_int
        length = user32.GetWindowTextLengthW(int(handle))
        buffer = ctypes.create_unicode_buffer(max(length + 1, 2))
        user32.GetWindowTextW(int(handle), buffer, len(buffer))
        return buffer.value
    except Exception:
        return ""


def _read_control_text(control: Any) -> str:
    native_text = _native_window_text(control)
    if native_text:
        return native_text
    for method_name in ("get_value", "window_text"):
        try:
            value = getattr(control, method_name)()
            if value:
                return str(value)
        except Exception:
            continue
    return ""


def _native_set_window_text(control: Any, text: str) -> bool:
    handle = getattr(control, "handle", None)
    if os.name != "nt" or not handle:
        return False
    try:
        import ctypes

        set_window_text = ctypes.windll.user32.SetWindowTextW
        set_window_text.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        set_window_text.restype = ctypes.c_int
        return bool(set_window_text(int(handle), str(text)))
    except Exception:
        return False


def _same_windows_path(actual: str, expected: str) -> bool:
    if not actual:
        return False
    return os.path.normcase(os.path.normpath(actual.strip().strip('"'))) == os.path.normcase(
        os.path.normpath(expected)
    )


def _click_folder_confirmation(dialog: Any) -> None:
    buttons = _visible_controls(dialog, "Button")
    preferred = (
        "选择文件夹",
        "选择此文件夹",
        "确定",
        "selectfolder",
        "ok",
    )
    for expected in preferred:
        for button in buttons:
            title = "".join(button.window_text().split()).casefold()
            if title == expected.casefold() or expected.casefold() in title:
                button.click()
                return
    available = [
        " ".join(button.window_text().split())
        for button in buttons
        if button.window_text().strip()
    ]
    raise ConverterAutomationError(
        "文件夹选择窗口没有找到“选择文件夹/确定”按钮；"
        f"可见按钮：{available}"
    )


def _wait_for_directory_value(
    edit: Any,
    expected: str,
    timeout: float = 10,
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _same_windows_path(_read_control_text(edit), expected):
            return True
        time.sleep(0.2)
    return False


def _choose_output_directory_with_dialog(
    window: Any,
    edit: Any,
    output_directory: Path,
) -> None:
    from pywinauto import Desktop

    desktop = Desktop(backend="uia")
    previous_handles = _window_handles(window, desktop)
    _click_button(window, "打开")
    dialog = _find_new_dialog(window, desktop, previous_handles)
    dialog.set_focus()
    _set_windows_clipboard(str(output_directory))
    _send_keys("^l")
    _send_keys("^a")
    _send_keys("^v")
    _send_keys("{ENTER}")
    time.sleep(0.5)
    _click_folder_confirmation(dialog)
    if not _wait_for_directory_value(edit, str(output_directory)):
        actual = _read_control_text(edit)
        raise ConverterAutomationError(
            "通过“打开”选择目录后校验失败："
            f"期望 {str(output_directory)!r}，控件实际值 {actual!r}"
        )


def _set_output_directory(window: Any, output_directory: Path) -> None:
    edits = _visible_controls(window, "Edit")
    if not edits:
        raise ConverterAutomationError("没有找到“保存目录”输入框")
    # The converter 1.2.2 main window has one editable text field: 保存目录.
    edit = max(edits, key=lambda control: control.rectangle().width())
    expected = str(output_directory)

    # Its UIA ValuePattern raises .NET InvalidOperationException (0x80131509).
    # WM_SETTEXT does not depend on DPI coordinates and works with this native
    # custom edit.
    _native_set_window_text(edit, expected)
    time.sleep(0.1)
    if _same_windows_path(_read_control_text(edit), expected):
        return

    # Fallback for variants without a native HWND.
    try:
        edit.set_focus()
    except Exception:
        edit.click_input()
    _set_windows_clipboard(expected)
    _send_keys("^a")
    _send_keys("^v")
    _send_keys("{TAB}")
    time.sleep(0.2)
    actual = _read_control_text(edit)
    if _same_windows_path(actual, expected):
        return

    # This build ignores all direct writes. Use its own folder picker so the
    # application updates its internal output-directory state as well as the
    # visible text.
    _choose_output_directory_with_dialog(window, edit, output_directory)


def _window_handles(window: Any, desktop: Any) -> set[int]:
    controls: list[Any] = []
    try:
        controls.extend(desktop.windows())
    except Exception:
        pass
    try:
        controls.extend(window.descendants(control_type="Window"))
    except Exception:
        pass
    return {
        int(control.handle)
        for control in controls
        if getattr(control, "handle", None)
    }


def _find_new_dialog(
    window: Any,
    desktop: Any,
    previous_handles: set[int],
    timeout: float = 10,
) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        candidates: list[Any] = []
        try:
            candidates.extend(desktop.windows())
        except Exception:
            pass
        try:
            candidates.extend(window.descendants(control_type="Window"))
        except Exception:
            pass
        for candidate in reversed(candidates):
            handle = getattr(candidate, "handle", None)
            if (
                handle
                and int(handle) not in previous_handles
                and candidate.is_visible()
            ):
                return candidate
        time.sleep(0.2)
    raise ConverterAutomationError("点击“添加文件”后没有识别到新文件选择窗口")


def _set_windows_clipboard(text: str) -> None:
    try:
        import win32clipboard

        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
        finally:
            win32clipboard.CloseClipboard()
    except Exception as error:
        raise ConverterAutomationError(f"无法将文件路径写入剪贴板：{error}") from error


def _send_keys(keys: str) -> None:
    from pywinauto.keyboard import send_keys

    send_keys(keys)


def _wait_until_hidden(window: Any, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if not window.is_visible():
                return
        except Exception:
            return
        time.sleep(0.2)
    raise ConverterAutomationError("提交文件路径后，文件选择窗口没有关闭")


def _data_item_count(window: Any) -> int:
    try:
        return len(window.descendants(control_type="DataItem"))
    except Exception:
        return 0


def _wait_for_added_files(
    window: Any,
    previous_item_count: int,
    timeout: float = 30,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _data_item_count(window) > previous_item_count:
            return
        time.sleep(0.2)
    raise ConverterAutomationError("提交文件路径后，转换文件列表没有增加")


def _file_snapshot(directory: Path) -> dict[str, tuple[int, int]]:
    snapshot: dict[str, tuple[int, int]] = {}
    for path in directory.rglob("*"):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        snapshot[str(path.resolve()).casefold()] = (stat.st_mtime_ns, stat.st_size)
    return snapshot


def _matching_output_count(
    output_directory: Path,
    expected_inputs: Sequence[Path],
) -> int:
    expected = Counter(path.stem.casefold() for path in expected_inputs)
    available = Counter(
        path.stem.casefold()
        for path in output_directory.rglob("*")
        if path.is_file()
    )
    return sum(
        min(count, available.get(stem, 0))
        for stem, count in expected.items()
    )


def _new_visible_windows(
    window: Any,
    desktop: Any,
    previous_handles: set[int],
) -> list[Any]:
    candidates: list[Any] = []
    try:
        candidates.extend(desktop.windows())
    except Exception:
        pass
    try:
        candidates.extend(window.descendants(control_type="Window"))
    except Exception:
        pass
    unique: dict[int, Any] = {}
    for candidate in candidates:
        handle = getattr(candidate, "handle", None)
        if not handle or int(handle) in previous_handles:
            continue
        try:
            if candidate.is_visible():
                unique[int(handle)] = candidate
        except Exception:
            continue
    return list(unique.values())


def _window_message(window: Any) -> str:
    messages: list[str] = []
    try:
        title = " ".join(window.window_text().split())
        if title:
            messages.append(title)
    except Exception:
        pass
    try:
        for control in window.descendants(control_type="Text"):
            text = " ".join(control.window_text().split())
            if text and text not in messages:
                messages.append(text)
    except Exception:
        pass
    if not messages and getattr(window, "handle", None):
        try:
            from pywinauto import Desktop

            native = Desktop(backend="win32").window(handle=int(window.handle))
            for control in native.descendants():
                text = " ".join(control.window_text().split())
                if text and text not in messages:
                    messages.append(text)
        except Exception:
            pass
    return "；".join(messages)


def _converter_dialog_is_error(message: str) -> bool:
    normalized = message.casefold()
    return any(
        marker in normalized
        for marker in (
            "错误",
            "失败",
            "没有与搜索条件匹配",
            "请选择",
            "异常",
            "error",
            "failed",
            "no match",
        )
    )


def _converter_dialog_is_success(message: str) -> bool:
    normalized = message.casefold()
    return any(
        marker in normalized
        for marker in ("转换完成", "转换成功", "完成", "成功", "complete", "success")
    )


def _dismiss_converter_dialog(dialog: Any) -> bool:
    try:
        buttons = dialog.descendants(control_type="Button")
    except Exception:
        buttons = []
    for preferred in ("确定", "完成", "ok", "关闭", "close"):
        for button in buttons:
            title = "".join(button.window_text().split()).casefold()
            if title == preferred.casefold() or preferred.casefold() in title:
                button.click()
                return True
    try:
        dialog.set_focus()
        _send_keys("{ENTER}")
        return True
    except Exception:
        return False


def _wait_for_conversion_outputs(
    window: Any,
    desktop: Any,
    output_directory: Path,
    previous_files: dict[str, tuple[int, int]],
    previous_handles: set[int],
    expected_count: int,
    timeout: float,
    expected_inputs: Sequence[Path] = (),
) -> int:
    deadline = time.monotonic() + timeout
    last_dialog_message = ""
    last_progress_report = 0.0
    found_count = 0
    completion_seen = False
    while time.monotonic() < deadline:
        current_files = _file_snapshot(output_directory)
        changed = [
            path
            for path, signature in current_files.items()
            if previous_files.get(path) != signature
        ]
        changed_count = len(changed)
        matched_count = (
            _matching_output_count(output_directory, expected_inputs)
            if expected_inputs
            else changed_count
        )
        found_count = matched_count
        if changed_count >= expected_count or (
            matched_count >= expected_count
            and (changed_count > 0 or completion_seen)
        ):
            return matched_count
        new_windows = _new_visible_windows(window, desktop, previous_handles)
        for candidate in new_windows:
            message = _window_message(candidate)
            if message and _converter_dialog_is_error(message):
                raise ConverterAutomationError(f"转换工具提示：{message}")
            if message and _converter_dialog_is_success(message):
                completion_seen = True
            if message:
                last_dialog_message = message
            _dismiss_converter_dialog(candidate)
        if matched_count >= expected_count and completion_seen:
            return matched_count
        now = time.monotonic()
        if now - last_progress_report >= 10:
            print(
                f"[转换] 已发现 {found_count}/{expected_count} 个结果，继续等待……",
                flush=True,
            )
            last_progress_report = now
        time.sleep(0.25)
    detail = f"；最后提示：{last_dialog_message}" if last_dialog_message else ""
    raise ConverterAutomationError(
        f"{timeout:g} 秒内未在 {output_directory} 发现 "
        f"{expected_count} 个转换结果（实际 {found_count} 个）{detail}"
    )


def _find_filename_edit(
    dialog: Any,
    allow_generic_edit: bool = False,
) -> Any | None:
    # Prefer the stable common-dialog automation id. Do not guess among visible
    # Edit controls: in this converter the only UIA-visible edit is the search
    # box, which sends pasted filenames into Windows Search.
    for auto_id in ("1148", "1152"):
        try:
            filename = dialog.child_window(auto_id=auto_id, control_type="Edit")
            filename.wait("visible enabled", timeout=2)
            return filename
        except Exception:
            pass

    # The converter's file dialog hides the filename field from UIA but still
    # exposes the classic Win32 control id 1148. Attach to the same handle with
    # the win32 backend so Unicode paths are written into the correct field.
    from pywinauto import Desktop

    handles: list[int] = []
    if getattr(dialog, "handle", None):
        handles.append(int(dialog.handle))
    try:
        handles.extend(
            int(control.handle)
            for control in dialog.descendants(control_type="Window")
            if getattr(control, "handle", None)
        )
    except Exception:
        pass
    win32_roots: list[Any] = []
    for handle in dict.fromkeys(handles):
        win32_dialog = Desktop(backend="win32").window(handle=handle)
        win32_roots.append(win32_dialog)
        for control_id in (1148, 1152):
            try:
                filename = win32_dialog.child_window(
                    control_id=control_id,
                    class_name="Edit",
                )
                filename.wait("exists enabled", timeout=1)
                return filename
            except Exception:
                continue

    if allow_generic_edit:
        # Old Delphi TSaveDialog variants may nest the file-name Edit inside
        # ComboBoxEx32/ComboBox and expose neither modern automation id. The
        # filename field is the lowest visible Edit in a standard Save As
        # dialog; the search field is near the top.
        generic_edits: list[Any] = []
        try:
            generic_edits.extend(
                control
                for control in dialog.descendants(control_type="Edit")
                if control.is_visible() and control.is_enabled()
            )
        except Exception:
            pass
        for root in win32_roots:
            try:
                generic_edits.extend(
                    control
                    for control in root.descendants(class_name="Edit")
                    if control.is_visible() and control.is_enabled()
                )
            except Exception:
                pass
        if generic_edits:
            return max(
                generic_edits,
                key=lambda control: (
                    control.rectangle().top,
                    control.rectangle().width(),
                ),
            )
    return None


def _wait_for_file_dialog_submission(
    control: Any,
    dialog: Any,
    timeout: float = 30,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if not control.is_visible():
                return
        except Exception:
            return
        time.sleep(0.2)
    message = _window_message(dialog)
    raise ConverterAutomationError(
        "提交文件后选择窗口仍未关闭"
        + (f"：{message}" if message else "")
    )


def _add_file_batch(
    window: Any,
    files: Sequence[Path],
    desktop: Any,
) -> None:
    previous_item_count = _data_item_count(window)
    previous_handles = _window_handles(window, desktop)
    _click_button(window, "添加文件")
    dialog = _find_new_dialog(window, desktop, previous_handles)
    file_text = file_dialog_text(files)
    filename = _find_filename_edit(dialog)

    if filename is not None:
        filename.set_edit_text(file_text)
        filename.set_focus()
    else:
        # Some versions expose the common file dialog as custom/shell panes
        # only. Alt+N focuses its standard 文件名(N) field; clipboard paste
        # preserves Chinese paths that pywinauto.type_keys cannot type.
        dialog.set_focus()
        _set_windows_clipboard(file_text)
        _send_keys("%n")
        _send_keys("^a^v")

    _send_keys("{ENTER}")
    monitor = filename if filename is not None else dialog
    _wait_for_file_dialog_submission(monitor, dialog)
    if previous_item_count == 0:
        _wait_for_added_files(window, previous_item_count)
    else:
        # UIA virtualizes rows once the table is full, so its visible DataItem
        # count may stop growing even though later batches were accepted.
        time.sleep(0.3)


def _focus_win32_file_list(dialog: Any) -> bool:
    from pywinauto import Desktop

    handles: list[int] = []
    if getattr(dialog, "handle", None):
        handles.append(int(dialog.handle))
    try:
        handles.extend(
            int(control.handle)
            for control in dialog.descendants(control_type="Window")
            if getattr(control, "handle", None)
        )
    except Exception:
        pass
    for handle in dict.fromkeys(handles):
        try:
            root = Desktop(backend="win32").window(handle=handle)
            lists = root.descendants(class_name="SysListView32")
            if lists:
                lists[0].set_focus()
                return True
        except Exception:
            continue
    return False


def _mouse_click(coords: tuple[int, int]) -> None:
    from pywinauto import mouse

    mouse.click(button="left", coords=coords)


def _focus_file_list_for_select_all(dialog: Any) -> str:
    try:
        items_view = dialog.child_window(auto_id="ItemsView", control_type="List")
        items_view.wait("visible enabled", timeout=2)
        items_view.set_focus()
        return "ItemsView"
    except Exception:
        pass
    if _focus_win32_file_list(dialog):
        return "SysListView32"

    # Windows 11 may expose the shell list as DirectUI panes only. A physical
    # click inside the largest content pane gives the file list keyboard focus;
    # clicking an item or blank column is both safe because Ctrl+A follows.
    try:
        panes = [
            pane
            for pane in dialog.descendants(control_type="Pane")
            if pane.is_visible() and pane.is_enabled()
        ]
    except Exception:
        panes = []
    if not panes:
        raise ConverterAutomationError("文件窗口没有可点击的文件区域")
    pane = max(
        panes,
        key=lambda control: (
            control.rectangle().width() * control.rectangle().height()
        ),
    )
    rectangle = pane.rectangle()
    x = int(rectangle.left + rectangle.width() * 0.65)
    y = int(rectangle.top + rectangle.height() * 0.60)
    _mouse_click((x, y))
    time.sleep(0.2)
    return "文件区域点击"


def _add_whole_folder(
    window: Any,
    folder: Path,
    desktop: Any,
) -> None:
    previous_item_count = _data_item_count(window)
    previous_handles = _window_handles(window, desktop)
    _click_button(window, "添加文件")
    dialog = _find_new_dialog(window, desktop, previous_handles)
    filename = _find_filename_edit(dialog)
    try:
        dialog.set_focus()
        _set_windows_clipboard(str(folder))
        _send_keys("^l")
        _send_keys("^a")
        _send_keys("^v")
        _send_keys("{ENTER}")
        time.sleep(0.5)
        focus_method = _focus_file_list_for_select_all(dialog)
        print(f"[转换] 已通过{focus_method}聚焦文件列表。", flush=True)
    except Exception as error:
        try:
            dialog.set_focus()
            _send_keys("{ESC}")
            monitor = filename if filename is not None else dialog
            _wait_for_file_dialog_submission(monitor, dialog, timeout=5)
        except Exception:
            pass
        raise ConverterAutomationError(
            f"无法聚焦文件列表：{error}"
        ) from error
    try:
        _send_keys("^a")
        _send_keys("{ENTER}")
        monitor = filename if filename is not None else dialog
        _wait_for_file_dialog_submission(monitor, dialog)
        _wait_for_added_files(window, previous_item_count)
    except Exception:
        try:
            dialog.set_focus()
            _send_keys("{ESC}")
        except Exception:
            pass
        raise


def _add_files(window: Any, files: Sequence[Path], desktop: Any) -> None:
    folder = whole_folder_selection_candidate(files)
    if folder is not None:
        print(
            f"[转换] 所有文件位于同一目录，执行全选：{folder}",
            flush=True,
        )
        try:
            _add_whole_folder(window, folder, desktop)
            return
        except Exception as error:
            print(
                f"[转换] 文件夹全选不可用，回退到分批导入：{error}",
                flush=True,
            )

    batches = file_batches(files)
    if not batches:
        raise ConverterAutomationError("没有要添加的音频文件")
    for index, batch in enumerate(batches, start=1):
        print(
            f"[转换] 添加文件批次 {index}/{len(batches)}"
            f"（{len(batch)} 个）……",
            flush=True,
        )
        try:
            _add_file_batch(window, batch, desktop)
        except Exception as error:
            raise ConverterAutomationError(
                f"第 {index} 批文件添加失败：{error}"
            ) from error


def automate_converter(
    executable: Path,
    files: Sequence[Path],
    output_directory: Path,
    config: ConverterConfig,
    diagnostics_directory: Path,
) -> None:
    try:
        from pywinauto import Application, Desktop
    except ImportError as error:
        raise ConverterAutomationError(
            "无法加载 Windows 自动化组件。请关闭窗口并重新运行 BAT；"
            f"如果仍然失败，请执行：{sys.executable} -m pip install "
            f"--force-reinstall pywin32 pywinauto=={PYWINAUTO_VERSION}"
        ) from error

    diagnostics_directory.mkdir(parents=True, exist_ok=True)
    application = Application(backend="uia").start(
        f'"{executable}"',
        work_dir=str(executable.parent),
    )
    window = application.window(title_re=config.window_title_regex)
    try:
        window.wait(
            "visible enabled ready",
            timeout=config.startup_timeout_seconds,
        )
        window.set_focus()
        desktop = Desktop(backend="uia")
        if config.clear_existing_files:
            try:
                _click_button(window, "清空文件")
            except Exception:
                pass
        steps = [
            (
                "添加处理后的音频",
                lambda: _add_files(window, files, desktop),
            ),
            (
                "设置保存目录",
                lambda: _set_output_directory(window, output_directory),
            ),
            (
                f"选择格式 {config.format}",
                lambda: _select_radio(window, config.format, column=0),
            ),
            (
                f"选择采样率 {config.sample_rate}",
                lambda: _select_radio(window, config.sample_rate, column=1),
            ),
            (
                f"选择码率 {config.bit_rate}",
                lambda: _select_radio(window, config.bit_rate, column=2),
            ),
        ]
        for label, action in steps:
            print(f"[转换] {label}……", flush=True)
            try:
                action()
            except Exception as error:
                raise ConverterAutomationError(f"{label}失败：{error}") from error

        previous_files = _file_snapshot(output_directory)
        previous_handles = _window_handles(window, desktop)
        print("[转换] 点击开始转换……", flush=True)
        try:
            _click_button(window, "开始转换")
        except Exception as error:
            raise ConverterAutomationError(f"点击开始转换失败：{error}") from error
        print("[转换] 等待并校验转换结果……", flush=True)
        try:
            output_count = _wait_for_conversion_outputs(
                window,
                desktop,
                output_directory,
                previous_files,
                previous_handles,
                expected_count=len(files),
                timeout=max(
                    config.conversion_timeout_seconds,
                    len(files) * 5,
                ),
                expected_inputs=files,
            )
        except Exception as error:
            if isinstance(error, ConverterAutomationError):
                raise
            raise ConverterAutomationError(f"校验转换结果失败：{error}") from error
        print(f"[转换] 已确认生成 {output_count} 个结果文件。", flush=True)
    except Exception as error:
        controls_file = diagnostics_directory / "converter-controls.txt"
        try:
            window.print_control_identifiers(filename=str(controls_file))
        except Exception:
            pass
        if isinstance(error, ConverterAutomationError):
            raise
        raise ConverterAutomationError(
            f"转换工具自动操作失败：{error}。控件信息已保存到 {controls_file}"
        ) from error


def run_configured_converter(
    files: Sequence[Path],
    raw_inputs: Sequence[str],
    script_directory: Path,
    config_path: Path,
    include_packer: bool | None = None,
) -> Path | None:
    config = load_converter_config(config_path)
    if not config.enabled:
        return None
    if os.name != "nt":
        print("[转换] 当前不是 Windows，已跳过专用转换工具。", flush=True)
        return None
    existing_files = [path.resolve() for path in files if path.is_file()]
    if not existing_files:
        raise ConverterAutomationError("没有可添加到转换工具的成功输出文件")
    executable = resolve_converter_executable(config, config_path)
    output = conversion_output_directory(
        raw_inputs,
        script_directory,
        config.output_folder_name,
    )
    ensure_pywinauto(config.auto_install_pywinauto)
    automate_converter(
        executable,
        existing_files,
        output,
        config,
        output,
    )
    should_run_packer = (
        config.packer_enabled if include_packer is None else include_packer
    )
    if should_run_packer:
        try:
            from packer_automation import (
                PackerAutomationError,
                run_configured_packer,
            )

            package = run_configured_packer(output, config, config_path)
            if package:
                print(f"[合成] 最终输出已就绪：{package}", flush=True)
        except (ImportError, OSError, PackerAutomationError) as error:
            raise ConverterAutomationError(f"音频文件合成失败：{error}") from error
    return output
