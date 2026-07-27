import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / "runtime"
sys.path.insert(0, str(RUNTIME))

import au_task  # noqa: E402
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


if __name__ == "__main__":
    unittest.main()
