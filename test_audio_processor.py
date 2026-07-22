import argparse
import json
import tempfile
import unittest
from pathlib import Path

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

    def test_preprocessing_filter_preserves_middle_silence_strategy(self) -> None:
        args = argparse.Namespace(
            noise_reduction=12.0,
            noise_floor=-50.0,
            speech_confirmation=0.02,
            silence_threshold=-45.0,
            keep_silence=0.15,
        )
        value = audio_processor.preprocessing_filter(args, {"denoise", "trim"})
        self.assertIsNotNone(value)
        self.assertIn("afftdn=", value)
        self.assertEqual(value.count("silenceremove="), 2)
        self.assertEqual(value.count("areverse"), 2)
        self.assertNotIn("stop_periods", value)

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


if __name__ == "__main__":
    unittest.main()
