"""Reproduce scanner timing and Python peak-memory measurements without GUI/I/O output."""
import argparse
import gc
import io
import json
from pathlib import Path
import platform
import re
import statistics
import sys
import tempfile
import time
import tracemalloc

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vector_scanner import scan_stream

LEGACY = [re.compile(r'vector3\(\s*-?\d+(\.\d+)?\s*,\s*-?\d+(\.\d+)?\s*,\s*-?\d+(\.\d+)?\s*\)'),
          re.compile(r'vector4\(\s*-?\d+(\.\d+)?\s*,\s*-?\d+(\.\d+)?\s*,\s*-?\d+(\.\d+)?\s*,\s*-?\d+(\.\d+)?\s*\)')]


def legacy(stream):
    return sum(any(pattern.search(line) for pattern in LEGACY) for line in stream)


def current(stream):
    return sum(1 for _ in scan_stream(stream))


def measure(path, function, repeat):
    timings = []
    for _ in range(repeat):
        with path.open(encoding="utf-8") as stream:
            start = time.perf_counter()
            count = function(stream)
            timings.append(time.perf_counter() - start)
    gc.collect()
    tracemalloc.start()
    with path.open(encoding="utf-8") as stream:
        assert function(stream) == count
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {"matches": count, "median_seconds": round(statistics.median(timings), 6),
            "python_peak_bytes": peak}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mib", type=int, default=32)
    parser.add_argument("--repeat", type=int, default=3)
    args = parser.parse_args()
    if args.mib <= 0 or args.repeat <= 0:
        parser.error("mib and repeat must be positive")
    report = {"python": sys.version.split()[0], "platform": platform.platform(),
              "mib": args.mib, "repeat": args.repeat, "scenarios": {}}
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        giant = root / "one-long-line.lua"
        with giant.open("w", encoding="utf-8", newline="\n") as stream:
            for _ in range(args.mib * 16):
                stream.write("x" * 65536)
            stream.write(" vector3(1,2,3)")
        dense = root / "dense.lua"
        with dense.open("w", encoding="utf-8", newline="\n") as stream:
            for _ in range(50000):
                stream.write("vector3(1,2,3)\n")
        for path, expected in ((giant, 1), (dense, 50000)):
            rows = {"size_bytes": path.stat().st_size,
                    "legacy": measure(path, legacy, args.repeat),
                    "current": measure(path, current, args.repeat)}
            assert rows["legacy"]["matches"] == rows["current"]["matches"] == expected
            report["scenarios"][path.name] = rows
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
