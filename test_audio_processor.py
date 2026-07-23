import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import audio_processor
import converter_automation


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
            converted = root / "converted"
            converted.mkdir()
            (converted / "voice.mp3").touch()
            self.assertEqual(
                audio_processor.collect_files([str(root)], True, None),
                [expected],
            )

    def test_double_click_mode_scans_child_audio_folders(self) -> None:
        self.assertTrue(audio_processor.should_scan_recursively([], False))
        self.assertFalse(
            audio_processor.should_scan_recursively(["voice-folder"], False)
        )
        self.assertTrue(
            audio_processor.should_scan_recursively(["voice-folder"], True)
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
            audio_processor.edge_trim_bounds(log, 1.05, 0.15, 0.0),
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
        start, end = audio_processor.edge_trim_bounds(log, 2.0, 0.15, 0.0)
        self.assertAlmostEqual(start, 0.15)
        self.assertAlmostEqual(end, 1.7)

    def test_detected_tail_silence_is_removed_by_default(self) -> None:
        args = audio_processor.parse_args([])
        self.assertEqual(args.keep_head_silence, 0.15)
        self.assertEqual(args.keep_tail_silence, 0.0)
        log = (
            "[silencedetect] silence_start: 1\n"
            "[silencedetect] silence_end: 1.05 | silence_duration: 0.05\n"
        )
        start, end = audio_processor.edge_trim_bounds(
            log,
            1.05,
            args.keep_head_silence,
            args.keep_tail_silence,
        )
        self.assertEqual(start, 0.0)
        self.assertAlmostEqual(end, 1.0)

    def test_denoiser_head_latency_is_removed(self) -> None:
        processed_log = (
            "[silencedetect] silence_start: 0\n"
            "[silencedetect] silence_end: 0.075 | silence_duration: 0.075\n"
        )
        start, end = audio_processor.edge_trim_bounds(
            processed_log,
            1.075,
            keep_head_silence=0.15,
            keep_tail_silence=0.0,
            original_leading_silence=0.05,
        )
        self.assertAlmostEqual(start, 0.025)
        self.assertAlmostEqual(end, 1.075)

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

    def test_converter_config_and_output_directory_rules(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "enabled": True,
                        "converter_path": r"D:\tools\converter.exe",
                        "format": "f1a",
                        "sample_rate": "32k",
                        "bit_rate": "32k",
                        "output_folder_name": "converted",
                    }
                ),
                encoding="utf-8",
            )
            config = converter_automation.load_converter_config(config_path)
            self.assertEqual(config.format, "F1A")
            self.assertEqual(config.sample_rate, "32K")
            self.assertEqual(config.bit_rate, "32K")

            dragged_folder = root / "dragged"
            dragged_folder.mkdir()
            folder_output = converter_automation.conversion_output_directory(
                [str(dragged_folder)], root / "script", "converted"
            )
            self.assertEqual(folder_output, dragged_folder / "converted")

            source_file = root / "voice.wav"
            source_file.touch()
            script_directory = root / "script"
            script_directory.mkdir()
            file_output = converter_automation.conversion_output_directory(
                [str(source_file)], script_directory, "converted"
            )
            self.assertEqual(file_output, script_directory / "converted")

    def test_converter_file_dialog_text_supports_unicode_paths(self) -> None:
        paths = [Path(r"D:\提示音\开始.wav"), Path(r"D:\提示音\结束.wav")]
        value = converter_automation.file_dialog_text(paths)
        self.assertIn('"', value)
        self.assertIn("开始.wav", value)
        self.assertIn("结束.wav", value)

    def test_converter_selects_duplicate_32k_by_column(self) -> None:
        class Rectangle:
            def __init__(self, left: int) -> None:
                self.left = left

        class Control:
            def __init__(self, title: str, left: int) -> None:
                self.title = title
                self.left = left
                self.clicked = False

            def is_visible(self) -> bool:
                return True

            def is_enabled(self) -> bool:
                return True

            def rectangle(self) -> Rectangle:
                return Rectangle(self.left)

            def window_text(self) -> str:
                return self.title

            def click_input(self) -> None:
                self.clicked = True

        class Window:
            def __init__(self, controls: list[Control]) -> None:
                self.controls = controls

            def descendants(self, control_type: str) -> list[Control]:
                self.asserted_type = control_type
                return self.controls

        sample_32k = Control("32K", 120)
        bitrate_32k = Control("32K", 220)
        window = Window(
            [
                Control("F1A", 20),
                Control("16K", 120),
                sample_32k,
                Control("24K", 220),
                bitrate_32k,
            ]
        )
        converter_automation._select_radio(window, "32K", column=1)
        self.assertTrue(sample_32k.clicked)
        self.assertFalse(bitrate_32k.clicked)
        converter_automation._select_radio(window, "32K", column=2)
        self.assertTrue(bitrate_32k.clicked)

    def test_successful_audio_outputs_are_forwarded_to_converter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.wav"
            output = root / "processed.wav"
            config = root / "converter.json"
            source.touch()
            output.touch()
            config.write_text("{}", encoding="utf-8")
            args = audio_processor.parse_args(
                [str(source), "--converter-config", str(config)]
            )
            result = audio_processor.Result(
                source=str(source),
                source_sha256="hash",
                output=str(output),
                status="processed",
                message="ok",
                settings_signature="settings",
                completed_steps_before=[],
                applied_steps=["denoise", "trim", "normalize"],
            )
            with mock.patch.object(
                converter_automation,
                "run_configured_converter",
                return_value=root / "converted",
            ) as run_converter:
                self.assertTrue(
                    audio_processor.run_converter_after_processing(args, [result])
                )
            forwarded_files = run_converter.call_args.args[0]
            self.assertEqual(forwarded_files, [output.resolve()])

    def test_pywinauto_install_refreshes_pywin32_paths_in_current_process(self) -> None:
        installed_module = object()
        with (
            mock.patch.object(
                converter_automation.importlib,
                "import_module",
                side_effect=[ImportError("win32api"), installed_module, installed_module],
            ) as import_module,
            mock.patch.object(
                converter_automation.subprocess,
                "run",
                return_value=mock.Mock(returncode=0),
            ),
            mock.patch.object(converter_automation.site, "getsitepackages", return_value=[]),
            mock.patch.object(
                converter_automation.site,
                "getusersitepackages",
                return_value="Z:/missing-site-packages",
            ),
        ):
            converter_automation.ensure_pywinauto(auto_install=True)
        self.assertEqual(import_module.call_count, 3)

    def test_pywinauto_import_failure_requests_one_time_restart(self) -> None:
        with (
            mock.patch.object(
                converter_automation.importlib,
                "import_module",
                side_effect=ImportError("win32api"),
            ),
            mock.patch.object(
                converter_automation.subprocess,
                "run",
                return_value=mock.Mock(returncode=0),
            ),
            mock.patch.object(converter_automation.site, "getsitepackages", return_value=[]),
            mock.patch.object(
                converter_automation.site,
                "getusersitepackages",
                return_value="Z:/missing-site-packages",
            ),
        ):
            with self.assertRaisesRegex(
                converter_automation.ConverterAutomationError,
                "重新运行",
            ):
                converter_automation.ensure_pywinauto(auto_install=True)

    def test_file_dialog_detection_uses_new_handle_not_window_title(self) -> None:
        class Window:
            def __init__(self, handle: int, visible: bool = True) -> None:
                self.handle = handle
                self.visible = visible

            def is_visible(self) -> bool:
                return self.visible

            def descendants(self, control_type: str) -> list["Window"]:
                return []

        class Desktop:
            def __init__(self, windows: list[Window]) -> None:
                self._windows = windows

            def windows(self) -> list[Window]:
                return self._windows

        main = Window(100)
        converter_titled_dialog = Window(200)
        desktop = Desktop([main, converter_titled_dialog])
        found = converter_automation._find_new_dialog(
            main,
            desktop,
            previous_handles={100},
            timeout=0.1,
        )
        self.assertIs(found, converter_titled_dialog)

    def test_filename_field_uses_common_dialog_id_not_search_box(self) -> None:
        filename = mock.Mock()

        class Dialog:
            def child_window(self, **criteria: object) -> mock.Mock:
                self.criteria = criteria
                return filename

        dialog = Dialog()
        self.assertIs(converter_automation._find_filename_edit(dialog), filename)
        self.assertEqual(
            dialog.criteria,
            {"auto_id": "1148", "control_type": "Edit"},
        )


if __name__ == "__main__":
    unittest.main()
