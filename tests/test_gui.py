import json
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

try:
    from PyQt5.QtWidgets import QApplication
    from VectorSearch import DISPLAY_LIMIT, SearchThread, VectorSearchApp
except ImportError:
    QApplication = None

from vector_scanner import ScanOptions


@unittest.skipIf(QApplication is None, "Install requirements.txt for GUI tests")
class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.window = VectorSearchApp()
        self.window.directory = str(self.root)
        self.addCleanup(self.window.close)

    def until(self, predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while not predicate():
            self.app.processEvents()
            if time.monotonic() > deadline:
                self.fail("Timed out waiting for GUI state")
            time.sleep(0.002)
        self.app.processEvents()

    def test_complete_repeat_and_copy_literal_markup(self):
        filename = "literal&name.lua" if os.name == "nt" else "<b>.lua"
        (self.root / filename).write_text("vector3(1,2,3) vector4(1,2,3,4)")
        self.window.start_search()
        self.until(lambda: self.window.search_thread is None)
        self.assertIn("Done: 1 files, 2 vectors", self.window.status_label.text())
        self.assertIn(filename, self.window.result_text.toPlainText())
        self.window.copy_to_clipboard()
        self.assertEqual(self.app.clipboard().text(), self.window.result_text.toPlainText())
        self.window.start_search()
        worker = self.window.search_thread
        self.window.start_search()
        self.assertIs(worker, self.window.search_thread)
        self.until(lambda: self.window.search_thread is None)
        self.assertEqual(len(self.window.result_text.toPlainText().splitlines()), 2)

    def test_cap_display_and_limit_status(self):
        (self.root / "many.lua").write_text("vector3(1,2,3)\n" * 2000)
        self.window.max_matches.setValue(1200)
        self.window.start_search()
        self.until(lambda: self.window.search_thread is None)
        self.assertIn("Stopped at match limit", self.window.status_label.text())
        self.assertEqual(self.window.result_text.document().blockCount(), DISPLAY_LIMIT)

    def test_close_cancels_and_defers_destruction(self):
        (self.root / "many.lua").write_text("vector3(1,2,3)\n" * 100000)
        self.window.show()
        self.window.start_search()
        self.window.close()
        self.assertTrue(self.window.closing)
        self.until(lambda: self.window.search_thread is None)
        self.assertFalse(self.window.isVisible())
        self.assertIn("Cancelled", self.window.status_label.text())

    def test_backpressure_can_cancel_without_gui_consumer(self):
        (self.root / "many.lua").write_text("vector3(1,2,3)\n" * 100000)
        worker = SearchThread(str(self.root), ScanOptions(max_matches=0))
        worker.start()
        try:
            self.until(worker.events.full)
            worker.cancel()
            self.assertTrue(worker.wait(2000))
            self.assertTrue(worker.stats.cancelled)
            self.assertLessEqual(worker.events.qsize(), 16)
            worker.result_file.seek(0)
            self.assertEqual(sum(1 for _ in worker.result_file), worker.stats.matches)
        finally:
            worker.cancel()
            worker.wait(2000)
            worker.result_file.close()

    def test_unlimited_export_preserves_results_beyond_display_and_cleans_up(self):
        (self.root / "many.lua").write_text("vector3(1,2,3)\n" * 2500)
        self.assertEqual(self.window.max_matches.value(), 0)
        self.window.start_search()
        self.until(lambda: self.window.search_thread is None)
        self.assertEqual(self.window.result_text.document().blockCount(), DISPLAY_LIMIT)
        destination = self.root / "all.jsonl"
        self.assertTrue(self.window.save_results(destination))
        rows = [json.loads(line) for line in destination.read_text().splitlines()]
        self.assertEqual(len(rows), 2500)
        self.assertEqual(rows[0]["line"], 1)
        self.assertEqual(rows[-1]["line"], 2500)
        spool = self.window.result_file
        self.window.close()
        self.assertTrue(spool.closed)

    def test_export_failure_preserves_existing_destination(self):
        (self.root / "one.lua").write_text("vector3(1,2,3)")
        self.window.start_search()
        self.until(lambda: self.window.search_thread is None)
        destination = self.root / "results.jsonl"
        destination.write_text("keep me")
        with patch("VectorSearch.os.replace", side_effect=PermissionError("fixture write denied")):
            self.assertFalse(self.window.save_results(destination))
        self.assertEqual(destination.read_text(), "keep me")
        self.assertIn("Export failed", self.window.status_label.text())

    def test_new_scan_closes_previous_spool(self):
        (self.root / "one.lua").write_text("vector3(1,2,3)")
        self.window.start_search()
        self.until(lambda: self.window.search_thread is None)
        spool = self.window.result_file
        self.window.start_search()
        self.assertTrue(spool.closed)
        self.assertFalse(self.window.export_button.isEnabled())
        self.until(lambda: self.window.search_thread is None)

    def test_missing_directory_does_not_start(self):
        self.window.directory = str(self.root / "missing")
        self.window.start_search()
        self.assertIsNone(self.window.search_thread)
        self.assertIn("existing directory", self.window.status_label.text())

    def test_decode_error_is_visible_and_controls_restore(self):
        (self.root / "bad.lua").write_bytes(b"\xff")
        self.window.start_search()
        self.until(lambda: self.window.search_thread is None)
        self.assertIn("Done with errors", self.window.status_label.text())
        self.assertIn("Error: bad.lua", self.window.result_text.toPlainText())
        self.assertTrue(self.window.start_button.isEnabled())
        self.assertFalse(self.window.cancel_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
