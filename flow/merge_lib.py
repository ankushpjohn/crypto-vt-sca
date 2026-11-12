#!/usr/bin/env python3
"""Merge several liberty files into one.

ASAP7 splits its cells over several files (SIMPLE, INVBUF, AO, OA, SEQ), but
ABC inside Yosys takes a single liberty file. This keeps the header of the
first file (units, templates, operating conditions) and appends the cell
groups of all of them.

    flow/merge_lib.py OUT.lib IN1.lib IN2.lib ...
"""
import re
import sys

CELL_RE = re.compile(r"^\s*cell\s*\(")


def split(path):
    """Return (header lines, cell lines) of one liberty file."""
    with open(path, "r", encoding="ascii", errors="replace") as fh:
        lines = fh.readlines()
    first = next(i for i, line in enumerate(lines) if CELL_RE.match(line))
    # The last line holding only "}" closes the library group.
    last = max(i for i, line in enumerate(lines) if line.strip() == "}")
    return lines[:first], lines[first:last]


def main(out_path, in_paths):
    with open(out_path, "w", encoding="ascii", newline="\n") as out:
        for n, path in enumerate(in_paths):
            header, cells = split(path)
            if n == 0:
                out.writelines(header)
            out.writelines(cells)
        out.write("}\n")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2:])
