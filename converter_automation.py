"""Automation for AD140 音频文件转换工具 1.2.2 on Windows."""

from __future__ import annotations

import json
import importlib
import os
import site
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence


PYWINAUTO_VERSION = "0.6.9"
FORMATS = {"A", "E", "F1A", "F1C", "UMP3"}
SAMPLE_RATES = {"8K", "12K", "16K", "24K", "32K"}
BIT_RATES = {"8K", "16K", "24K", "32K", "40K", "48K", "56K", "64K"}


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
        base = Path(raw_inputs[0]).expanduser().resolve()
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
    if not _same_windows_path(actual, expected):
        raise ConverterAutomationError(
            f"保存目录校验失败：期望 {expected!r}，控件实际值 {actual!r}"
        )


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
    return "；".join(messages)


def _wait_for_conversion_outputs(
    window: Any,
    desktop: Any,
    output_directory: Path,
    previous_files: dict[str, tuple[int, int]],
    previous_handles: set[int],
    expected_count: int,
    timeout: float,
) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        new_windows = _new_visible_windows(window, desktop, previous_handles)
        if new_windows:
            message = _window_message(new_windows[-1]) or "转换工具弹出错误窗口"
            raise ConverterAutomationError(f"转换工具提示：{message}")
        current_files = _file_snapshot(output_directory)
        changed = [
            path
            for path, signature in current_files.items()
            if previous_files.get(path) != signature
        ]
        if len(changed) >= expected_count:
            return len(changed)
        time.sleep(0.25)
    raise ConverterAutomationError(
        f"{timeout:g} 秒内未在 {output_directory} 发现 "
        f"{expected_count} 个转换结果"
    )


def _find_filename_edit(dialog: Any) -> Any | None:
    # Prefer the stable common-dialog automation id. Do not guess among visible
    # Edit controls: in this converter the only UIA-visible edit is the search
    # box, which sends pasted filenames into Windows Search.
    try:
        filename = dialog.child_window(auto_id="1148", control_type="Edit")
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
    for handle in dict.fromkeys(handles):
        try:
            win32_dialog = Desktop(backend="win32").window(handle=handle)
            filename = win32_dialog.child_window(control_id=1148, class_name="Edit")
            filename.wait("exists enabled", timeout=1)
            return filename
        except Exception:
            continue
    return None


def _add_files(window: Any, files: Sequence[Path], desktop: Any) -> None:
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
    # This converter reuses its own title/handle hierarchy for the common file
    # dialog, so waiting for the selected wrapper to disappear can actually
    # wait on the still-visible main window. The table row count is the
    # reliable success signal.
    _wait_for_added_files(window, previous_item_count)


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
                timeout=config.conversion_timeout_seconds,
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
    return output
