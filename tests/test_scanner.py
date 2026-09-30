import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from vector_scanner import MAX_BODY, MAX_GAP, OVERLAP, ScanOptions, ScanStats, scan_directory, scan_stream


class StreamTests(unittest.TestCase):
    def scan(self, text, **kwargs):
        return list(scan_stream(io.StringIO(text), "fixture.lua", **kwargs))

    def test_numeric_forms_and_multiple_matches(self):
        result = self.scan("vector3(+1, -.5, 3.e+2) vector4(1E-4, 0, 42., +.7)")
        self.assertEqual([r.kind for r in result], ["vector3", "vector4"])
        self.assertEqual(result[0].values, ("+1", "-.5", "3.e+2"))
        self.assertEqual(result[1].values, ("1E-4", "0", "42.", "+.7"))

    def test_exact_arity_and_invalid_numbers(self):
        for text in ("vector3(1,2)", "vector3(1,2,3,4)", "vector4(1,2,3)",
                     "vector3(1,2,3,)", "vector3(1,2,NaN)", "vector3(1,2,Infinity)",
                     "vector3(1,2,x)", "vector3(1,2,3+4)", "vector3(1,2,1e)",
                     "vector3(1,2,.)", "vector3(١,2,3)"):
            with self.subTest(text=text):
                self.assertEqual(self.scan(text), [])

    def test_identifier_boundaries(self):
        text = "myvector3(1,2,3) _vector3(1,2,3) .vector3(1,2,3) vector30(1,2,3)"
        self.assertEqual(self.scan(text), [])
        self.assertEqual(len(self.scan("return vector3(1,2,3);[vector4(1,2,3,4)]")), 2)

    def test_multiline_line_and_column(self):
        rows = self.scan("α\n  vector3 (\n1, 2, 3\n)\nvector4(1,2,3,4)")
        self.assertEqual([(r.line, r.column) for r in rows], [(2, 3), (5, 1)])

    def test_comments_and_strings_are_deliberately_lexical(self):
        self.assertEqual(len(self.scan('-- vector3(1,2,3)\n"vector4(1,2,3,4)"')), 2)

    def test_chunk_boundaries_do_not_duplicate_or_lose_results(self):
        text = ("x" * 100 + " vector3(+1,.2,3e2)\n") * 100
        expected = self.scan(text)
        for size in (7, 31, 512, OVERLAP - 1, OVERLAP, OVERLAP + 1, 65536):
            with self.subTest(size=size):
                self.assertEqual(self.scan(text, chunk_size=size), expected)
        self.assertEqual(len(expected), 100)

    def test_rejected_identifier_at_retained_boundary(self):
        # Place a disallowed preceding character exactly at the discard boundary.
        size = 8192
        text = " " * (size - OVERLAP - 1) + "xvector3(1,2,3)" + " " * size
        self.assertEqual(self.scan(text, chunk_size=size), [])

    def test_minified_large_line_is_streamed(self):
        text = ("x" * 65536) + " vector3(1,2,3) " + ("x" * 65536)
        result = self.scan(text, chunk_size=1024)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].column, 65538)

    def test_candidate_size_limits(self):
        body = "1," + " " * (MAX_BODY - 5) + "2,3"
        self.assertEqual(len(body), MAX_BODY)
        self.assertEqual(len(self.scan("vector3(" + body + ")")), 1)
        self.assertEqual(self.scan("vector3(" + body + " )"), [])
        self.assertEqual(len(self.scan("vector3" + " " * MAX_GAP + "(1,2,3)")), 1)
        self.assertEqual(self.scan("vector3" + " " * (MAX_GAP + 1) + "(1,2,3)"), [])

    def test_cancel_before_read_and_between_matches(self):
        class NoRead(io.StringIO):
            def read(self, *args):
                raise AssertionError("read after cancellation")
        self.assertEqual(list(scan_stream(NoRead(), cancelled=lambda: True)), [])
        cancelled = False
        iterator = scan_stream(io.StringIO("vector3(1,2,3) " * 100), cancelled=lambda: cancelled)
        next(iterator)
        cancelled = True
        self.assertEqual(list(iterator), [])

    def test_nul_does_not_join_numeric_text(self):
        with self.assertRaises(ValueError):
            self.scan("vector3(1,2,3\0)")

    def test_invalid_chunk_size(self):
        with self.assertRaises(ValueError):
            self.scan("", chunk_size=0)


class DirectoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, name, content="vector3(1,2,3)"):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_deterministic_order_filters_and_excludes(self):
        for name in ("z.lua", "a.LUA", "sub/c.lua", "sub/a.lua", "b.txt", ".git/a.lua", "node_modules/b.lua"):
            self.write(name)
        matches = list(scan_directory(self.root, ScanOptions(extensions=(" lua ", ".LUA"))))
        self.assertEqual([m.path for m in matches], ["a.LUA", "z.lua", "sub/a.lua", "sub/c.lua"])

    def test_binary_bad_encoding_and_bom(self):
        (self.root / "binary.dat").write_bytes(b"\0vector3(1,2,3)")
        (self.root / "invalid.txt").write_bytes(b"vector3(1,2,\xff3)")
        (self.root / "bom.lua").write_bytes(b"\xef\xbb\xbfvector3(1,2,3)\r\nvector3(4,5,6)")
        stats, errors = ScanStats(), []
        result = list(scan_directory(self.root, stats=stats, on_error=errors.append))
        self.assertEqual([(m.path, m.line, m.column) for m in result], [("bom.lua", 1, 1), ("bom.lua", 2, 1)])
        self.assertEqual((stats.files, stats.skipped_binary, stats.errors), (3, 1, 1))
        self.assertIn("invalid.txt", errors[0])

    def test_match_limit(self):
        self.write("all.lua", "vector3(1,2,3) " * 10)
        stats = ScanStats()
        self.assertEqual(len(list(scan_directory(self.root, ScanOptions(max_matches=3), stats=stats))), 3)
        self.assertEqual(stats.matches, 3)
        self.assertTrue(stats.limit_reached)

    def test_symlinks_not_followed(self):
        target = self.write("source/a.lua")
        try:
            (self.root / "link.lua").symlink_to(target)
            (self.root / "loop").symlink_to(self.root, target_is_directory=True)
        except OSError:
            self.skipTest("symlink creation unavailable")
        self.assertEqual([m.path for m in scan_directory(self.root)], ["source/a.lua"])

    def test_unreadable_file_reported_and_other_files_continue(self):
        self.write("bad.lua")
        self.write("good.lua")
        original = Path.open
        def opened(path, *args, **kwargs):
            if path.name == "bad.lua":
                raise PermissionError("fixture permission denied")
            return original(path, *args, **kwargs)
        stats, errors = ScanStats(), []
        with patch.object(Path, "open", opened):
            result = list(scan_directory(self.root, stats=stats, on_error=errors.append))
        self.assertEqual([m.path for m in result], ["good.lua"])
        self.assertEqual(stats.errors, 1)
        self.assertIn("bad.lua", errors[0])

    def test_walk_error(self):
        def walk(*args, **kwargs):
            kwargs["onerror"](PermissionError("cannot enumerate"))
            return iter(())
        stats = ScanStats()
        with patch("vector_scanner.os.walk", walk):
            self.assertEqual(list(scan_directory(self.root, stats=stats)), [])
        self.assertEqual(stats.errors, 1)

    def test_cancelled_directory_and_missing_root(self):
        stats = ScanStats()
        self.write("a.lua")
        self.assertEqual(list(scan_directory(self.root, stats=stats, cancelled=lambda: True)), [])
        self.assertTrue(stats.cancelled)
        with self.assertRaises(ValueError):
            list(scan_directory(self.root / "missing"))

    def test_cli_jsonl_and_exit_status(self):
        self.write("a.lua")
        command = [sys.executable, "vector_scanner.py", str(self.root), "--extensions", "lua"]
        result = subprocess.run(command, text=True, capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout)["values"], ["1", "2", "3"])
        self.assertEqual(json.loads(result.stderr)["matches"], 1)
        result = subprocess.run(command + ["--max-matches", "-1"], text=True, capture_output=True)
        self.assertEqual(result.returncode, 2)

    def test_cli_decode_failure_exit_status(self):
        (self.root / "bad.txt").write_bytes(b"\xff")
        result = subprocess.run([sys.executable, "vector_scanner.py", str(self.root)], text=True, capture_output=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("bad.txt", result.stderr)


if __name__ == "__main__":
    unittest.main()
