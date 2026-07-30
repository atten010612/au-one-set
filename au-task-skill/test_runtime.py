import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / "runtime"
sys.path.insert(0, str(RUNTIME))

import au_task  # noqa: E402
import install_cursor  # noqa: E402
import mcp_server  # noqa: E402


class RuntimeTests(unittest.TestCase):
    def test_filename_whitespace_and_collision_preparation(self) -> None:
        self.assertEqual(
            au_task.sanitized_name("03 [连接]\tAPP 已连接.wav"),
            "03[连接]APP已连接.wav",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_a = root / "a b.wav"
            source_b = root / "ab.wav"
            output = root / "prepared"
            output.mkdir()
            source_a.write_bytes(b"a")
            source_b.write_bytes(b"b")
            prepared = au_task.prepare_sanitized_copies(
                [source_a, source_b],
                output,
            )
            self.assertEqual(
                [path.name for path in prepared],
                ["ab.wav", "ab_1.wav"],
            )

    def test_standalone_workflow_mode_mapping(self) -> None:
        self.assertEqual(mcp_server.WORKFLOW_TO_MODE, {2: 0, 3: 1, 4: 2})
        manager = mcp_server.JobManager(start_dispatcher=False)
        job = mcp_server.Job("job", [], workflow_step=2, status="running")
        manager._consume(job, "[转换] 已发现 2/4 个结果，继续等待……")
        self.assertEqual(job.phase, "conversion")
        self.assertEqual(job.percent, 37.5)
        manager._consume(job, "[合成] 输出成功：dir_music")
        self.assertEqual(job.phase, "packaging")
        self.assertEqual(job.percent, 100.0)

    def test_standalone_environment_contains_all_vendor_tools(self) -> None:
        result = mcp_server.check_environment()
        self.assertIn("converter", result["checks"])
        self.assertIn("pRFiles", result["checks"])
        self.assertIn("packres.exe", result["checks"])
        self.assertIn("new_packres.bat", result["checks"])

    def test_installer_preserves_other_global_mcp_servers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "skill"
            cursor_home = Path(directory) / ".cursor"
            (root / ".venv" / "Scripts").mkdir(parents=True)
            (root / ".venv" / "Scripts" / "python.exe").touch()
            (root / "runtime").mkdir()
            (root / "runtime" / "mcp_server.py").touch()
            for name in install_cursor.SKILL_NAMES:
                skill = root / ".cursor" / "skills" / name
                skill.mkdir(parents=True)
                (skill / "SKILL.md").write_text(name, encoding="utf-8")
            cursor_home.mkdir()
            mcp_config = cursor_home / "mcp.json"
            mcp_config.write_text(
                '{"mcpServers":{"other":{"command":"other.exe"}}}',
                encoding="utf-8",
            )
            with (
                mock.patch.object(install_cursor, "ROOT", root),
                mock.patch.object(install_cursor, "CURSOR_HOME", cursor_home),
                mock.patch.object(install_cursor, "GLOBAL_MCP", mcp_config),
                mock.patch.object(
                    install_cursor,
                    "GLOBAL_SKILLS",
                    cursor_home / "skills",
                ),
            ):
                install_cursor.install()
                installed = install_cursor.read_mcp_config()
                self.assertIn("other", installed["mcpServers"])
                self.assertIn(
                    "au-task-workflow",
                    installed["mcpServers"],
                )
                install_cursor.uninstall()
                removed = install_cursor.read_mcp_config()
                self.assertIn("other", removed["mcpServers"])
                self.assertNotIn(
                    "au-task-workflow",
                    removed["mcpServers"],
                )


if __name__ == "__main__":
    unittest.main()
