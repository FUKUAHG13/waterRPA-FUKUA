import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QListWidgetItem

from fukua_rpa.ui.task_row import DraggableListWidget


class DragInsertPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_list(self, count=5):
        widget = DraggableListWidget()
        for index in range(count):
            widget.addItem(QListWidgetItem(f"step {index + 1}"))
        return widget

    def test_upward_drop_reports_resulting_step_number(self):
        widget = self.make_list()
        widget.setCurrentRow(3)
        widget.drop_line_row = 0
        widget.drop_line_after = False
        self.assertEqual(widget._insertion_index(), 0)

    def test_downward_drop_accounts_for_removed_source_row(self):
        widget = self.make_list()
        widget.setCurrentRow(1)
        widget.drop_line_row = 4
        widget.drop_line_after = True
        self.assertEqual(widget._insertion_index(), 4)

    def test_preview_pixmap_uses_full_row_widget_when_available(self):
        widget = self.make_list(1)
        pixmap = widget._drag_preview_pixmap(widget.item(0))
        self.assertFalse(pixmap.isNull())
        self.assertGreaterEqual(pixmap.width(), 260)


if __name__ == "__main__":
    unittest.main()
