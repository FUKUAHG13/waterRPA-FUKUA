import unittest
from unittest import mock

from fukua_rpa.workflow_document import (
    apply_numeric_reference_edits,
    clone_task_for_insert,
    materialize_runtime_references,
    normalize_workflow_tasks,
    references_to_step,
    remove_task_and_clear_references,
)


class WorkflowDocumentTests(unittest.TestCase):
    def test_until_defaults_on_normal_steps_never_create_hidden_references(self):
        tasks = normalize_workflow_tasks(
            [
                {"type": 1.0, "value": "1,1", "until_false_jump": "1"},
                {"type": 1.0, "value": "2,2", "until_false_jump": "1"},
            ]
        )
        self.assertEqual(tasks[0]["until_false_target_id"], "")
        self.assertEqual(tasks[1]["until_false_target_id"], "")
        self.assertEqual(references_to_step(tasks, tasks[0]["step_id"]), [])

    def stable_tasks(self):
        return [
            {"step_id": "step_0001", "type": 5.0, "value": "0"},
            {
                "step_id": "step_0002",
                "type": 5.0,
                "value": "0",
                "success_jump": "3",
                "success_target_id": "step_0003",
            },
            {"step_id": "step_0003", "type": 5.0, "value": "0"},
        ]

    def test_legacy_numeric_jumps_migrate_to_stable_ids(self):
        tasks = [
            {"type": 5.0, "value": "0", "success_jump": "2"},
            {"type": 5.0, "value": "0"},
        ]
        with mock.patch(
            "fukua_rpa.workflow_document.new_step_id",
            side_effect=["generated_0001", "generated_0002"],
        ):
            normalized = normalize_workflow_tasks(tasks)
        self.assertEqual(normalized[0]["success_target_id"], "generated_0002")
        self.assertEqual(normalized[0]["success_jump"], "2")

    def test_reorder_keeps_target_identity_and_refreshes_display_number(self):
        first, branch, target = self.stable_tasks()
        reordered = materialize_runtime_references([target, first, branch])
        self.assertEqual(reordered[2]["success_target_id"], "step_0003")
        self.assertEqual(reordered[2]["success_jump"], "1")

    def test_explicit_number_edit_replaces_stable_target(self):
        tasks = normalize_workflow_tasks(self.stable_tasks())
        edited = dict(tasks[1], success_jump="1")
        resolved = apply_numeric_reference_edits(edited, tasks)
        self.assertEqual(resolved["success_target_id"], "step_0001")

    def test_delete_reports_and_clears_references(self):
        tasks = normalize_workflow_tasks(self.stable_tasks())
        references = references_to_step(tasks, "step_0003")
        self.assertEqual([(item.source_index, item.label) for item in references], [(2, "成功后跳至")])
        remaining = remove_task_and_clear_references(tasks, "step_0003")
        self.assertEqual(len(remaining), 2)
        self.assertEqual(remaining[1]["success_target_id"], "")
        self.assertEqual(remaining[1]["success_jump"], "0")

    def test_copy_rebases_self_reference_but_keeps_external_reference(self):
        task = {
            "step_id": "source_01",
            "success_target_id": "source_01",
            "fail_target_id": "external_01",
        }
        with mock.patch(
            "fukua_rpa.workflow_document.new_step_id",
            return_value="cloned_01",
        ):
            cloned = clone_task_for_insert(task)
        self.assertEqual(cloned["step_id"], "cloned_01")
        self.assertEqual(cloned["success_target_id"], "cloned_01")
        self.assertEqual(cloned["fail_target_id"], "external_01")

    def test_duplicate_ids_are_replaced(self):
        tasks = [
            {"step_id": "duplicate_01"},
            {"step_id": "duplicate_01"},
        ]
        with mock.patch(
            "fukua_rpa.workflow_document.new_step_id",
            return_value="replacement_01",
        ):
            normalized = normalize_workflow_tasks(tasks)
        self.assertEqual(normalized[0]["step_id"], "duplicate_01")
        self.assertEqual(normalized[1]["step_id"], "replacement_01")


if __name__ == "__main__":
    unittest.main()
