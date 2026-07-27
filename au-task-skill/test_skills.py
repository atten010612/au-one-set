import unittest
from pathlib import Path


class SkillTests(unittest.TestCase):
    def test_skill_commands_map_to_expected_mcp_modes(self) -> None:
        root = Path(__file__).resolve().parent / ".cursor" / "skills"
        expected = {
            "au-task0": 2,
            "au-task1": 3,
            "au-task2": 4,
        }
        for name, workflow_step in expected.items():
            skill = root / name / "SKILL.md"
            self.assertTrue(skill.is_file(), skill)
            content = skill.read_text(encoding="utf-8")
            self.assertIn(f"name: {name}", content)
            self.assertIn("disable-model-invocation: true", content)
            self.assertIn(f'"workflow_step": {workflow_step}', content)
            self.assertIn("start_audio_workflow", content)
            self.assertIn("get_audio_workflow_status", content)

    def test_global_installer_registers_standalone_mcp(self) -> None:
        root = Path(__file__).resolve().parent
        installer = (root / "install_global_skills.bat").read_text(
            encoding="utf-8"
        )
        self.assertIn("install_cursor.py", installer)
        installer_module = (root / "install_cursor.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('SERVER_NAME = "au-task-workflow"', installer_module)
        self.assertIn('"mcpServers"', installer_module)
        self.assertTrue((root / "runtime" / "mcp_server.py").is_file())
        self.assertTrue((root / "runtime" / "au_task.py").is_file())
        self.assertTrue(
            (root / "vendor" / "converter" / "README.txt").is_file()
        )
        self.assertTrue(
            (root / "vendor" / "ad140" / "packres" / "README.txt").is_file()
        )
        self.assertTrue(
            (root / "vendor" / "ad140" / "test_dir" / "README.txt").is_file()
        )


if __name__ == "__main__":
    unittest.main()
