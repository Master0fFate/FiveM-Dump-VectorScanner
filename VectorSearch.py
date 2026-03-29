import sys
import os
import re
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QPushButton, QFileDialog,
                             QLabel, QTextEdit, QHBoxLayout)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QCursor

SEARCH_PATTERNS = {
    'vector3': re.compile(r'vector3\(\s*-?\d+(\.\d+)?\s*,\s*-?\d+(\.\d+)?\s*,\s*-?\d+(\.\d+)?\s*\)'),
    'vector4': re.compile(r'vector4\(\s*-?\d+(\.\d+)?\s*,\s*-?\d+(\.\d+)?\s*,\s*-?\d+(\.\d+)?\s*,\s*-?\d+(\.\d+)?\s*\)'),
}


class SearchThread(QThread):
    result_found = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    progress_updated = pyqtSignal(int, int)
    finished = pyqtSignal()

    def __init__(self, directory):
        super().__init__()
        self.directory = directory
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    def run(self):
        files_processed = 0
        matches_found = 0

        for root, dirs, files in os.walk(self.directory):
            if self.cancelled:
                break

            for file_name in files:
                if self.cancelled:
                    break

                file_path = os.path.join(root, file_name)
                files_processed += 1

                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        for line_number, line in enumerate(f, 1):
                            if self.cancelled:
                                break
                            for pattern in SEARCH_PATTERNS.values():
                                if pattern.search(line):
                                    matches_found += 1
                                    result = f"{file_path} {line_number}\n{line.strip()}\n"
                                    self.result_found.emit(result)
                                    break
                except PermissionError:
                    self.error_occurred.emit(f"Permission denied: {file_path}")
                except (OSError, IOError) as e:
                    self.error_occurred.emit(f"Cannot read file: {file_path} ({e})")

                if files_processed % 100 == 0:
                    self.progress_updated.emit(files_processed, matches_found)

        self.progress_updated.emit(files_processed, matches_found)
        self.finished.emit()


class VectorSearchApp(QWidget):
    def __init__(self):
        super().__init__()
        self.directory = ""
        self.search_thread = None
        self.initUI()

    def initUI(self):
        self.setWindowFlag(Qt.FramelessWindowHint)

        self.main_layout = QVBoxLayout()
        self.setStyleSheet(self.darkStyleSheet())

        header_layout = QHBoxLayout()

        self.title_label = QLabel("Vector Searcher by Master0fFate", self)
        header_layout.addWidget(self.title_label)

        self.close_button = QPushButton("X")
        self.close_button.setObjectName("closeButton")
        self.close_button.clicked.connect(self.close)
        header_layout.addWidget(self.close_button, alignment=Qt.AlignRight)

        self.main_layout.addLayout(header_layout)

        self.instruction_label = QLabel("Select a directory and press Start to search.")
        self.main_layout.addWidget(self.instruction_label)

        self.directory_label = QLabel("No directory selected")
        self.main_layout.addWidget(self.directory_label)

        self.browse_button = QPushButton("Browse")
        self.browse_button.clicked.connect(self.browse_directory)
        self.main_layout.addWidget(self.browse_button)

        button_layout = QHBoxLayout()

        self.start_button = QPushButton("Start")
        self.start_button.clicked.connect(self.start_search)
        button_layout.addWidget(self.start_button)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_search)
        button_layout.addWidget(self.cancel_button)

        self.main_layout.addLayout(button_layout)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusLabel")
        self.main_layout.addWidget(self.status_label)

        result_layout = QVBoxLayout()

        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        result_layout.addWidget(self.result_text)

        self.copy_label = QLabel('<a href="#" style="color: lightgray;">Copy to Clipboard</a>')
        self.copy_label.setAlignment(Qt.AlignRight)
        self.copy_label.setObjectName("copyLabel")
        self.copy_label.linkActivated.connect(self.copy_to_clipboard)
        self.copy_label.setCursor(QCursor(Qt.PointingHandCursor))
        result_layout.addWidget(self.copy_label, alignment=Qt.AlignRight)

        self.main_layout.addLayout(result_layout)

        self.setLayout(self.main_layout)
        self.setWindowTitle("Vector Search Application")
        self.setGeometry(300, 300, 600, 500)

    def browse_directory(self):
        chosen = QFileDialog.getExistingDirectory(self, "Select Directory")
        if chosen:
            self.directory = chosen
            self.directory_label.setText(self.directory)

    def start_search(self):
        if not self.directory:
            self.status_label.setText("Please select a directory first.")
            return

        if not os.path.isdir(self.directory):
            self.status_label.setText(f"Directory not found: {self.directory}")
            return

        if not os.access(self.directory, os.R_OK):
            self.status_label.setText(f"Permission denied: {self.directory}")
            return

        self.result_text.clear()
        self.status_label.setText("Searching...")
        self.start_button.setEnabled(False)
        self.cancel_button.setEnabled(True)

        self.search_thread = SearchThread(self.directory)
        self.search_thread.result_found.connect(self.on_result_found)
        self.search_thread.error_occurred.connect(self.on_error)
        self.search_thread.progress_updated.connect(self.on_progress)
        self.search_thread.finished.connect(self.on_search_finished)
        self.search_thread.start()

    def cancel_search(self):
        if self.search_thread and self.search_thread.isRunning():
            self.search_thread.cancel()
            self.status_label.setText("Cancelling...")

    def on_result_found(self, result):
        self.result_text.append(result + "\n")

    def on_error(self, message):
        self.result_text.append(f"⚠ {message}\n")

    def on_progress(self, files_processed, matches_found):
        self.status_label.setText(
            f"Searched {files_processed} files — {matches_found} matches found"
        )

    def on_search_finished(self):
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)

        current = self.status_label.text()
        if self.search_thread and self.search_thread.cancelled:
            self.status_label.setText(f"Search cancelled. {current}")
        else:
            self.status_label.setText(f"Done. {current}")

    def copy_to_clipboard(self):
        clipboard = QApplication.clipboard()
        clipboard.setText(self.result_text.toPlainText())

    def darkStyleSheet(self):
        return """
        QWidget {
            background-color: #2b2b2b;
            color: #ffffff;
            border-radius: 10px;
        }
        QPushButton {
            background-color: #3c3f41;
            border: 2px solid #ff0000;
            border-radius: 10px;
            color: #ffffff;
            padding: 10px 20px;
            font-size: 14px;
        }
        QPushButton#closeButton {
            background-color: #ff0000;
            border: none;
            border-radius: 5px;
            color: #ffffff;
            padding: 5px 10px;
            font-size: 12px;
            font-weight: bold;
        }
        QPushButton#closeButton:hover {
            background-color: #ff5555;
        }
        QPushButton:hover {
            background-color: #505355;
        }
        QPushButton:disabled {
            background-color: #2d2d2d;
            border: 1px solid #555555;
            color: #555555;
        }
        QLabel {
            color: #ffffff;
            padding: 4px;
        }
        QLabel#statusLabel {
            color: #aaaaaa;
            font-size: 12px;
            padding: 2px 4px;
        }
        QLabel#copyLabel {
            color: #888888;
            font-size: 12px;
        }
        QTextEdit {
            background-color: #3c3f41;
            color: #ffffff;
            border: none;
            border-radius: 10px;
        }
        QScrollBar:vertical {
            width: 12px;
            background: #3c3f41;
            margin: 0;
            border-radius: 4px;
        }
        QScrollBar::handle:vertical {
            background: #ff0000;
            min-height: 20px;
            border-radius: 4px;
        }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            background: none;
            height: 12px;
            subcontrol-position: top;
            subcontrol-origin: margin;
        }
        """

    def mousePressEvent(self, event):
        self.drag_offset = event.pos()

    def mouseMoveEvent(self, event):
        if hasattr(self, 'drag_offset'):
            self.move(self.pos() + event.pos() - self.drag_offset)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = VectorSearchApp()
    window.show()
    sys.exit(app.exec_())
