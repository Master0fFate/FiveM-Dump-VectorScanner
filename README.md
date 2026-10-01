# Vector Search

Search **local text files you own or are authorized to inspect** for numeric `vector3` and `vector4` literals. Includes a PyQt5 desktop app and a dependency-free JSONL command-line scanner. It never connects to a game or server.

## Run

Python 3.10 or newer is required.

```sh
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
python VectorSearch.py
```

Choose a directory, optionally enter comma-separated extensions (`lua, js, txt`), and press **Start**. The default scan is unlimited; optionally choose a maximum number of vectors to stop early. **Cancel** stops between chunks/results. Closing the window requests cancellation and waits without blocking the event loop before releasing the worker.

The display retains the latest 1,000 result/error lines, and **Copy visible results** copies only those lines. **Export all results** saves every discovered match as JSONL after completion, an optional limit, or cancellation. Results stream into a temporary file rather than accumulating in memory; that file is closed and removed on a new scan or when the window closes. Export before starting another scan. Export writes a temporary destination and replaces the selected file only after the copy succeeds. Results are rendered as plain text, including filenames containing markup. A bounded queue applies backpressure so dense files cannot flood the GUI's event queue.

## CLI and complete exports

The CLI uses only the Python standard library; PyQt5 is not needed.

```sh
python vector_scanner.py ./my-sources --extensions lua,js --max-matches 0 > vectors.jsonl
```

One JSON object is emitted for every literal, including multiple literals on one line:

```json
{"path":"resources/spawn.lua","line":12,"column":5,"kind":"vector3","values":["+1",".5","3e-2"],"text":"vector3(+1,.5,3e-2)"}
```

Paths are relative, slash-separated, and results follow deterministic directory/file order and then source order. Line/column are one-based Unicode character positions; CRLF and CR newlines normalize to LF. Exact numeric spelling is preserved rather than rounded through floating point.

A summary and readable errors go to stderr. Exit codes are 0 for completion (including an explicitly requested match limit), 1 if some files/directories could not be read, 2 for invalid input, and 130 for Ctrl+C. Redirect stdout to a file **outside the scanned directory** so the export does not become scan input. A scan with errors may contain partial results.

## Search rules and limits

- Handles signed integers, decimals (`.5`, `1.`), scientific notation (`-1.2e+3`), spaces between the name and `(`, multiline literals, and exact 3/4 argument counts
- Rejects embedded identifiers such as `myvector3`, dotted names such as `object.vector3`, nonnumeric arguments, and arithmetic expressions
- This is a **lexical text search**, not a language parser. Literals inside comments and quoted strings are intentionally included; uppercase names and aliases are not matched
- UTF-8 and UTF-8 with BOM are supported. Invalid UTF-8 is reported rather than silently discarded. Files with NUL in the initial probe are counted as binary skips; NUL discovered later is a reported error. UTF-16/legacy encodings are not decoded automatically
- File and directory symlinks are skipped. `.git`, `.hg`, `.svn`, `node_modules`, `__pycache__`, `.venv`, and `venv` directories are excluded by default. Use `--include-generated` or the GUI checkbox to include them
- Input is read in 64K-character chunks, independent of line length. Candidates allow at most 128 whitespace characters before `(` and 4,096 characters inside parentheses; longer candidates are not matched. These limits keep the overlap buffer bounded even for minified or malformed files
- Memory is bounded with respect to file length and total match count when consuming the iterator without retaining results. Directory enumeration still uses memory proportional to entries in each visited directory; a single directory containing millions of files remains expensive
- Cancellation cannot interrupt an operating-system read already blocked on a slow filesystem. Results still queued when cancelling may be omitted from the visible GUI, and the status says so. The export retains matches already written to the result spool. Temporary disk usage grows with the number of matches; disk-write failures are reported as scan errors

## Tests

```sh
python -m unittest discover -s tests -v
python -m compileall -q VectorSearch.py vector_scanner.py tests benchmarks
```

Install `requirements.txt` to run all GUI tests; otherwise those tests are explicitly skipped. GUI tests use Qt's offscreen platform and exercise repeated starts, copy/plain-text output, display caps, complete exports beyond the display cap, atomic export failure, temporary-file cleanup, error recovery, cancellation with a full queue, and close-during-scan. Core tests cover parsing, chunk boundaries, multiline coordinates, huge lines, symlinks, invalid encoding, deterministic filters, permission errors, CLI behavior, and limits. CI runs on Linux and Windows with Python 3.10, 3.12 and 3.14.7.

## Reproducible benchmark

```sh
python benchmarks/benchmark.py --mib 32 --repeat 3
```

The benchmark generates its own fixtures, compares the original two-regex line scanner with the current streaming scanner, checks result counts, times three runs, and measures Python allocation peaks separately with `tracemalloc`. It excludes Qt, result rendering, traversal, and fixture generation. Both fixtures deliberately give the same count under old and new semantics.

Recorded in [benchmarks/results-linux-python312.json](benchmarks/results-linux-python312.json), on Linux / Python 3.12.14:

| Fixture | Original median | Streaming median | Original peak | Streaming peak |
|---|---:|---:|---:|---:|
| 32 MiB single line, one vector | 0.0510 s | 0.0415 s | 64.20 MiB | 267.12 KiB |
| 50,000 short lines, one vector each | 0.0595 s | 0.1396 s | 22.49 KiB | 335.94 KiB |

The large-line case uses roughly **246× less peak Python memory**. Dense-match parsing is slower because the new engine validates the expanded numeric syntax and creates a structured record for every match. This is a bounded-memory/correctness improvement, not a claim of universal speedup; filesystem and machine timings vary. The GUI separately avoids one Qt signal and one widget append per match by batching results and limiting retained text.

## Windows executable builds

After the Linux/Windows test matrix passes on a push to `main`, CI builds a standalone **Windows x64** `VectorSearch.exe` with Python 3.14.7 and PyInstaller. The executable name matches earlier release assets; no separate Python installation is needed. The build is unsigned, so Windows may show a publisher/SmartScreen warning.

Before uploading the artifact, CI launches the **actual executable** in both Qt's offscreen mode and the native Windows backend. It scans 2,502 synthetic matches, validates signed/scientific and multiline parsing, verifies the 1,000-line display bound, exports all matches, and checks temporary-file cleanup. The artifact contains the executable, its SHA-256 checksum, source-commit/build provenance, and the smoke-test report. Offscreen testing does not replace interactive testing on every Windows version; Windows 10/11 x64 is the intended desktop target.

To reproduce on Windows with Python 3.14.7 x64:

```sh
python -m pip install -r requirements.txt -r requirements-build.txt
python -m PyInstaller --noconfirm --clean VectorSearch.spec
```

`VectorSearch.exe --smoke-test <report.json>` runs the offline packaging check instead of the normal GUI. CI tests `QT_QPA_PLATFORM=offscreen` and `QT_QPA_PLATFORM=windows`, verifying both the exit code and report before preserving release files. Building an artifact does not automatically publish a GitHub Release.

The checked-in packaging spec excludes unused QML/Quick/network/DBus/WebSockets DLLs, the optional WebGL/TUIO/Linux portal plugins, and unused Qt translation catalogs. Windows/offscreen platform support, the Windows widget style, image/icon plugins, and QtGui graphics fallbacks are retained. Native Windows rendering and full export are tested against the final executable.
