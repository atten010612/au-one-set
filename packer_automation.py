"""Automation for the AD140 pRFiles resource packing utility."""

from __future__ import annotations

import json
import ntpath
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any


class PackerAutomationError(RuntimeError):
    """Expected packer setup or UI automation failure."""


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


def _same_path(first: str | Path, second: str | Path) -> bool:
    return ntpath.normcase(ntpath.normpath(str(first))) == ntpath.normcase(
        ntpath.normpath(str(second))
    )


def _current_directory(window: Any) -> str | None:
    candidates: list[str] = []
    for class_name in ("TPanel", "Static"):
        try:
            controls = window.descendants(class_name=class_name)
        except Exception:
            continue
        for control in controls:
            try:
                text = control.window_text().strip()
            except Exception:
                continue
            if len(text) >= 3 and text[1:3] == ":\\":
                candidates.append(text)
    if not candidates:
        return None
    return max(candidates, key=lambda value: (value.count("\\"), len(value)))


def _find_directory_list(window: Any) -> Any:
    lists = window.descendants(class_name="TDirectoryListBox")
    if not lists:
        raise PackerAutomationError("没有找到 Delphi 目录列表 TDirectoryListBox")
    return lists[0]


def _matches_directory_component(item_text: str, component: str) -> bool:
    cleaned = item_text.strip().strip("[]").rstrip("\\/")
    basename = ntpath.basename(cleaned) or cleaned
    return basename.casefold() == component.casefold()


def navigate_directory_list(window: Any, directory: Path) -> None:
    current = _current_directory(window)
    if current and _same_path(current, directory):
        return
    directory_list = _find_directory_list(window)
    for component in directory.parts[1:]:
        try:
            items = directory_list.item_texts()
        except Exception as error:
            raise PackerAutomationError(f"无法读取目录列表：{error}") from error
        matches = [
            index
            for index, text in enumerate(items)
            if _matches_directory_component(text, component)
        ]
        if not matches:
            raise PackerAutomationError(
                f"目录列表中没有找到 {component!r}；可见项：{items}"
            )
        directory_list.select(matches[-1])
        time.sleep(0.2)
        if _current_directory(window) and _same_path(
            _current_directory(window) or "", directory
        ):
            return
    current = _current_directory(window)
    if not current or not _same_path(current, directory):
        raise PackerAutomationError(
            f"目录选择后路径不一致：期望 {directory}，当前 {current or '(无法读取)'}"
        )


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
    previous_handles = _window_handles(window, desktop)
    _click_save(window)

    # Some builds save immediately; most open the standard Save As dialog.
    immediate_deadline = time.monotonic() + 1
    while time.monotonic() < immediate_deadline:
        if _signature(output) not in {None, previous_signature}:
            return
        time.sleep(0.1)

    dialog = _find_new_dialog(window, desktop, previous_handles, timeout=10)
    filename = _find_filename_edit(dialog)
    if filename is None:
        raise PackerAutomationError("另存为窗口没有找到“文件名”输入框")
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


def automate_packer(
    executable: Path,
    source_directory: Path,
    config: Any,
) -> Path:
    from pywinauto import Application

    output = executable.parent / config.packer_output_name
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
        current = _current_directory(window)
        if current and _same_path(current, source_directory):
            print(f"[合成] 当前目录已经是 {source_directory}。", flush=True)
        else:
            print(f"[合成] 选择磁盘 {source_directory.drive}……", flush=True)
            _select_drive(window, source_directory.drive)
            print(f"[合成] 逐层进入 {source_directory}……", flush=True)
            try:
                navigate_directory_list(window, source_directory)
            except PackerAutomationError:
                # Retain support for variants that use a standard TreeView.
                tree = _find_tree(window)
                navigate_tree_to_directory(tree, source_directory)
        time.sleep(0.5)
        print("[合成] 点击保存……", flush=True)
        print(f"[合成] 在另存为窗口填写 {config.packer_output_name}……", flush=True)
        _complete_save_as(
            window,
            output,
            previous_signature,
            config.packer_timeout_seconds,
        )
        print(f"[合成] 已生成并校验：{output}", flush=True)
        return output
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
    return automate_packer(executable, source_directory.resolve(), config)
