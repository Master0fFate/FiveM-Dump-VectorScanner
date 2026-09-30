"""Safe, offline smoke checks for the actual frozen desktop executable."""
import json
from pathlib import Path
import platform
import sys
import tempfile
import time
import traceback


def run(output_path):
    """Write a machine-readable result, then exit without opening a user window."""
    report = {"ok": False, "frozen": bool(getattr(sys, "frozen", False)),
              "python": platform.python_version(), "machine": platform.machine(),
              "platform": platform.platform()}
    window = None
    try:
        from PyQt5.QtWidgets import QApplication
        from VectorSearch import DISPLAY_LIMIT, VectorSearchApp
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory(prefix="vector-search-smoke-") as temporary:
            root = Path(temporary)
            fixture = root / "input"
            fixture.mkdir()
            (fixture / "sample.lua").write_text(
                "vector3(1,2,3)\n" * 2500 +
                "vector3(+1, .5, -3e-2)\nvector4(1,\n2, 3., 4E+1)\n"
                "myvector3(1,2,3)\nvector3(1,2,3,4)\n", encoding="utf-8")
            window = VectorSearchApp()
            window.directory = str(fixture)
            if window.max_matches.value() != 0:
                raise AssertionError("Default GUI scan must be unlimited")
            window.start_search()
            deadline = time.monotonic() + 60
            while window.search_thread is not None:
                app.processEvents()
                if time.monotonic() > deadline:
                    raise TimeoutError("Packaged scan did not finish within 60 seconds")
                time.sleep(0.005)
            if "Done: 1 files, 2502 vectors, 0 errors" not in window.status_label.text():
                raise AssertionError(window.status_label.text())
            if window.result_text.document().blockCount() != DISPLAY_LIMIT:
                raise AssertionError("Visible result buffer exceeded its configured limit")
            destination = root / "export.jsonl"
            if not window.save_results(destination):
                raise AssertionError(window.status_label.text())
            rows = [json.loads(line) for line in destination.read_text(encoding="utf-8").splitlines()]
            if len(rows) != 2502:
                raise AssertionError(f"Export lost results: {len(rows)}")
            if rows[-2]["values"] != ["+1", ".5", "-3e-2"]:
                raise AssertionError("Signed/scientific literals were not preserved")
            if rows[-1]["values"] != ["1", "2", "3.", "4E+1"] or rows[-1]["line"] != 2502:
                raise AssertionError("Multiline vector or location was incorrect")
            spool = window.result_file
            window.close()
            app.processEvents()
            if not spool.closed:
                raise AssertionError("Result spool remained open after close")
            window = None
            report.update(ok=True, exported_matches=len(rows), visible_limit=DISPLAY_LIMIT,
                          checks=["GUI startup", "unlimited scan", "bounded display", "full JSONL export",
                                  "signed and scientific numbers", "multiline vectors",
                                  "invalid literal rejection", "temporary result cleanup"])
    except Exception:
        report["error"] = traceback.format_exc()
        if window is not None and window.search_thread is not None:
            window.search_thread.cancel()
            window.search_thread.wait(5000)
            window.drain_events()
        if window is not None:
            window.close()
    Path(output_path).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if report["ok"] else 1
