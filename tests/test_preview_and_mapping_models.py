import os
import random
import unittest
from unittest import mock

from fukua_rpa.mapping_backend import WindowMappingBackend
from fukua_rpa.preview_model import build_coordinate_preview
from fukua_rpa.win32_api import user32


class PreviewModelTests(unittest.TestCase):
    def test_offset_points_use_dashed_branches_not_a_solid_chain(self):
        tasks = [
            {"type": 1.0, "value": "0,0"},
            {
                "type": 1.0,
                "value": "10,0",
                "coord_step_en": True,
                "coord_step_direction": "移动到新点位",
                "coord_step_point": "30,0",
                "coord_step_max_steps": "3",
            },
            {"type": 1.0, "value": "40,0"},
        ]
        plan = build_coordinate_preview(tasks)
        self.assertEqual(len(plan.points), 5)
        segments = {(item["from"], item["to"], item["style"]) for item in plan.line_segments}
        self.assertIn((0, 1, "solid"), segments)
        self.assertIn((1, 4, "solid"), segments)
        self.assertIn((0, 2, "dash"), segments)
        self.assertIn((2, 4, "dash"), segments)
        self.assertIn((0, 3, "dash"), segments)
        self.assertIn((3, 4, "dash"), segments)
        self.assertNotIn((1, 2, "solid"), segments)
        self.assertNotIn((2, 3, "solid"), segments)

    def test_drag_has_an_internal_line_but_only_start_is_representative(self):
        plan = build_coordinate_preview(
            [
                {"type": 10.0, "value": "10,20 -> 30,40"},
                {"type": 1.0, "value": "50,60"},
            ]
        )
        segments = {(item["from"], item["to"], item["style"]) for item in plan.line_segments}
        self.assertIn((0, 1, "solid"), segments)
        self.assertIn((0, 2, "solid"), segments)
        self.assertNotIn((1, 2, "solid"), segments)

    def test_random_preview_segments_always_reference_existing_points(self):
        random.seed(20260711)
        for _case in range(200):
            tasks = []
            for index in range(random.randint(1, 100)):
                task = {"type": random.choice([1.0, 8.0, 10.0, 11.0])}
                if task["type"] in (10.0, 11.0):
                    task["value"] = f"{index},{index + 1} -> {index + 2},{index + 3}"
                else:
                    task["value"] = f"{index},{index + 1}"
                tasks.append(task)
            limit = random.randint(1, 80)
            plan = build_coordinate_preview(tasks, max_points=limit)
            self.assertLessEqual(len(plan.points), limit)
            self.assertEqual(len(plan.points), len(plan.labels))
            for segment in plan.line_segments:
                self.assertTrue(0 <= segment["from"] < len(plan.points))
                self.assertTrue(0 <= segment["to"] < len(plan.points))


class MappingBackendTests(unittest.TestCase):
    def test_uia_activation_precedes_post_message_for_single_left_click(self):
        uia = mock.Mock()
        uia.activate.return_value = {
            "success": True,
            "method": "UI Automation Invoke",
        }
        backend = WindowMappingBackend(uia_backend=uia)
        with mock.patch.object(
            backend, "resolve_binding", return_value=(123, 10, 20)
        ), mock.patch.object(
            backend, "screen_point_for_target", return_value=(210, 320)
        ), mock.patch.object(
            user32, "GetAncestor", return_value=100
        ), mock.patch.object(user32, "PostMessageW") as post:
            self.assertTrue(backend.background_click({"root_hwnd": 100}, "left", 1))

        uia.activate.assert_called_once_with(
            100,
            210,
            320,
            preferred_hwnd=123,
        )
        post.assert_not_called()
        self.assertEqual(backend.last_background_method, "UI Automation Invoke")

    def test_uia_failure_falls_back_to_post_message_without_foreground_click(self):
        uia = mock.Mock()
        uia.activate.return_value = {"success": False, "error": "not supported"}
        backend = WindowMappingBackend(uia_backend=uia)
        with mock.patch.object(
            backend, "resolve_binding", return_value=(123, 10, 20)
        ), mock.patch.object(
            backend, "screen_point_for_target", return_value=(210, 320)
        ), mock.patch.object(
            user32, "GetAncestor", return_value=100
        ), mock.patch.object(
            user32, "PostMessageW", return_value=True
        ) as post, mock.patch("fukua_rpa.mapping_backend.time.sleep"):
            self.assertTrue(backend.background_click({"root_hwnd": 100}, "left", 1))

        self.assertEqual(post.call_count, 3)
        self.assertEqual(backend.last_background_method, "PostMessage")

    def test_uia_timeout_never_sends_a_second_background_action(self):
        uia = mock.Mock()
        uia.activate.return_value = {
            "success": False,
            "timed_out": True,
            "outcome_unknown": True,
        }
        backend = WindowMappingBackend(uia_backend=uia)
        with mock.patch.object(
            backend, "resolve_binding", return_value=(123, 10, 20)
        ), mock.patch.object(
            backend, "screen_point_for_target", return_value=(210, 320)
        ), mock.patch.object(
            user32, "GetAncestor", return_value=100
        ), mock.patch.object(user32, "PostMessageW") as post:
            self.assertFalse(backend.background_click({"root_hwnd": 100}, "left", 1))

        post.assert_not_called()
        self.assertIn("未重复点击", backend.last_background_method)

    def test_manual_window_selection_is_separate_from_click_coordinate(self):
        backend = WindowMappingBackend()
        binding = {"root_hwnd": 700, "root_title": "Target"}
        with mock.patch.object(
            backend, "root_window_at_point", return_value=700
        ) as select_root, mock.patch.object(
            backend, "create_binding_for_root", return_value=binding
        ) as create:
            result = backend.create_binding_for_window_at_point(900, 500, 120, 80)

        self.assertEqual(result, binding)
        select_root.assert_called_once_with(900, 500, exclude_current_process=True)
        create.assert_called_once_with(700, 120, 80)

    def test_background_click_uses_bound_client_coordinates(self):
        backend = WindowMappingBackend()
        with mock.patch.object(backend, "resolve_binding", return_value=(123, 10, 20)), mock.patch.object(
            user32, "PostMessageW", return_value=True
        ) as post, mock.patch("fukua_rpa.mapping_backend.time.sleep"):
            self.assertTrue(backend.background_click({"root_hwnd": 123}, "left", 2))
        self.assertEqual(post.call_count, 5)
        self.assertTrue(all(call.args[0] == 123 for call in post.call_args_list))

    def test_process_path_binding_takes_priority_over_window_title(self):
        backend = WindowMappingBackend()
        expected = os.path.normcase(os.path.abspath("C:/Program Files/App/app.exe"))
        with mock.patch.object(user32, "IsWindow", return_value=True), mock.patch.object(
            backend, "class_name", return_value="Widget"
        ), mock.patch.object(backend, "process_info", return_value=(42, expected)), mock.patch.object(
            backend, "title", return_value="Changed title"
        ):
            self.assertTrue(
                backend.matches_binding(
                    123,
                    {
                        "root_class": "Widget",
                        "process_path": expected,
                        "root_title": "Old title",
                        "pid": 9,
                    },
                )
            )


if __name__ == "__main__":
    unittest.main()
