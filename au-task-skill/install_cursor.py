"""Install or remove the standalone AU Task MCP and global Cursor Skills."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CURSOR_HOME = Path.home() / ".cursor"
GLOBAL_MCP = CURSOR_HOME / "mcp.json"
GLOBAL_SKILLS = CURSOR_HOME / "skills"
SERVER_NAME = "au-task-workflow"
SKILL_NAMES = ("au-task0", "au-task1", "au-task2")


def read_mcp_config() -> dict:
    if not GLOBAL_MCP.is_file():
        return {"mcpServers": {}}
    data = json.loads(GLOBAL_MCP.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise RuntimeError(f"{GLOBAL_MCP} must contain a JSON object")
    servers = data.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise RuntimeError(f"{GLOBAL_MCP}: mcpServers must be an object")
    return data


def write_mcp_config(data: dict) -> None:
    CURSOR_HOME.mkdir(parents=True, exist_ok=True)
    if GLOBAL_MCP.is_file():
        shutil.copy2(GLOBAL_MCP, GLOBAL_MCP.with_suffix(".json.backup"))
    temporary = GLOBAL_MCP.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(GLOBAL_MCP)


def install() -> None:
    python = ROOT / ".venv" / "Scripts" / "python.exe"
    server = ROOT / "runtime" / "mcp_server.py"
    if not python.is_file():
        raise RuntimeError(f"Missing virtual environment Python: {python}")
    if not server.is_file():
        raise RuntimeError(f"Missing MCP server: {server}")

    GLOBAL_SKILLS.mkdir(parents=True, exist_ok=True)
    for name in SKILL_NAMES:
        source = ROOT / ".cursor" / "skills" / name
        destination = GLOBAL_SKILLS / name
        shutil.copytree(source, destination, dirs_exist_ok=True)

    config = read_mcp_config()
    config["mcpServers"][SERVER_NAME] = {
        "type": "stdio",
        "command": str(python),
        "args": [str(server)],
        "env": {
            "PYTHONUTF8": "1",
            "PYTHONUNBUFFERED": "1",
        },
    }
    write_mcp_config(config)
    print(f"Installed global MCP: {SERVER_NAME}")
    print(f"Installed skills: {', '.join(SKILL_NAMES)}")
    print(f"Skill root: {ROOT}")


def uninstall() -> None:
    for name in SKILL_NAMES:
        shutil.rmtree(GLOBAL_SKILLS / name, ignore_errors=True)
    config = read_mcp_config()
    config["mcpServers"].pop(SERVER_NAME, None)
    write_mcp_config(config)
    print(f"Removed global MCP: {SERVER_NAME}")
    print(f"Removed skills: {', '.join(SKILL_NAMES)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("install", "uninstall"))
    args = parser.parse_args()
    if args.action == "install":
        install()
    else:
        uninstall()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
