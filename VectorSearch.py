"""PyQt5 front end for the local vector text scanner."""
import json
import os
import queue
import shutil
import tempfile
import sys
import threading
import time
from dataclasses import asdict, replace
from pathlib import Path

from PyQt5.QtCore import QThread, QTimer
from PyQt5.QtWidgets import (QApplication, QCheckBox, QFileDialog, QHBoxLayout,
                             QLabel, QLineEdit, QPlainTextEdit, QPushButton,
                             QSpinBox, QVBoxLayout, QWidget)

from vector_scanner import DEFAULT_EXCLUDES, ScanOptions, ScanStats, scan_directory

DISPLAY_LIMIT = 1000


class SearchThread(QThread):
    """Backpressure keeps a fast scanner from flooding Qt's event queue."""
    def __init__(self, directory, options=None):
        super().__init__()
        self.directory = directory
        self.options = options or ScanOptions()
        self.result_file = tempfile.TemporaryFile(mode="w+t", encoding="utf-8", newline="\n")
        self.events = queue.Queue(maxsize=16)
        self.stop_event = threading.Event()
        self.stats = ScanStats()
        self.last_progress = 0.0

    def cancel(self):
        self.stop_event.set()

    def publish(self, kind, payload):
        while not self.stop_event.is_set():
            try:
                self.events.put((kind, payload), timeout=0.05)
                return True
            except queue.Full:
                pass
        return False

    def progress(self, stats):
        now = time.monotonic()
        if now - self.last_progress >= 0.1:
            self.publish("progress", replace(stats))
            self.last_progress = now

    def run(self):
        batch = []
        try:
            for match in scan_directory(self.directory, self.options, stats=self.stats,
                                        cancelled=self.stop_event.is_set,
                                        on_error=lambda message: self.publish("error", message),
                                        on_progress=self.progress):
                self.result_file.write(json.dumps(asdict(match), ensure_ascii=True) + "\n")
                batch.append(f"{match.path}:{match.line}:{match.column}  "
                             f"{match.kind}({', '.join(match.values)})")
                if len(batch) >= 32:
                    if not self.publish("results", batch):
                        break
                    batch = []
                    self.progress(self.stats)
            if batch:
                self.publish("results", batch)
        except Exception as error:
            self.stats.errors += 1
            self.publish("error", str(error))
        finally:
            try:
                self.result_file.flush()
            except OSError as error:
                self.stats.errors += 1
                self.publish("error", f"Cannot save temporary results: {error}")
            self.stats.cancelled = self.stop_event.is_set()


class VectorSearchApp(QWidget):
    def __init__(self):
        super().__init__()
        self.directory = ""
        self.search_thread = None
        self.result_file = None
        self.closing = False
        self.setWindowTitle("Vector Search by Master0fFate")
        self.resize(850, 600)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Search numeric vector3 / vector4 literals in local files"))
        self.directory_label = QLabel("No directory selected")
        self.directory_label.setWordWrap(True)
        layout.addWidget(self.directory_label)
        self.browse_button = QPushButton("Choose directory…")
        self.browse_button.clicked.connect(self.browse_directory)
        layout.addWidget(self.browse_button)
        settings = QHBoxLayout()
        settings.addWidget(QLabel("Extensions:"))
        self.extensions = QLineEdit()
        self.extensions.setPlaceholderText("All files, or lua, js, txt")
        self.extensions.setAccessibleName("File extensions")
        settings.addWidget(self.extensions)
        settings.addWidget(QLabel("Match limit:"))
        self.max_matches = QSpinBox()
        self.max_matches.setRange(0, 1000000)
        self.max_matches.setValue(0)
        self.max_matches.setSpecialValueText("Unlimited")
        self.max_matches.setAccessibleName("Maximum matches")
        settings.addWidget(self.max_matches)
        layout.addLayout(settings)
        self.include_generated = QCheckBox("Include generated and version-control directories")
        layout.addWidget(self.include_generated)
        buttons = QHBoxLayout()
        self.start_button = QPushButton("Start")
        self.start_button.clicked.connect(self.start_search)
        buttons.addWidget(self.start_button)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_search)
        buttons.addWidget(self.cancel_button)
        self.copy_button = QPushButton("Copy visible results")
        self.copy_button.clicked.connect(self.copy_to_clipboard)
        buttons.addWidget(self.copy_button)
        self.export_button = QPushButton("Export all results…")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export_results)
        buttons.addWidget(self.export_button)
        layout.addLayout(buttons)
        self.status_label = QLabel("Ready")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.result_text = QPlainTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setMaximumBlockCount(DISPLAY_LIMIT)
        self.result_text.setLineWrapMode(QPlainTextEdit.NoWrap)
        layout.addWidget(self.result_text)
        layout.addWidget(QLabel("Display: latest 1,000 lines. Export: all results found. Scan limit is optional."))
        self.timer = QTimer(self)
        self.timer.setInterval(30)
        self.timer.timeout.connect(self.drain_events)
        self.setStyleSheet("QWidget { background: #25282e; color: #eceff4; } "
                           "QPushButton, QLineEdit, QSpinBox { padding: 6px; } "
                           "QPlainTextEdit { background: #191b20; font-family: monospace; } "
                           "QPushButton:disabled { color: #747b87; }")

    def browse_directory(self):
        chosen = QFileDialog.getExistingDirectory(self, "Select Directory", self.directory)
        if chosen:
            self.directory = chosen
            self.directory_label.setText(chosen)

    def set_running(self, running):
        for widget in (self.start_button, self.browse_button, self.extensions,
                       self.max_matches, self.include_generated):
            widget.setEnabled(not running)
        self.cancel_button.setEnabled(running)

    def start_search(self):
        if self.search_thread is not None:
            return
        if not self.directory or not Path(self.directory).is_dir():
            self.status_label.setText("Please select an existing directory first.")
            return
        options = ScanOptions(tuple(self.extensions.text().split(",")),
                              frozenset() if self.include_generated.isChecked() else DEFAULT_EXCLUDES,
                              self.max_matches.value())
        try:
            worker = SearchThread(self.directory, options)
        except OSError as error:
            self.status_label.setText(f"Cannot create temporary result storage: {error}")
            return
        if self.result_file is not None:
            self.result_file.close()
            self.result_file = None
        self.export_button.setEnabled(False)
        self.result_text.clear()
        self.set_running(True)
        self.status_label.setText("Searching…")
        self.search_thread = worker
        self.search_thread.start()
        self.timer.start()

    def cancel_search(self):
        if self.search_thread is not None:
            self.search_thread.cancel()
            self.cancel_button.setEnabled(False)
            self.status_label.setText("Cancelling…")

    def show_stats(self, stats, prefix="Searching"):
        self.status_label.setText(f"{prefix}: {stats.files} files, {stats.matches} vectors, "
                                  f"{stats.errors} errors, {stats.skipped_binary} binary files skipped")

    def drain_events(self):
        worker = self.search_thread
        if worker is None:
            return
        for _ in range(8):
            try:
                kind, payload = worker.events.get_nowait()
            except queue.Empty:
                break
            if kind == "results":
                self.result_text.appendPlainText("\n".join(payload))
            elif kind == "error":
                self.result_text.appendPlainText("Error: " + payload.replace("\n", " "))
            elif not worker.stop_event.is_set():
                self.show_stats(payload)
        if not worker.isRunning() and worker.events.empty():
            self.timer.stop()
            self.set_running(False)
            status = ("Cancelled (queued display rows may be omitted)" if worker.stats.cancelled else
                      "Stopped at match limit" if worker.stats.limit_reached else
                      "Done with errors" if worker.stats.errors else "Done")
            self.show_stats(worker.stats, status)
            self.result_file = worker.result_file
            worker.result_file = None
            self.export_button.setEnabled(True)
            worker.deleteLater()
            self.search_thread = None
            if self.closing:
                self.close()

    def copy_to_clipboard(self):
        QApplication.clipboard().setText(self.result_text.toPlainText())

    def save_results(self, destination):
        """Stream a complete or cancelled scan's JSONL spool to an atomic export."""
        if self.search_thread is not None or self.result_file is None:
            return False
        temporary = None
        try:
            destination = Path(destination)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                             dir=destination.parent, delete=False) as output:
                temporary = output.name
                self.result_file.seek(0)
                shutil.copyfileobj(self.result_file, output, length=64 * 1024)
            os.replace(temporary, destination)
            return True
        except OSError as error:
            self.status_label.setText(f"Export failed: {error}")
            return False
        finally:
            if temporary and os.path.exists(temporary):
                try:
                    os.unlink(temporary)
                except OSError as error:
                    self.status_label.setText(f"Could not remove temporary export {temporary}: {error}")

    def export_results(self):
        destination, _ = QFileDialog.getSaveFileName(self, "Export all results", "vectors.jsonl",
                                                   "JSON Lines (*.jsonl);;All files (*)")
        if destination and self.save_results(destination):
            self.status_label.setText("Exported all saved matches, including those outside the display window.")

    def closeEvent(self, event):
        if self.search_thread is not None:
            self.closing = True
            self.cancel_search()
            event.ignore()
        else:
            if self.result_file is not None:
                self.result_file.close()
                self.result_file = None
            event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = VectorSearchApp()
    window.show()
    sys.exit(app.exec_())
