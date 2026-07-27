"""Automation for the AD140 pRFiles resource packing utility."""

from __future__ import annotations

import json
import ntpath
import os
import shutil
import subprocess
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any


class PackerAutomationError(RuntimeError):
    """Expected packer setup or UI automation failure."""


PACKED_AUDIO_EXTENSIONS = {".a", ".e", ".f1a", ".f1b", ".f1c", ".ump3"}


def choose_packer_executable() -> Path | None:
    if os.name != "nt":
        return None
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askopenfilename(
            title="请选择 AD140 打包工具 pRFiles.exe",
            filetypes=[("pRFiles", "pRFiles.exe"), ("Windows 程序", "*.exe")],
        )
        root.destroy()
    except Exception as error:
        raise PackerAutomationError(f"无法打开打包工具选择窗口：{error}") from error
    return Path(selected).resolve() if selected else None


def resolve_packer_executable(
    config: Any,
    config_path: Path,
) -> Path:
    configured = Path(config.packer_path).expanduser() if config.packer_path else None
    if configured and not configured.is_absolute():
        configured = config_path.parent / configured
    if configured and configured.is_file():
        return configured.resolve()
    selected = choose_packer_executable()
    if not selected:
        raise PackerAutomationError(
            f"打包工具路径无效：{configured or '(未填写)'}。"
            f"请修改 {config_path.name} 中的 packer_path。"
        )
    config.packer_path = str(selected)
    config_path.write_text(
        json.dumps(asdict(config), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return selected


def _normalize_tree_name(value: str) -> str:
    return value.strip().rstrip("\\/").casefold()


def _select_drive(window: Any, drive: str) -> None:
    desired = drive.rstrip("\\/").casefold()
    combos: list[Any] = []
    for class_name in ("TDriveComboBox", "ComboBox"):
        try:
            combos.extend(window.descendants(class_name=class_name))
        except Exception:
            pass
    for combo in combos:
        try:
            if combo.window_text().strip().casefold().startswith(desired):
                return
        except Exception:
            pass
        try:
            items = combo.item_texts()
        except Exception:
            continue
        for index, text in enumerate(items):
            if text.strip().casefold().startswith(desired):
                combo.select(index)
                time.sleep(0.3)
                return
    raise PackerAutomationError(f"磁盘下拉框中没有找到 {drive}")


def _find_directory_list(window: Any) -> Any:
    lists = window.descendants(class_name="TDirectoryListBox")
    if not lists:
        raise PackerAutomationError("没有找到 Delphi 目录列表 TDirectoryListBox")
    return lists[0]


def _matches_directory_component(item_text: str, component: str) -> bool:
    cleaned = item_text.strip().strip("[]").rstrip("\\/")
    basename = ntpath.basename(cleaned) or cleaned
    expected = component.strip().strip("[]").rstrip("\\/")
    expected_basename = ntpath.basename(expected) or expected
    return (
        basename.casefold() == expected_basename.casefold()
        or cleaned.casefold() == expected.casefold()
    )


def _activate_directory_selection(directory_list: Any) -> None:
    handle = getattr(directory_list, "handle", None)
    if not handle or os.name != "nt":
        try:
            directory_list.type_keys("{ENTER}")
            return
        except Exception as error:
            raise PackerAutomationError(f"无法进入选中的目录：{error}") from error
    try:
        import ctypes

        user32 = ctypes.windll.user32
        user32.GetParent.argtypes = [ctypes.c_void_p]
        user32.GetParent.restype = ctypes.c_void_p
        user32.GetDlgCtrlID.argtypes = [ctypes.c_void_p]
        user32.GetDlgCtrlID.restype = ctypes.c_int
        user32.SendMessageW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_size_t,
            ctypes.c_void_p,
        ]
        user32.SendMessageW.restype = ctypes.c_ssize_t
        parent = user32.GetParent(int(handle))
        control_id = user32.GetDlgCtrlID(int(handle))
        # WM_COMMAND with LBN_DBLCLK reproduces a native double-click without
        # DPI-sensitive mouse coordinates.
        wparam = (2 << 16) | (control_id & 0xFFFF)
        user32.SendMessageW(parent, 0x0111, wparam, int(handle))
    except Exception as error:
        raise PackerAutomationError(
            f"无法向 Delphi 目录列表发送双击通知：{error}"
        ) from error


def _directory_item_index(
    directory_list: Any,
    component: str,
    timeout: float = 3,
) -> tuple[int, list[str]]:
    deadline = time.monotonic() + timeout
    last_items: list[str] = []
    while time.monotonic() < deadline:
        try:
            last_items = directory_list.item_texts()
        except Exception as error:
            raise PackerAutomationError(f"无法读取目录列表：{error}") from error
        matches = [
            index
            for index, text in enumerate(last_items)
            if _matches_directory_component(text, component)
        ]
        if matches:
            return matches[-1], last_items
        time.sleep(0.2)
    raise PackerAutomationError(
        f"目录列表中没有找到 {component!r}；可见项：{last_items}"
    )


def _reset_directory_list_to_drive_root(
    directory_list: Any,
    drive: str,
) -> None:
    clean_drive = drive.rstrip("\\/")
    root_name = clean_drive + "\\"
    index, _ = _directory_item_index(directory_list, root_name)
    directory_list.select(index)
    _activate_directory_selection(directory_list)
    time.sleep(0.3)


def navigate_directory_list(window: Any, directory: Path) -> None:
    directory_list = _find_directory_list(window)
    _reset_directory_list_to_drive_root(directory_list, directory.drive)
    for component in directory.parts[1:]:
        index, _ = _directory_item_index(directory_list, component)
        directory_list.select(index)
        _activate_directory_selection(directory_list)
        time.sleep(0.3)
    try:
        selected = directory_list.selected_text()
    except Exception:
        selected = directory.name
    if selected and not _matches_directory_component(selected, directory.name):
        raise PackerAutomationError(
            f"目录选择后节点不一致：期望 {directory.name!r}，当前 {selected!r}"
        )


def _wait_for_source_files(window: Any, timeout: float = 5) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        counts: list[int] = []
        try:
            lists = window.descendants(class_name="TListBox")
        except Exception:
            lists = []
        for control in lists:
            try:
                counts.append(len(control.item_texts()))
            except Exception:
                continue
        if counts and max(counts) > 0:
            return max(counts)
        time.sleep(0.2)
    raise PackerAutomationError("进入 converted 后左侧文件列表仍为空")


def _find_tree(window: Any) -> Any:
    trees = window.descendants(class_name="SysTreeView32")
    if trees:
        return trees[0]
    try:
        tree = window.child_window(control_type="Tree")
        tree.wait("exists enabled", timeout=3)
        return tree.wrapper_object()
    except Exception as error:
        raise PackerAutomationError("没有找到文件夹树形目录") from error


def _matching_root(tree: Any, drive: str) -> Any:
    desired = _normalize_tree_name(drive)
    roots = tree.roots()
    for root in roots:
        if _normalize_tree_name(root.text()) == desired:
            return root
    available = [root.text() for root in roots]
    raise PackerAutomationError(
        f"树形目录没有找到磁盘根节点 {drive}；可见根节点：{available}"
    )


def navigate_tree_to_directory(tree: Any, directory: Path) -> Any:
    drive = directory.drive
    if not drive:
        raise PackerAutomationError(f"打包输入目录不是绝对 Windows 路径：{directory}")
    root_name = f"{drive}\\"
    current = _matching_root(tree, root_name)
    current.expand()
    parts = directory.parts[1:]
    for index, part in enumerate(parts):
        try:
            child = current.get_child(part, exact=True)
        except Exception as error:
            available = []
            try:
                available = [item.text() for item in current.children()]
            except Exception:
                pass
            raise PackerAutomationError(
                f"在 {current.text()} 下没有找到目录 {part!r}；"
                f"可见目录：{available}"
            ) from error
        child.ensure_visible()
        child.select()
        if index < len(parts) - 1:
            child.expand()
        current = child
        time.sleep(0.15)
    current.ensure_visible()
    current.select()
    return current


def _click_save(window: Any) -> None:
    buttons: list[Any] = []
    for class_name in ("TBitBtn", "Button"):
        try:
            buttons.extend(window.descendants(class_name=class_name))
        except Exception:
            pass
    for button in buttons:
        if "".join(button.window_text().split()) == "保存":
            # Delphi's save handler opens a modal Save As dialog. A synchronous
            # BM_CLICK blocks until that dialog closes, preventing automation
            # from filling it. Post the message asynchronously instead.
            button.post_message(0x00F5)
            return
    raise PackerAutomationError("没有找到“保存”按钮")


def _click_overwrite_confirmation(dialog: Any) -> bool:
    preferred = ("是", "yes", "覆盖", "确认", "确定", "ok")
    try:
        buttons = dialog.descendants(control_type="Button")
    except Exception:
        buttons = []
    for expected in preferred:
        for button in buttons:
            title = "".join(button.window_text().split()).casefold()
            if title.startswith(expected.casefold()) or expected.casefold() in title:
                button.click()
                return True
    return False


def _complete_save_as(
    window: Any,
    output: Path,
    previous_signature: tuple[int, int] | None,
    timeout: float,
    legacy_directory: Path | None = None,
) -> None:
    from pywinauto import Desktop
    from converter_automation import (
        _find_filename_edit,
        _find_new_dialog,
        _new_visible_windows,
        _send_keys,
        _set_windows_clipboard,
        _window_handles,
    )

    desktop = Desktop(backend="uia")
    win32_desktop = Desktop(backend="win32")
    previous_handles = _window_handles(window, desktop)
    previous_win32_handles = _window_handles(window, win32_desktop)
    legacy_output = (legacy_directory or output.parent) / "LIST.LST"
    previous_legacy_signature = _signature(legacy_output)
    _click_save(window)

    # Some Delphi builds save a fixed LIST.LST directly instead of opening Save
    # As. Preserve that native file and copy it to the requested OUTPUT.LST.
    immediate_deadline = time.monotonic() + 3
    while time.monotonic() < immediate_deadline:
        if _signature(output) not in {None, previous_signature}:
            return
        if _promote_updated_legacy_list(
            output,
            previous_legacy_signature,
            legacy_output=legacy_output,
        ):
            return
        time.sleep(0.1)

    dialog: Any | None = None
    detection_errors: list[str] = []
    for candidate_desktop, handles, timeout_seconds in (
        (desktop, previous_handles, 3),
        (win32_desktop, previous_win32_handles, 10),
    ):
        try:
            dialog = _find_new_dialog(
                window,
                candidate_desktop,
                handles,
                timeout=timeout_seconds,
            )
            break
        except Exception as error:
            detection_errors.append(str(error))
    if dialog is None:
        diagnostics = output.parent / "packer-save-as-controls.txt"
        lines = ["No new Save As window detected.", *detection_errors, "", "Visible windows:"]
        try:
            for candidate in win32_desktop.windows():
                lines.append(
                    f"handle={getattr(candidate, 'handle', '')} "
                    f"class={candidate.class_name()!r} "
                    f"title={candidate.window_text()!r}"
                )
        except Exception as error:
            lines.append(f"Unable to enumerate windows: {error}")
        diagnostics.write_text("\n".join(lines), encoding="utf-8")
        raise PackerAutomationError(
            "点击保存后既没有更新 LIST.LST/OUTPUT.LST，也没有识别到另存为窗口；"
            f"诊断信息：{diagnostics}"
        )

    filename = _find_filename_edit(dialog, allow_generic_edit=True)
    if filename is None:
        diagnostics = output.parent / "packer-save-as-controls.txt"
        try:
            dialog.print_control_identifiers(filename=str(diagnostics))
        except Exception:
            pass
        raise PackerAutomationError(
            "另存为窗口没有找到“文件名”输入框；"
            f"控件信息：{diagnostics}"
        )
    try:
        filename.set_edit_text(str(output))
        filename.set_focus()
    except Exception:
        filename.set_focus()
        _set_windows_clipboard(str(output))
        _send_keys("^a")
        _send_keys("^v")

    handles_before_submit = _window_handles(window, desktop)
    _send_keys("{ENTER}")
    deadline = time.monotonic() + timeout
    overwrite_confirmed = False
    while time.monotonic() < deadline:
        current = _signature(output)
        if current is not None and current != previous_signature:
            return
        if not overwrite_confirmed:
            for candidate in _new_visible_windows(
                window,
                desktop,
                handles_before_submit,
            ):
                if _click_overwrite_confirmation(candidate):
                    overwrite_confirmed = True
                    break
        time.sleep(0.2)
    raise PackerAutomationError(
        f"{timeout:g} 秒内未通过另存为生成或更新 {output}"
    )


def _signature(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
        return stat.st_mtime_ns, stat.st_size
    except OSError:
        return None


def _wait_for_package(
    output: Path,
    previous_signature: tuple[int, int] | None,
    timeout: float,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = _signature(output)
        if current is not None and current != previous_signature:
            return
        time.sleep(0.2)
    raise PackerAutomationError(
        f"{timeout:g} 秒内没有生成或更新 {output}"
    )


def _promote_updated_legacy_list(
    output: Path,
    previous_legacy_signature: tuple[int, int] | None,
    legacy_output: Path | None = None,
) -> bool:
    legacy_output = legacy_output or output.with_name("LIST.LST")
    if legacy_output == output:
        return False
    current = _signature(legacy_output)
    if current is None or current == previous_legacy_signature:
        return False
    shutil.copy2(legacy_output, output)
    return _signature(output) is not None


def stage_converted_files(
    source_directory: Path,
    packer_directory: Path,
    clean_existing: bool = True,
) -> list[Path]:
    source_files = sorted(
        (
            path
            for path in source_directory.iterdir()
            if path.is_file() and path.suffix.lower() in PACKED_AUDIO_EXTENSIONS
        ),
        key=lambda path: path.name.casefold(),
    )
    if not source_files:
        raise PackerAutomationError(
            f"{source_directory} 中没有可复制的杰理转换文件"
        )
    packer_directory.mkdir(parents=True, exist_ok=True)
    if source_directory.resolve() == packer_directory.resolve():
        return source_files
    if clean_existing:
        for existing in packer_directory.iterdir():
            if (
                existing.is_file()
                and existing.suffix.lower() in PACKED_AUDIO_EXTENSIONS
            ):
                existing.unlink()
    staged: list[Path] = []
    for source in source_files:
        destination = packer_directory / source.name
        if source.resolve() != destination.resolve():
            shutil.copy2(source, destination)
        staged.append(destination)
    return staged


def resolve_packres_input_directory(
    executable: Path,
    configured: str,
) -> Path:
    path = Path(configured).expanduser()
    if path.is_absolute():
        return path.resolve()
    # Default layout:
    # 音频转换工具/AD140打包工具/packres/pRFiles.exe
    # 音频转换工具/test_dir
    try:
        suite_root = executable.parent.parents[1]
    except IndexError:
        suite_root = executable.parent
    return (suite_root / path).resolve()


def run_packres_batch(
    packer_directory: Path,
    config: Any,
) -> Path:
    batch = packer_directory / config.packres_batch_name
    if not batch.is_file():
        raise PackerAutomationError(f"找不到资源打包脚本：{batch}")
    output = packer_directory / config.packres_output_name
    previous_signature = _signature(output)
    comspec = os.environ.get("COMSPEC", "cmd.exe")
    command = [comspec, "/d", "/c", "call", str(batch)]
    try:
        process = subprocess.run(
            command,
            cwd=str(packer_directory),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=config.packres_timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        raise PackerAutomationError(
            f"{config.packres_batch_name} 执行超过 "
            f"{config.packres_timeout_seconds} 秒"
        ) from error
    if process.returncode:
        detail = process.stdout.strip()
        raise PackerAutomationError(
            f"{config.packres_batch_name} 退出代码 {process.returncode}"
            + (f"：{detail}" if detail else "")
        )
    current_signature = _signature(output)
    if current_signature is None or current_signature == previous_signature:
        detail = process.stdout.strip()
        raise PackerAutomationError(
            f"批处理结束但 {output} 没有生成或更新"
            + (f"：{detail}" if detail else "")
        )
    return output


def automate_packer(
    executable: Path,
    source_directory: Path,
    config: Any,
) -> Path:
    from pywinauto import Application

    staging_directory = resolve_packres_input_directory(
        executable,
        config.packres_input_directory,
    )
    staging_directory.mkdir(parents=True, exist_ok=True)
    output = staging_directory / config.packer_output_name
    previous_signature = _signature(output)
    application = Application(backend="win32").start(
        f'"{executable}"',
        work_dir=str(executable.parent),
    )
    window = application.window(title_re=config.packer_window_title_regex)
    try:
        window.wait(
            "visible enabled ready",
            timeout=config.startup_timeout_seconds,
        )
        print(f"[合成] 选择磁盘 {source_directory.drive}……", flush=True)
        _select_drive(window, source_directory.drive)
        print(f"[合成] 逐层进入 {source_directory}……", flush=True)
        try:
            directory_lists = window.descendants(class_name="TDirectoryListBox")
        except Exception:
            directory_lists = []
        if directory_lists:
            navigate_directory_list(window, source_directory)
        else:
            tree = _find_tree(window)
            navigate_tree_to_directory(tree, source_directory)
        loaded_count = _wait_for_source_files(window)
        print(f"[合成] 已加载 {loaded_count} 条源文件记录。", flush=True)
        print("[合成] 点击保存……", flush=True)
        print(f"[合成] 在另存为窗口填写 {config.packer_output_name}……", flush=True)
        _complete_save_as(
            window,
            output,
            previous_signature,
            config.packer_timeout_seconds,
            legacy_directory=executable.parent,
        )
        print(f"[合成] 已生成并校验：{output}", flush=True)
        staged = stage_converted_files(source_directory, staging_directory)
        print(
            f"[合成] 已复制 {len(staged)} 个转换文件到 {staging_directory}。",
            flush=True,
        )
        print(f"[合成] 执行 {config.packres_batch_name}……", flush=True)
        final_output = run_packres_batch(staging_directory, config)
        print(f"[合成] 输出成功：{final_output}", flush=True)
        return final_output
    except Exception as error:
        diagnostics = executable.parent / "packer-controls.txt"
        try:
            window.print_control_identifiers(filename=str(diagnostics))
        except Exception:
            pass
        if isinstance(error, PackerAutomationError):
            raise
        raise PackerAutomationError(
            f"打包工具自动操作失败：{error}；控件信息：{diagnostics}"
        ) from error


def run_configured_packer(
    source_directory: Path,
    config: Any,
    config_path: Path,
) -> Path | None:
    if not config.packer_enabled:
        return None
    if os.name != "nt":
        print("[合成] 当前不是 Windows，已跳过 AD140 打包工具。", flush=True)
        return None
    executable = resolve_packer_executable(config, config_path)
    configured_input = Path(config.packres_input_directory).expanduser()
    if not configured_input.is_absolute():
        config.packres_input_directory = str(
            (config_path.parent / configured_input).resolve()
        )
    return automate_packer(executable, source_directory.resolve(), config)
