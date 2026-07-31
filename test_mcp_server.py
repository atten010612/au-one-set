import tempfile
import unittest
from pathlib import Path
from unittest import mock

import mcp_server


class MCPServerTests(unittest.TestCase):
    def test_windows_worker_combines_hidden_and_process_group_flags(self) -> None:
        with (
            mock.patch.object(mcp_server.os, "name", "nt"),
            mock.patch.object(
                mcp_server.subprocess,
                "CREATE_NO_WINDOW",
                0x08000000,
                create=True,
            ),
            mock.patch.object(
                mcp_server.subprocess,
                "CREATE_NEW_PROCESS_GROUP",
                0x00000200,
                create=True,
            ),
        ):
            self.assertEqual(
                mcp_server.no_window_creation_flags(new_process_group=True),
                0x08000200,
            )

    def test_progress_parser_tracks_processing_and_conversion(self) -> None:
        manager = mcp_server.WorkflowManager(Path.cwd(), start_dispatcher=False)
        job = mcp_server.WorkflowJob(
            job_id="job",
            input_paths=[],
            workflow_step=0,
            status="running",
        )
        manager._consume_line(job, "找到 4 个音频文件，使用 1 个并发任务。")
        manager._consume_line(job, "[完成] a.wav：处理完成")
        self.assertEqual((job.current, job.total), (1, 4))
        self.assertEqual(job.phase, "processing")
        self.assertAlmostEqual(job.percent, 13.75)

        manager._consume_line(job, "[转换] 已发现 2/4 个结果，继续等待……")
        self.assertEqual(job.phase, "conversion")
        self.assertAlmostEqual(job.percent, 67.5)

        manager._consume_line(job, "[合成] 输出成功：dir_music")
        self.assertEqual(job.phase, "synthesis")
        self.assertEqual(job.percent, 90.0)
        manager._consume_line(job, "[授权] 已授权固件：authorized.fw")
        self.assertEqual(job.phase, "authorization")
        self.assertEqual(job.percent, 100.0)

    def test_mode_specific_progress_ranges(self) -> None:
        manager = mcp_server.WorkflowManager(Path.cwd(), start_dispatcher=False)
        conversion_only = mcp_server.WorkflowJob(
            job_id="conversion",
            input_paths=[],
            workflow_step=3,
        )
        manager._set_stage_progress(conversion_only, "conversion", 0.5)
        self.assertEqual(conversion_only.percent, 50.0)

        synthesis_only = mcp_server.WorkflowJob(
            job_id="synthesis",
            input_paths=[],
            workflow_step=4,
        )
        manager._set_stage_progress(synthesis_only, "synthesis", 0.8)
        self.assertEqual(synthesis_only.percent, 40.0)

    def test_queued_job_can_be_cancelled(self) -> None:
        manager = mcp_server.WorkflowManager(Path.cwd(), start_dispatcher=False)
        job = mcp_server.WorkflowJob(
            job_id="cancel-me",
            input_paths=[],
            workflow_step=0,
        )
        manager.jobs[job.job_id] = job
        result = manager.cancel(job.job_id)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["phase"], "cancelled")

    def test_relative_input_paths_resolve_from_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "audio"
            source.mkdir()
            manager = mcp_server.WorkflowManager(root, start_dispatcher=False)
            result = manager.start(["audio"], workflow_step=1)
            self.assertEqual(result["input_paths"], [str(source.resolve())])
            manager.cancel(result["job_id"])

    def test_environment_check_reports_all_portable_tools(self) -> None:
        result = mcp_server.check_environment()
        self.assertIn("ffmpeg", result["checks"])
        self.assertIn("converter_path", result["checks"])
        self.assertIn("packer_path", result["checks"])
        self.assertIn("packres.exe", result["checks"])
        self.assertIn("new_packres.bat", result["checks"])
        self.assertIn("AU_TASK_SKILL_HOME", result["checks"])

    def test_cursor_slash_commands_map_to_all_workflow_steps(self) -> None:
        commands = Path(__file__).resolve().parent / ".cursor" / "commands"
        for step in range(5):
            command = commands / f"音频处理{step}.md"
            self.assertTrue(command.is_file(), command)
            content = command.read_text(encoding="utf-8")
            self.assertIn(f'"workflow_step": {step}', content)
            self.assertIn("start_audio_workflow", content)
            self.assertIn("get_audio_workflow_status", content)


if __name__ == "__main__":
    unittest.main()
