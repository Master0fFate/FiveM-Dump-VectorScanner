import sys
import os
import re
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QPushButton, QFileDialog, 
                             QLabel, QTextEdit, QHBoxLayout)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QCursor

class SearchThread(QThread):
    update_result = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, directory):
        super().__init__()
        self.directory = directory

    def run(self):
        # REGEX for vector3(3 coords) & vector4(4 coords)
        pattern3 = re.compile(r'vector3\(\s*-?\d+(\.\d+)?\s*,\s*-?\d+(\.\d+)?\s*,\s*-?\d+(\.\d+)?\s*\)')
        pattern4 = re.compile(r'vector4\(\s*-?\d+(\.\d+)?\s*,\s*-?\d+(\.\d+)?\s*,\s*-?\d+(\.\d+)?\s*,\s*-?\d+(\.\d+)?\s*\)')

        for root, dirs, files in os.walk(self.directory):
            for file in files:
                filePath = os.path.join(root, file)
                with open(filePath, 'r', encoding='utf-8', errors='ignore') as f:
                    for i, line in enumerate(f, 1):
                        if pattern3.search(line) or pattern4.search(line):
                            # Add a newline to insert a blank line between entries
                            result = f"{filePath} {i}\n{line.strip()}\n"
                            self.update_result.emit(result)

        self.finished.emit()

class VectorSearchApp(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()

    def initUI(self):
        self.setWindowFlag(Qt.FramelessWindowHint)
        
        self.layout = QVBoxLayout()
        self.setStyleSheet(self.styleSheet())  # Apply the stylesheet

        headerLayout = QHBoxLayout()

        self.titleLabel = QLabel("Vector Searcher by Master0fFate", self)
        headerLayout.addWidget(self.titleLabel)
        
        self.closeButton = QPushButton("X")
        self.closeButton.setObjectName("closeButton")
        self.closeButton.clicked.connect(self.closeApplication)
        headerLayout.addWidget(self.closeButton, alignment=Qt.AlignRight)
        
        self.layout.addLayout(headerLayout)

        self.label = QLabel("Select a directory and press Start to search.")
        self.layout.addWidget(self.label)

        self.directoryLabel = QLabel("No directory selected")
        self.layout.addWidget(self.directoryLabel)

        self.browseButton = QPushButton("Browse")
        self.browseButton.clicked.connect(self.browseDirectory)
        self.layout.addWidget(self.browseButton)

        self.startButton = QPushButton("Start")
        self.startButton.clicked.connect(self.startSearch)
        self.layout.addWidget(self.startButton)

        resultLayout = QVBoxLayout()

        self.resultText = QTextEdit()
        self.resultText.setReadOnly(True)
        resultLayout.addWidget(self.resultText)

        self.copyLabel = QLabel('<a href="#" style="color: lightgray;">Copy to Clipboard</a>')
        self.copyLabel.setAlignment(Qt.AlignRight)
        self.copyLabel.setObjectName("copyLabel")
        self.copyLabel.linkActivated.connect(self.copyToClipboard)
        self.copyLabel.setCursor(QCursor(Qt.PointingHandCursor))  # Set cursor to pointer
        resultLayout.addWidget(self.copyLabel, alignment=Qt.AlignRight)

        self.layout.addLayout(resultLayout)

        self.setLayout(self.layout)
        self.setWindowTitle('Vector Search Application')
        self.setGeometry(300, 300, 600, 450)  # Increased height for better UI fitting

    def browseDirectory(self):
        self.directory = QFileDialog.getExistingDirectory(self, "Select Directory")
        self.directoryLabel.setText(self.directory)

    def startSearch(self):
        if not hasattr(self, 'directory') or not self.directory:
            self.resultText.setText("Please select a directory first.")
            return

        self.startButton.setEnabled(False)

        self.searchThread = SearchThread(self.directory)
        self.searchThread.update_result.connect(self.updateResults)
        self.searchThread.finished.connect(self.searchFinished)
        self.searchThread.start()

    def updateResults(self, result):
        self.resultText.append(result + '\n')

    def searchFinished(self):
        self.startButton.setEnabled(True)

    def copyToClipboard(self):
        clipboard = QApplication.clipboard()
        clipboard.setText(self.resultText.toPlainText())

    def closeApplication(self):
        self.close()

    def styleSheet(self):
        return """
        QWidget {
            background-color: #2b2b2b;
            color: #ffffff;
            border-radius: 10px;
        }
        QLabel#titleLabel {
            color: #ffffff;
            padding: 8px;
            font-size: 16px;
            font-weight: bold;
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
            padding: 5px 10px;  /* Smaller padding */
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
        QLabel#copyLabel {
            color: #888888;
            font-size: 12px;
        }
        QLabel#copyLabel:hover {
            color: #dddddd;
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
        self.offset = event.pos()

    def mouseMoveEvent(self, event):
        if hasattr(self, 'offset'):
            self.move(self.pos() + event.pos() - self.offset)
            
if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = VectorSearchApp()
    ex.show()
    sys.exit(app.exec_())
