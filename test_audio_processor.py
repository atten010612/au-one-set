import argparse
import json
import tempfile
import unittest
from pathlib import Path, PureWindowsPath
from unittest import mock

import audio_processor
import converter_automation
import packer_automation


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

    def test_workflow_modes_skip_ffmpeg_for_existing_conversion_steps(self) -> None:
        for mode, helper, expected in (
            ("2", "run_conversion_from_existing_audio", True),
            ("3", "run_conversion_from_existing_audio", False),
            ("4", "run_packer_from_existing_conversion", None),
        ):
            with (
                mock.patch.object(
                    audio_processor,
                    "resolve_ffmpeg",
                    side_effect=AssertionError("FFmpeg must not be checked"),
                ),
                mock.patch.object(
                    audio_processor,
                    helper,
                    return_value=0,
                ) as run_step,
            ):
                self.assertEqual(
                    audio_processor.main(["--workflow-step", mode]),
                    0,
                )
            if expected is not None:
                self.assertEqual(run_step.call_args.kwargs["include_packer"], expected)

    def test_workflow_defaults_to_all_when_noninteractive(self) -> None:
        with mock.patch.object(audio_processor.sys.stdin, "isatty", return_value=False):
            self.assertEqual(audio_processor.choose_workflow_step(None), "0")
        self.assertEqual(audio_processor.choose_workflow_step("4"), "4")

    def test_existing_conversion_prefers_processed_audio(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "raw.wav"
            raw.touch()
            processed = root / "processed"
            processed.mkdir()
            ready = processed / "ready.wav"
            ready.touch()
            converted = root / "converted"
            converted.mkdir()
            (converted / "old.wav").touch()
            self.assertEqual(
                audio_processor.collect_existing_audio_for_conversion([str(root)]),
                [ready],
            )

    def test_only_synthesis_accepts_converted_or_processed_input_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            processed = root / "processed"
            processed.mkdir()
            converted = root / "converted"
            converted.mkdir()
            (converted / "voice.f1a").touch()
            self.assertEqual(
                audio_processor.existing_converted_directory(
                    [str(converted)],
                    root,
                    "converted",
                ),
                converted,
            )
            self.assertEqual(
                audio_processor.existing_converted_directory(
                    [str(processed)],
                    root,
                    "converted",
                ),
                converted,
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
            self.assertTrue(config.packer_enabled)
            self.assertEqual(config.packer_output_name, "OUTPUT.LST")
            self.assertEqual(config.packres_input_directory, "test_dir")
            self.assertEqual(config.packres_batch_name, "new_packres.bat")
            self.assertEqual(config.packres_output_name, "dir_music")

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

            processed = root / "processed"
            processed.mkdir()
            processed_output = converter_automation.conversion_output_directory(
                [str(processed)], script_directory, "converted"
            )
            self.assertEqual(processed_output, root / "converted")

    def test_converter_file_dialog_text_supports_unicode_paths(self) -> None:
        paths = [Path(r"D:\提示音\开始.wav"), Path(r"D:\提示音\结束.wav")]
        value = converter_automation.file_dialog_text(paths)
        self.assertIn('"', value)
        self.assertIn("开始.wav", value)
        self.assertIn("结束.wav", value)

    def test_converter_splits_large_file_sets_into_safe_batches(self) -> None:
        files = [Path(f"prompt-{index:02d}.wav") for index in range(43)]
        batches = converter_automation.file_batches(files)
        self.assertEqual([len(batch) for batch in batches], [8, 8, 8, 8, 8, 3])
        self.assertEqual(
            [path for batch in batches for path in batch],
            files,
        )

    def test_converter_uses_whole_folder_selection_when_audio_set_matches(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            files = [folder / f"prompt-{index}.wav" for index in range(43)]
            for path in files:
                path.touch()
            (folder / "processing-report.json").write_text("{}", encoding="utf-8")
            self.assertEqual(
                converter_automation.whole_folder_selection_candidate(files),
                folder,
            )
            extra = folder / "old-output.wav"
            extra.touch()
            self.assertIsNone(
                converter_automation.whole_folder_selection_candidate(files)
            )

    def test_file_batch_waits_until_filename_control_closes(self) -> None:
        filename = mock.Mock()
        filename.is_visible.side_effect = [True, False]
        converter_automation._wait_for_file_dialog_submission(
            filename,
            mock.Mock(),
            timeout=0.5,
        )

    def test_select_all_focus_falls_back_to_clicking_file_area(self) -> None:
        class Rectangle:
            left = 100
            top = 200

            def width(self) -> int:
                return 1000

            def height(self) -> int:
                return 600

        pane = mock.Mock()
        pane.is_visible.return_value = True
        pane.is_enabled.return_value = True
        pane.rectangle.return_value = Rectangle()
        dialog = mock.Mock()
        dialog.child_window.side_effect = RuntimeError("ItemsView unavailable")
        dialog.descendants.return_value = [pane]
        with (
            mock.patch.object(
                converter_automation,
                "_focus_win32_file_list",
                return_value=False,
            ),
            mock.patch.object(
                converter_automation,
                "_mouse_click",
            ) as mouse_click,
        ):
            method = converter_automation._focus_file_list_for_select_all(dialog)
        self.assertEqual(method, "文件区域点击")
        mouse_click.assert_called_once_with((750, 560))

    def test_select_all_uses_win32_list_before_physical_click(self) -> None:
        dialog = mock.Mock()
        dialog.child_window.side_effect = RuntimeError("ItemsView unavailable")
        with (
            mock.patch.object(
                converter_automation,
                "_focus_win32_file_list",
                return_value=True,
            ),
            mock.patch.object(converter_automation, "_mouse_click") as mouse_click,
        ):
            method = converter_automation._focus_file_list_for_select_all(dialog)
        self.assertEqual(method, "SysListView32")
        mouse_click.assert_not_called()

    def test_converter_selects_duplicate_32k_by_column(self) -> None:
        class Rectangle:
            def __init__(self, left: int) -> None:
                self.left = left

        class Control:
            def __init__(self, title: str, left: int) -> None:
                self.title = title
                self.left = left
                self.selected = False

            def is_visible(self) -> bool:
                return True

            def is_enabled(self) -> bool:
                return True

            def rectangle(self) -> Rectangle:
                return Rectangle(self.left)

            def window_text(self) -> str:
                return self.title

            def select(self) -> None:
                self.selected = True

            def click(self) -> None:
                self.selected = True

            def is_selected(self) -> bool:
                return self.selected

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
        self.assertTrue(sample_32k.selected)
        self.assertFalse(bitrate_32k.selected)
        converter_automation._select_radio(window, "32K", column=2)
        self.assertTrue(bitrate_32k.selected)

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

    def test_filename_field_supports_legacy_save_dialog_id_1152(self) -> None:
        missing = mock.Mock()
        missing.wait.side_effect = RuntimeError("1148 unavailable")
        legacy = mock.Mock()

        class Dialog:
            def child_window(self, **criteria: object) -> mock.Mock:
                return missing if criteria["auto_id"] == "1148" else legacy

        self.assertIs(
            converter_automation._find_filename_edit(Dialog()),
            legacy,
        )
        legacy.wait.assert_called_once_with("visible enabled", timeout=2)

    def test_file_import_waits_for_table_items_not_dialog_close(self) -> None:
        class Window:
            def __init__(self) -> None:
                self.calls = 0

            def descendants(self, control_type: str) -> list[object]:
                self.calls += 1
                return [] if self.calls == 1 else [object(), object(), object()]

        window = Window()
        previous = converter_automation._data_item_count(window)
        converter_automation._wait_for_added_files(
            window,
            previous_item_count=previous,
            timeout=0.1,
        )

    def test_button_matching_ignores_converter_newlines(self) -> None:
        button = mock.Mock()
        button.is_visible.return_value = True
        button.is_enabled.return_value = True
        button.window_text.return_value = "\n开始转换\n"
        window = mock.Mock()
        window.child_window.side_effect = RuntimeError("exact title unavailable")
        window.descendants.return_value = [button]
        converter_automation._click_button(window, "开始转换")
        button.click.assert_called_once_with()

    def test_output_directory_is_pasted_and_verified_without_uia_set_value(self) -> None:
        narrow_edit = mock.Mock()
        narrow_edit.is_visible.return_value = True
        narrow_edit.is_enabled.return_value = True
        narrow_edit.rectangle.return_value.width.return_value = 80
        output_edit = mock.Mock()
        output_edit.is_visible.return_value = True
        output_edit.is_enabled.return_value = True
        output_edit.rectangle.return_value.width.return_value = 600
        window = mock.Mock()
        window.descendants.return_value = [narrow_edit, output_edit]
        output_path = Path(r"D:\au-one-set\converted")
        with (
            mock.patch.object(
                converter_automation,
                "_set_windows_clipboard",
            ) as set_clipboard,
            mock.patch.object(converter_automation, "_send_keys") as send_keys,
            mock.patch.object(
                converter_automation,
                "_native_set_window_text",
                return_value=False,
            ),
            mock.patch.object(
                converter_automation,
                "_read_control_text",
                side_effect=["", str(output_path)],
            ),
        ):
            converter_automation._set_output_directory(window, output_path)
        output_edit.set_focus.assert_called_once_with()
        output_edit.set_edit_text.assert_not_called()
        set_clipboard.assert_called_once_with(str(output_path))
        self.assertEqual(
            [call.args[0] for call in send_keys.call_args_list],
            ["^a", "^v", "{TAB}"],
        )

    def test_output_directory_prefers_verified_native_window_text(self) -> None:
        edit = mock.Mock()
        edit.is_visible.return_value = True
        edit.is_enabled.return_value = True
        edit.rectangle.return_value.width.return_value = 600
        window = mock.Mock()
        window.descendants.return_value = [edit]
        output_path = Path(r"D:\au-one-set\converted")
        with (
            mock.patch.object(
                converter_automation,
                "_native_set_window_text",
                return_value=True,
            ) as native_set,
            mock.patch.object(
                converter_automation,
                "_read_control_text",
                return_value=str(output_path),
            ),
            mock.patch.object(
                converter_automation,
                "_set_windows_clipboard",
            ) as set_clipboard,
        ):
            converter_automation._set_output_directory(window, output_path)
        native_set.assert_called_once_with(edit, str(output_path))
        set_clipboard.assert_not_called()

    def test_output_directory_uses_application_folder_picker_as_last_resort(self) -> None:
        edit = mock.Mock()
        edit.is_visible.return_value = True
        edit.is_enabled.return_value = True
        edit.rectangle.return_value.width.return_value = 600
        window = mock.Mock()
        window.descendants.return_value = [edit]
        output_path = Path(r"D:\au-one-set\converted")
        with (
            mock.patch.object(
                converter_automation,
                "_native_set_window_text",
                return_value=False,
            ),
            mock.patch.object(
                converter_automation,
                "_read_control_text",
                return_value="",
            ),
            mock.patch.object(converter_automation, "_set_windows_clipboard"),
            mock.patch.object(converter_automation, "_send_keys"),
            mock.patch.object(
                converter_automation,
                "_choose_output_directory_with_dialog",
            ) as choose_directory,
        ):
            converter_automation._set_output_directory(window, output_path)
        choose_directory.assert_called_once_with(window, edit, output_path)

    def test_folder_confirmation_button_is_selected_by_text(self) -> None:
        button = mock.Mock()
        button.is_visible.return_value = True
        button.is_enabled.return_value = True
        button.window_text.return_value = " 选择文件夹 "
        dialog = mock.Mock()
        dialog.descendants.return_value = [button]
        converter_automation._click_folder_confirmation(dialog)
        button.click.assert_called_once_with()

    def test_conversion_success_requires_actual_output_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            previous = converter_automation._file_snapshot(output)
            (output / "result.f1a").write_bytes(b"converted")
            with mock.patch.object(
                converter_automation,
                "_new_visible_windows",
                return_value=[],
            ):
                count = converter_automation._wait_for_conversion_outputs(
                    mock.Mock(),
                    mock.Mock(),
                    output,
                    previous,
                    previous_handles=set(),
                    expected_count=1,
                    timeout=0.1,
                )
            self.assertEqual(count, 1)

    def test_conversion_error_dialog_prevents_false_success(self) -> None:
        dialog = mock.Mock()
        dialog.window_text.return_value = "音频文件转换工具 1.2.2"
        message = mock.Mock()
        message.window_text.return_value = "错误：请选择输出文件位置。"
        dialog.descendants.return_value = [message]
        with tempfile.TemporaryDirectory() as directory:
            with (
                mock.patch.object(
                    converter_automation,
                    "_new_visible_windows",
                    return_value=[dialog],
                ),
                self.assertRaisesRegex(
                    converter_automation.ConverterAutomationError,
                    "请选择输出文件位置",
                ),
            ):
                converter_automation._wait_for_conversion_outputs(
                    mock.Mock(),
                    mock.Mock(),
                    Path(directory),
                    previous_files={},
                    previous_handles=set(),
                    expected_count=1,
                    timeout=0.1,
                )

    def test_conversion_completion_dialog_is_dismissed_while_waiting(self) -> None:
        dialog = mock.Mock()
        dialog.window_text.return_value = "音频文件转换工具 1.2.2"
        message = mock.Mock()
        message.window_text.return_value = "转换完成"
        ok = mock.Mock()
        ok.window_text.return_value = "确定"

        def descendants(control_type: str) -> list[mock.Mock]:
            return [ok] if control_type == "Button" else [message]

        dialog.descendants.side_effect = descendants
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.object(
                converter_automation,
                "_file_snapshot",
                side_effect=[{}, {"result.f1a": (1, 1)}],
            ),
            mock.patch.object(
                converter_automation,
                "_new_visible_windows",
                return_value=[dialog],
            ),
        ):
            count = converter_automation._wait_for_conversion_outputs(
                mock.Mock(),
                mock.Mock(),
                Path(directory),
                previous_files={},
                previous_handles=set(),
                expected_count=1,
                timeout=1,
            )
        self.assertEqual(count, 1)
        ok.click.assert_called_once_with()

    def test_actual_outputs_take_priority_over_completion_popup(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.object(
                converter_automation,
                "_file_snapshot",
                return_value={"result.f1a": (1, 1)},
            ),
            mock.patch.object(
                converter_automation,
                "_new_visible_windows",
                side_effect=AssertionError("dialog must not override outputs"),
            ),
        ):
            count = converter_automation._wait_for_conversion_outputs(
                mock.Mock(),
                mock.Mock(),
                Path(directory),
                previous_files={},
                previous_handles=set(),
                expected_count=1,
                timeout=0.1,
            )
        self.assertEqual(count, 1)

    def test_existing_matching_outputs_count_with_newly_converted_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            inputs = [Path(f"voice-{index:02d}.wav") for index in range(43)]
            for path in inputs[:17]:
                (output / f"{path.stem}.f1a").write_bytes(b"existing")
            previous = converter_automation._file_snapshot(output)
            for path in inputs[17:]:
                (output / f"{path.stem}.f1a").write_bytes(b"new")
            with mock.patch.object(
                converter_automation,
                "_new_visible_windows",
                return_value=[],
            ):
                count = converter_automation._wait_for_conversion_outputs(
                    mock.Mock(),
                    mock.Mock(),
                    output,
                    previous_files=previous,
                    previous_handles=set(),
                    expected_count=43,
                    expected_inputs=inputs,
                    timeout=0.1,
                )
            self.assertEqual(count, 43)

    def test_packer_tree_navigation_expands_each_path_component(self) -> None:
        class Item:
            def __init__(self, name: str, children: dict[str, "Item"] | None = None) -> None:
                self.name = name
                self.children_by_name = children or {}
                self.expanded = False
                self.selected = False

            def text(self) -> str:
                return self.name

            def expand(self) -> None:
                self.expanded = True

            def get_child(self, name: str, exact: bool) -> "Item":
                self.exact = exact
                return self.children_by_name[name]

            def children(self) -> list["Item"]:
                return list(self.children_by_name.values())

            def ensure_visible(self) -> None:
                pass

            def select(self) -> None:
                self.selected = True

        converted = Item("converted")
        project = Item("au-one-set", {"converted": converted})
        root = Item("D:\\", {"au-one-set": project})
        tree = mock.Mock()
        tree.roots.return_value = [root]
        selected = packer_automation.navigate_tree_to_directory(
            tree,
            PureWindowsPath(r"D:\au-one-set\converted"),
        )
        self.assertIs(selected, converted)
        self.assertTrue(root.expanded)
        self.assertTrue(project.expanded)
        self.assertTrue(converted.selected)
        self.assertFalse(converted.expanded)

    def test_packer_drive_selection_matches_volume_prefix(self) -> None:
        combo = mock.Mock()
        combo.window_text.return_value = "c: [系统]"
        combo.item_texts.return_value = ["c: [系统]", "d: [软件]"]
        window = mock.Mock()
        window.descendants.return_value = [combo]
        packer_automation._select_drive(window, "D:")
        combo.select.assert_called_once_with(1)

    def test_packer_skips_drive_selection_when_already_selected(self) -> None:
        combo = mock.Mock()
        combo.window_text.return_value = "d: [软件]"
        window = mock.Mock()
        window.descendants.return_value = [combo]
        packer_automation._select_drive(window, "D:")
        combo.item_texts.assert_not_called()
        combo.select.assert_not_called()

    def test_packer_enters_each_delphi_directory_with_double_click_action(self) -> None:
        class DirectoryList:
            handle = None

            def __init__(self) -> None:
                self.stage = 0
                self.selected = ""

            def item_texts(self) -> list[str]:
                if self.stage == 0:
                    return ["D:\\", "project", "g5-1", "g5-2-belt"]
                if self.stage == 1:
                    return ["D:\\", "au-one-set", "cursor", "project"]
                return ["D:\\", "au-one-set", "converted"]

            def select(self, index: int) -> None:
                self.selected = self.item_texts()[index]

            def type_keys(self, keys: str) -> None:
                self.asserted_keys = keys
                self.stage += 1

            def selected_text(self) -> str:
                return self.selected

        directory_list = DirectoryList()
        window = mock.Mock()
        window.descendants.return_value = [directory_list]
        packer_automation.navigate_directory_list(
            window,
            PureWindowsPath(r"D:\au-one-set\converted"),
        )
        self.assertEqual(directory_list.selected, "converted")
        self.assertEqual(directory_list.stage, 3)

    def test_packer_save_uses_delphi_bit_button_message(self) -> None:
        save = mock.Mock()
        save.window_text.return_value = "保存"
        window = mock.Mock()
        window.descendants.return_value = [save]
        packer_automation._click_save(window)
        save.post_message.assert_called_once_with(0x00F5)
        save.send_message.assert_not_called()

    def test_packer_overwrite_confirmation_is_clicked(self) -> None:
        yes = mock.Mock()
        yes.window_text.return_value = "是(Y)"
        dialog = mock.Mock()
        dialog.descendants.return_value = [yes]
        self.assertTrue(packer_automation._click_overwrite_confirmation(dialog))
        yes.click.assert_called_once_with()

    def test_packer_success_requires_updated_output_lst(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "OUTPUT.LST"
            output.write_bytes(b"old")
            previous = packer_automation._signature(output)
            output.write_bytes(b"new package")
            packer_automation._wait_for_package(output, previous, timeout=0.1)

    def test_packer_promotes_updated_fixed_list_to_output_lst(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = root / "LIST.LST"
            output = root / "OUTPUT.LST"
            legacy.write_bytes(b"old")
            previous = packer_automation._signature(legacy)
            legacy.write_bytes(b"new package")
            self.assertTrue(
                packer_automation._promote_updated_legacy_list(output, previous)
            )
            self.assertEqual(output.read_bytes(), b"new package")

    def test_packer_stages_only_converted_audio_formats(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "converted"
            target = root / "packres"
            source.mkdir()
            target.mkdir()
            (target / "stale.f1b").write_bytes(b"stale")
            (target / "keep.txt").write_text("keep", encoding="utf-8")
            expected_names = {"a.f1a", "b.f1b", "c.ump3", "d.a", "e.e"}
            for name in expected_names:
                (source / name).write_bytes(name.encode())
            (source / "converter-controls.txt").write_text("log", encoding="utf-8")
            staged = packer_automation.stage_converted_files(source, target)
            self.assertEqual({path.name for path in staged}, expected_names)
            self.assertFalse((target / "converter-controls.txt").exists())
            self.assertFalse((target / "stale.f1b").exists())
            self.assertTrue((target / "keep.txt").exists())

    def test_relative_packres_input_uses_suite_sibling_test_dir(self) -> None:
        executable = Path("/suite/AD140打包工具/packres/pRFiles.exe")
        self.assertEqual(
            packer_automation.resolve_packres_input_directory(
                executable,
                "test_dir",
            ),
            Path("/suite/test_dir"),
        )

    def test_packres_batch_requires_updated_dir_music(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            batch = root / "new_packres.bat"
            batch.write_text("@echo off", encoding="utf-8")
            config = converter_automation.ConverterConfig()

            def run_batch(*args: object, **kwargs: object) -> mock.Mock:
                (root / "dir_music").write_bytes(b"package")
                return mock.Mock(returncode=0, stdout="ok")

            with mock.patch.object(
                packer_automation.subprocess,
                "run",
                side_effect=run_batch,
            ) as run:
                output = packer_automation.run_packres_batch(root, config)
            self.assertEqual(output, root / "dir_music")
            self.assertEqual(run.call_args.kwargs["cwd"], str(root))
            self.assertIn(str(batch), run.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
