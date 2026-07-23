"""Automation for the AD140 pRFiles resource packing utility."""

from __future__ import annotations

import json
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
    combos = window.descendants(class_name="ComboBox")
    for combo in combos:
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
    try:
        button = window.child_window(title="保存", class_name="Button")
        button.wait("exists enabled visible", timeout=3)
        button.click()
        return
    except Exception:
        pass
    buttons = window.descendants(class_name="Button")
    for button in buttons:
        if "".join(button.window_text().split()) == "保存":
            button.click()
            return
    raise PackerAutomationError("没有找到“保存”按钮")


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
        print(f"[合成] 选择磁盘 {source_directory.drive}……", flush=True)
        _select_drive(window, source_directory.drive)
        print(f"[合成] 逐层进入 {source_directory}……", flush=True)
        tree = _find_tree(window)
        navigate_tree_to_directory(tree, source_directory)
        time.sleep(0.5)
        print("[合成] 点击保存……", flush=True)
        _click_save(window)
        print(f"[合成] 等待 {config.packer_output_name}……", flush=True)
        _wait_for_package(
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
