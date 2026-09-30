"""Bounded, deterministic text search for numeric vector3/vector4 literals."""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import sys
from typing import Callable, Iterator, TextIO

# Limit each candidate, not each line: minified multi-megabyte lines are supported.
MAX_BODY = 4096
MAX_GAP = 128
OVERLAP = len("vector3(") + MAX_GAP + MAX_BODY + 1
CANDIDATE = re.compile(
    rf"vector(?P<dimension>[34])\s{{0,{MAX_GAP}}}\((?P<body>[^()]{{0,{MAX_BODY}}})\)"
)
NUMBER = r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"
BODIES = {str(n): re.compile(r"\s*(" + NUMBER + r")" +
                            (r"\s*,\s*(" + NUMBER + r")") * (n - 1) + r"\s*\Z")
          for n in (3, 4)}
DEFAULT_EXCLUDES = frozenset({".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv"})


@dataclass(frozen=True)
class Match:
    path: str
    line: int
    column: int
    kind: str
    values: tuple[str, ...]
    text: str


@dataclass(frozen=True)
class ScanOptions:
    extensions: tuple[str, ...] = ()
    exclude_dirs: frozenset[str] = DEFAULT_EXCLUDES
    max_matches: int = 0
    chunk_size: int = 64 * 1024

    def __post_init__(self):
        if self.max_matches < 0:
            raise ValueError("max_matches must be zero (unlimited) or positive")
        if self.chunk_size < 1:
            raise ValueError("chunk_size must be positive")
        normalized = tuple(sorted({"." + ext.strip().lower().lstrip(".")
                                   for ext in self.extensions if ext.strip()}))
        object.__setattr__(self, "extensions", normalized)


@dataclass
class ScanStats:
    files: int = 0
    matches: int = 0
    errors: int = 0
    skipped_binary: int = 0
    cancelled: bool = False
    limit_reached: bool = False


def advance(line: int, column: int, text: str) -> tuple[int, int]:
    count = text.count("\n")
    return (line + count, len(text) - text.rfind("\n")) if count else (line, column + len(text))


def scan_stream(stream: TextIO, path: str = "", *, chunk_size: int = 64 * 1024,
                cancelled: Callable[[], bool] = lambda: False) -> Iterator[Match]:
    """Yield all literals in source order, including those spanning lines/chunks.

    UTF-8 text is a lexical search, not a Lua parser: comments and strings count.
    Numeric strings are preserved exactly; expressions and nonnumeric args do not.
    Working buffer is bounded by chunk_size + OVERLAP + one boundary character.
    """
    if chunk_size < 1:
        raise ValueError("chunk_size must be positive")
    buffer = ""
    line, column, first_start = 1, 1, 0
    while not cancelled():
        chunk = stream.read(chunk_size)
        eof = not chunk
        if "\0" in chunk:
            raise ValueError("NUL byte in text (binary or unsupported encoding)")
        buffer += chunk
        safe_end = len(buffer) + 1 if eof else max(0, len(buffer) - OVERLAP)
        if not safe_end:
            continue
        cursor, match_line, match_column = 0, line, column
        for candidate in CANDIDATE.finditer(buffer):
            if cancelled():
                return
            start = candidate.start()
            if start >= safe_end:
                break
            if start < first_start:
                continue
            if start and (buffer[start - 1].isalnum() or buffer[start - 1] in "_."):
                continue
            body_match = BODIES[candidate["dimension"]].fullmatch(candidate["body"])
            if body_match is None:
                continue
            values = body_match.groups()
            match_line, match_column = advance(match_line, match_column, buffer[cursor:start])
            cursor = start
            yield Match(path, match_line, match_column, "vector" + candidate["dimension"], values, candidate[0])
        if eof:
            break
        # Keep one preceding character so identifier boundaries survive chunking.
        discard = max(0, safe_end - 1)
        line, column = advance(line, column, buffer[:discard])
        buffer = buffer[discard:]
        first_start = safe_end - discard


def scan_directory(directory: str | Path, options: ScanOptions | None = None, *,
                   stats: ScanStats | None = None,
                   cancelled: Callable[[], bool] = lambda: False,
                   on_error: Callable[[str], None] = lambda message: None,
                   on_progress: Callable[[ScanStats], None] = lambda stats: None) -> Iterator[Match]:
    options = options or ScanOptions()
    stats = stats if stats is not None else ScanStats()
    root_path = Path(directory).resolve()
    if not root_path.is_dir():
        raise ValueError(f"Not a directory: {root_path}")

    def report(error):
        stats.errors += 1
        on_error(str(error))

    try:
        for root, dirs, files in os.walk(root_path, followlinks=False, onerror=report):
            if cancelled():
                break
            dirs[:] = sorted(name for name in dirs if name not in options.exclude_dirs
                             and not Path(root, name).is_symlink())
            for name in sorted(files):
                if cancelled():
                    break
                path = Path(root, name)
                try:
                    if path.is_symlink() or not path.is_file():
                        continue
                except OSError as error:
                    report(f"{path.relative_to(root_path).as_posix()}: {error}")
                    continue
                if options.extensions and path.suffix.lower() not in options.extensions:
                    continue
                stats.files += 1
                relative = path.relative_to(root_path).as_posix()
                try:
                    with path.open("rb") as probe:
                        if b"\0" in probe.read(4096):
                            stats.skipped_binary += 1
                            continue
                    with path.open("r", encoding="utf-8-sig", errors="strict", newline=None) as stream:
                        for match in scan_stream(stream, relative, chunk_size=options.chunk_size, cancelled=cancelled):
                            stats.matches += 1
                            yield match
                            if options.max_matches and stats.matches >= options.max_matches:
                                stats.limit_reached = True
                                return
                except (OSError, UnicodeError, ValueError) as error:
                    report(f"{relative}: {error}")
                finally:
                    on_progress(stats)
    finally:
        stats.cancelled = cancelled()
        on_progress(stats)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--extensions", default="", help="Comma-separated extensions; default: all files")
    parser.add_argument("--max-matches", type=int, default=0, help="Stop after N matches; 0 means unlimited")
    parser.add_argument("--include-generated", action="store_true", help="Also scan normally excluded directories")
    args = parser.parse_args(argv)
    stats = ScanStats()
    try:
        options = ScanOptions(tuple(args.extensions.split(",")),
                              frozenset() if args.include_generated else DEFAULT_EXCLUDES,
                              args.max_matches)
        for match in scan_directory(args.directory, options, stats=stats,
                                    on_error=lambda error: print(error, file=sys.stderr)):
            print(json.dumps(asdict(match), ensure_ascii=True))
    except (ValueError, OSError) as error:
        print(error, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Cancelled", file=sys.stderr)
        return 130
    print(json.dumps(asdict(stats)), file=sys.stderr)
    return 1 if stats.errors else 0


if __name__ == "__main__":
    sys.exit(main())
