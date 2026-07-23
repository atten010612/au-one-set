import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import audio_processor


class AudioProcessorTests(unittest.TestCase):
    def test_plan_step_parsing(self) -> None:
        self.assertEqual(
            audio_processor.normalized_plan_steps("denoise|trim"),
            {"denoise", "trim"},
        )
        self.assertEqual(
            audio_processor.normalized_plan_steps("all"),
            audio_processor.ALL_STEPS,
        )
        self.assertEqual(audio_processor.normalized_plan_steps("none"), set())
        with self.assertRaises(ValueError):
            audio_processor.normalized_plan_steps("compress")

    def test_plan_supports_utf8_bom_and_filename_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "提示音.wav"
            source.touch()
            plan_file = root / "plan.csv"
            plan_file.write_text(
                "\ufefffile,completed_steps\n提示音.wav,denoise|trim\n",
                encoding="utf-8",
            )
            plan = audio_processor.load_plan(str(plan_file))
            self.assertEqual(
                audio_processor.steps_for_file(source, plan),
                {"denoise", "trim"},
            )

    def test_collect_files_ignores_processed_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = root / "voice.wav"
            expected.touch()
            (root / "notes.txt").touch()
            processed = root / "processed"
            processed.mkdir()
            (processed / "voice.wav").touch()
            self.assertEqual(
                audio_processor.collect_files([str(root)], True, None),
                [expected],
            )

    def test_denoise_filter_uses_configured_reduction(self) -> None:
        args = argparse.Namespace(
            noise_reduction=12.0,
            noise_floor=-50.0,
        )
        value = audio_processor.denoise_filter(args)
        self.assertIn("afftdn=", value)
        self.assertIn("nr=12", value)

    def test_short_head_silence_is_never_padded(self) -> None:
        log = (
            "[silencedetect] silence_start: 0\n"
            "[silencedetect] silence_end: 0.05 | silence_duration: 0.05\n"
        )
        self.assertEqual(
            audio_processor.edge_trim_bounds(log, 1.05, 0.15),
            (0.0, 1.05),
        )

    def test_only_excess_edge_silence_is_trimmed(self) -> None:
        log = (
            "[silencedetect] silence_start: 0\n"
            "[silencedetect] silence_end: 0.3 | silence_duration: 0.3\n"
            "[silencedetect] silence_start: 0.8\n"
            "[silencedetect] silence_end: 0.9 | silence_duration: 0.1\n"
            "[silencedetect] silence_start: 1.7\n"
            "[silencedetect] silence_end: 2 | silence_duration: 0.3\n"
        )
        start, end = audio_processor.edge_trim_bounds(log, 2.0, 0.15)
        self.assertAlmostEqual(start, 0.15)
        self.assertAlmostEqual(end, 1.85)

    def test_settings_signature_changes_with_completed_steps(self) -> None:
        args = audio_processor.parse_args([])
        untreated = audio_processor.settings_signature(args, set())
        denoised = audio_processor.settings_signature(args, {"denoise"})
        self.assertNotEqual(untreated, denoised)

    def test_overwrite_never_selects_source_as_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "voice.wav"
            source.touch()
            audio_processor.RESERVED_OUTPUTS.clear()
            output = audio_processor.choose_output(source, source.parent, overwrite=True)
            self.assertNotEqual(output, source)
            self.assertEqual(output.name, "voice_1.wav")

    def test_reports_merge_separate_runs_and_include_failures(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            args = audio_processor.parse_args([])
            first = audio_processor.Result(
                source="/audio/a.wav",
                source_sha256="aaa",
                output=str(output / "a.wav"),
                status="processed",
                message="ok",
                settings_signature="settings",
                completed_steps_before=[],
                applied_steps=["trim"],
            )
            failed = audio_processor.Result(
                source="/audio/b.wav",
                source_sha256="",
                output=None,
                status="failed",
                message="bad input",
                settings_signature="settings",
                completed_steps_before=[],
                applied_steps=[],
            )
            audio_processor.write_reports(
                [first], [output], {first.source: output}, args
            )
            audio_processor.write_reports(
                [failed], [output], {failed.source: output}, args
            )
            report = json.loads(
                (output / audio_processor.REPORT_NAME).read_text(encoding="utf-8")
            )
            self.assertEqual(len(report["results"]), 2)
            self.assertEqual(
                {item["status"] for item in report["results"]},
                {"processed", "failed"},
            )

    def test_winget_runs_through_cmd_to_avoid_app_alias_error(self) -> None:
        completed = mock.Mock(returncode=0)
        with (
            mock.patch.object(audio_processor.os, "name", "nt"),
            mock.patch.object(audio_processor.shutil, "which", return_value="winget.exe"),
            mock.patch.object(audio_processor.subprocess, "run", return_value=completed) as run,
        ):
            self.assertTrue(audio_processor.install_ffmpeg_with_winget())
        command = run.call_args.args[0]
        self.assertEqual(command[:4], ["cmd.exe", "/d", "/c", "winget"])
        self.assertIn("Gyan.FFmpeg", command)

    def test_winget_access_error_is_reported_without_traceback(self) -> None:
        with (
            mock.patch.object(audio_processor.os, "name", "nt"),
            mock.patch.object(audio_processor.shutil, "which", return_value="winget.exe"),
            mock.patch.object(
                audio_processor.subprocess,
                "run",
                side_effect=OSError(1920, "系统无法访问此文件"),
            ),
        ):
            self.assertFalse(audio_processor.install_ffmpeg_with_winget())


if __name__ == "__main__":
    unittest.main()
