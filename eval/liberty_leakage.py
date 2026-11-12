"""Per-input-state leakage tables from the ASAP7 liberty files.

The libraries give each cell a list of ``leakage_power`` groups, one per logic
state, e.g. for NAND2xp5:

    leakage_power () {
      value : 54.7371;
      when : "(A * !B * Y)";
      related_pg_pin : VDD;
    }

This module turns those into one NumPy array per cell and Vt flavour, indexed
by the logic values of the cell's pins, so that the leakage of thousands of
simulated executions can be looked up in one vectorised step.

Conventions
-----------
* Only ``related_pg_pin : VDD`` groups are used (the VSS ones are all zero).
* The group without a ``when`` is the library's state-independent default; it
  is kept as ``default`` but never used for per-state lookups.
* ``pins`` is the sorted list of every pin named in the cell's ``when``
  conditions. This includes outputs (Y, QN): a flip-flop's leakage depends on
  its stored value, which is not a function of its inputs.
* State index: ``sum(value_of(pins[i]) << i)``, so pins[0] is the least
  significant bit.
* States the library does not list (e.g. NAND2 with A=1, B=1, Y=1, which
  cannot occur) are NaN, so a wrong net value shows up instead of hiding.
* Values are in the library's leakage unit (pW for ASAP7).

Usage
-----
    table = load_leakage("libs/asap7", corner="TT")
    nand = table["NAND2xp5"]["RVT"]
    nand.pins                      # ['A', 'B', 'Y']
    nand.leak[nand.index(A=1, B=0, Y=1)]   # 54.7371

Run ``python liberty_leakage.py libs/asap7`` for a self-check.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# Suffix on the cell name -> flavour name used everywhere else in the project.
VT_SUFFIX = {"SRAM": "SRAM", "R": "RVT", "L": "LVT", "SL": "SLVT"}
FLAVOURS = ("SRAM", "RVT", "LVT", "SLVT")  # slowest to fastest

_CELL_RE = re.compile(r"^\s*cell\s*\(\s*(\w+)\s*\)")
_NAME_RE = re.compile(r"^(\w+?)_ASAP7_75t_(SRAM|SL|R|L)$")
_VALUE_RE = re.compile(r"^\s*value\s*:\s*([-+0-9.eE]+)\s*;")
_WHEN_RE = re.compile(r'^\s*when\s*:\s*"(.*)"\s*;')
_PG_RE = re.compile(r"^\s*related_pg_pin\s*:\s*\"?(\w+)\"?\s*;")
_AREA_RE = re.compile(r"^\s*area\s*:\s*([-+0-9.eE]+)\s*;")
_LITERAL_RE = re.compile(r"^(!?)(\w+)$")


@dataclass
class CellLeakage:
    """Leakage of one cell in one Vt flavour."""

    cell: str                  # base name, e.g. "NAND2xp5"
    flavour: str               # "SRAM", "RVT", "LVT" or "SLVT"
    lib_cell: str              # full library name, e.g. "NAND2xp5_ASAP7_75t_R"
    area: float
    pins: list[str]            # pins[i] is bit i of the state index
    leak: np.ndarray           # shape (2 ** len(pins),), NaN where unlisted
    default: float             # the library's state-independent value

    def index(self, **values: int) -> int:
        """State index for one assignment, e.g. index(A=1, B=0, Y=1)."""
        return sum((int(values[p]) & 1) << i for i, p in enumerate(self.pins))

    @property
    def listed(self) -> np.ndarray:
        """Leakage values of the states the library lists."""
        return self.leak[~np.isnan(self.leak)]


@dataclass
class _RawCell:
    lib_cell: str
    area: float = float("nan")
    default: float = float("nan")
    states: list[tuple[dict[str, int], float]] = field(default_factory=list)


def _parse_when(expr: str, lib_cell: str) -> dict[str, int]:
    """Turn "(A * !B * Y)" into {"A": 1, "B": 0, "Y": 1}.

    ASAP7 only uses plain AND-of-literals conditions. Anything else raises,
    because silently mis-reading a condition would corrupt every result.
    """
    body = expr.strip()
    while body.startswith("(") and body.endswith(")"):
        body = body[1:-1].strip()
    assignment: dict[str, int] = {}
    for term in re.split(r"\s*[*&]\s*", body):
        m = _LITERAL_RE.match(term.strip())
        if not m:
            raise ValueError(f"{lib_cell}: unsupported 'when' condition {expr!r}")
        assignment[m.group(2)] = 0 if m.group(1) else 1
    return assignment


def _parse_file(path: Path) -> list[_RawCell]:
    """Read every cell's VDD leakage groups from one liberty file."""
    cells: list[_RawCell] = []
    cur: _RawCell | None = None
    in_group = False
    value = when = pg = None

    with open(path, "r", encoding="ascii", errors="replace") as fh:
        for line in fh:
            if in_group:
                if "}" in line:
                    in_group = False
                    if cur is not None and pg == "VDD" and value is not None:
                        if when is None:
                            cur.default = value
                        else:
                            cur.states.append((_parse_when(when, cur.lib_cell), value))
                    continue
                m = _VALUE_RE.match(line)
                if m:
                    value = float(m.group(1))
                    continue
                m = _WHEN_RE.match(line)
                if m:
                    when = m.group(1)
                    continue
                m = _PG_RE.match(line)
                if m:
                    pg = m.group(1)
                continue

            # Cheap substring tests first: the files are mostly timing tables.
            if "leakage_power ()" in line:
                in_group = True
                value = when = pg = None
            elif "cell" in line:
                m = _CELL_RE.match(line)
                if m:
                    cur = _RawCell(lib_cell=m.group(1))
                    cells.append(cur)
            elif cur is not None and cur.area != cur.area and "area" in line:
                m = _AREA_RE.match(line)
                if m:
                    cur.area = float(m.group(1))
    return cells


def _build(raw: _RawCell) -> CellLeakage | None:
    m = _NAME_RE.match(raw.lib_cell)
    if not m:
        return None
    pins = sorted({p for assignment, _ in raw.states for p in assignment})
    leak = np.full(1 << len(pins), np.nan)
    for assignment, value in raw.states:
        # A condition that omits a pin applies to both values of that pin.
        free = [i for i, p in enumerate(pins) if p not in assignment]
        base = sum(assignment[p] << i for i, p in enumerate(pins) if p in assignment)
        for combo in range(1 << len(free)):
            idx = base
            for k, i in enumerate(free):
                idx |= ((combo >> k) & 1) << i
            if not np.isnan(leak[idx]) and leak[idx] != value:
                raise ValueError(
                    f"{raw.lib_cell}: two different leakage values for state "
                    f"{dict((p, (idx >> i) & 1) for i, p in enumerate(pins))}"
                )
            leak[idx] = value
    return CellLeakage(
        cell=m.group(1),
        flavour=VT_SUFFIX[m.group(2)],
        lib_cell=raw.lib_cell,
        area=raw.area,
        pins=pins,
        leak=leak,
        default=raw.default,
    )


def load_leakage(lib_dir: str | Path, corner: str = "TT") -> dict[str, dict[str, CellLeakage]]:
    """Load every ASAP7 cell at one corner.

    Returns ``table[cell][flavour]``, e.g. ``table["NAND2xp5"]["LVT"]``.
    """
    lib_dir = Path(lib_dir)
    files = sorted(lib_dir.glob(f"asap7sc7p5t_*_{corner}_nldm_*.lib"))
    if not files:
        raise FileNotFoundError(f"no {corner} liberty files in {lib_dir}")
    table: dict[str, dict[str, CellLeakage]] = {}
    for path in files:
        for raw in _parse_file(path):
            entry = _build(raw)
            if entry is None:
                continue
            flavours = table.setdefault(entry.cell, {})
            if entry.flavour in flavours:
                raise ValueError(f"{entry.lib_cell} appears in more than one file")
            flavours[entry.flavour] = entry
    return table


def _self_check(lib_dir: str) -> None:
    """Checks against values read by hand from the library text."""
    table = load_leakage(lib_dir, "TT")
    print(f"TT: {len(table)} cells")

    nand = table["NAND2xp5"]["RVT"]
    expected = {(0, 0, 1): 27.102, (0, 1, 1): 50.3497, (1, 0, 1): 54.7371, (1, 1, 0): 66.3488}
    for (a, b, y), want in expected.items():
        got = nand.leak[nand.index(A=a, B=b, Y=y)]
        assert got == want, (a, b, y, got, want)
    assert np.isnan(nand.leak[nand.index(A=1, B=1, Y=1)])
    print("NAND2xp5 RVT: 4 states match the library text; impossible states are NaN")

    missing = [c for c, f in table.items() if set(f) != set(FLAVOURS)]
    print(f"cells missing a flavour: {missing or 'none'}")

    mismatched = [
        c for c, f in table.items()
        if len({tuple(e.pins) for e in f.values()}) > 1
        or len({e.area for e in f.values()}) > 1
    ]
    print(f"cells whose pins or area differ between flavours: {mismatched or 'none'}")

    for flavour in ("SRAM", "LVT", "SLVT"):
        ratios = [
            f[flavour].listed.mean() / f["RVT"].listed.mean()
            for f in table.values()
            if flavour in f and "RVT" in f and f["RVT"].listed.size
        ]
        print(f"median mean-leakage ratio {flavour}/RVT: {np.median(ratios):.3g}")


if __name__ == "__main__":
    _self_check(sys.argv[1] if len(sys.argv) > 1 else "libs/asap7")
