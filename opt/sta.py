"""Python driver for one long-running OpenSTA process.

OpenSTA takes several seconds to load the ASAP7 libraries, so the optimiser
keeps a single process alive and sends it commands over a pipe. The Tcl side
is opt/sta_server.tcl.

    with Sta("build/ascon_core.v", "ascon_core", "flow/ascon_core.sdc", 300.0) as sta:
        print(sta.summary())               # Timing(wns=..., tns=..., hold=...)
        sta.apply({"_2402_": "LVT"})

All times are in ps. Flavours are "SRAM", "RVT", "LVT", "SLVT".
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import NamedTuple

FLAVOURS = ("SRAM", "RVT", "LVT", "SLVT")          # slowest to fastest
SUFFIX = {"SRAM": "SRAM", "RVT": "R", "LVT": "L", "SLVT": "SL"}
_FLAVOUR_OF_SUFFIX = {v: k for k, v in SUFFIX.items()}
_NAME_RE = re.compile(r"^(\w+?)_ASAP7_75t_(SRAM|SL|R|L)$")

_SERVER = Path(__file__).with_name("sta_server.tcl")


def split_lib_cell(lib_cell: str) -> tuple[str, str]:
    """'NAND2xp33_ASAP7_75t_R' -> ('NAND2xp33', 'RVT')."""
    m = _NAME_RE.match(lib_cell)
    if not m:
        raise ValueError(f"not an ASAP7 cell name: {lib_cell}")
    return m.group(1), _FLAVOUR_OF_SUFFIX[m.group(2)]


def lib_cell(cell: str, flavour: str) -> str:
    """('NAND2xp33', 'RVT') -> 'NAND2xp33_ASAP7_75t_R'."""
    return f"{cell}_ASAP7_75t_{SUFFIX[flavour]}"


class Timing(NamedTuple):
    wns: float    # worst setup slack; >= 0 means setup is met
    tns: float    # total negative setup slack over all endpoints; 0 when met
    hold: float   # worst hold slack


class StaError(RuntimeError):
    pass


class Sta:
    """One OpenSTA process with a design loaded in all four Vt flavours."""

    def __init__(self, netlist, top, sdc, clk_period, libdir="libs/asap7", corner="TT"):
        self._proc = subprocess.Popen(
            ["sta", "-no_init", "-no_splash", str(_SERVER)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1,
        )
        self._cmd(f"vt_load {libdir} {corner} {netlist} {top} {sdc} {float(clk_period)}")
        # instance name -> base cell name (fixed) and current flavour.
        self.cell: dict[str, str] = {}
        self.flavour: dict[str, str] = {}
        words = self._cmd("vt_cells").split()
        for name, ref in zip(words[0::2], words[1::2]):
            self.cell[name], self.flavour[name] = split_lib_cell(ref)
        # OpenSTA reports a huge slack when nothing is constrained. Treating
        # that as "timing met" would make every result meaningless.
        if self.summary().wns > 1e20:
            raise StaError(f"no constrained timing paths in {top}; check {sdc}")

    # -- plumbing ----------------------------------------------------------

    def _cmd(self, line: str) -> str:
        """Send one Tcl command and return its result as text."""
        assert "\n" not in line
        self._proc.stdin.write(line + "\n")
        self._proc.stdin.flush()
        out = []
        while True:
            reply = self._proc.stdout.readline()
            if reply == "":
                raise StaError("OpenSTA exited unexpectedly:\n" + "".join(out))
            if reply.rstrip("\n") == "@@OK@@":
                return "".join(out).strip()
            if reply.rstrip("\n") == "@@ERR@@":
                raise StaError(f"{line[:80]} -> " + "".join(out).strip())
            out.append(reply)

    def close(self):
        if self._proc.poll() is None:
            try:
                self._proc.stdin.write("quit\n")
                self._proc.stdin.flush()
                self._proc.wait(timeout=10)
            except Exception:
                self._proc.kill()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- queries -----------------------------------------------------------

    def summary(self) -> Timing:
        return Timing(*map(float, self._cmd("vt_summary").split()))

    def instance_slacks(self) -> dict[str, float]:
        """Worst setup slack through each instance."""
        words = self._cmd("vt_inst_slacks").split()
        return {n: float(s) for n, s in zip(words[0::2], words[1::2])}

    def trial(self, swaps: list[tuple[str, str]]) -> list[Timing]:
        """Timing after each swap applied alone (and then undone).

        swaps is a list of (instance, new_flavour). The hold field of the
        result is not computed and is NaN.
        """
        if not swaps:
            return []
        args = " ".join(
            f"{n} {lib_cell(self.cell[n], f)} {lib_cell(self.cell[n], self.flavour[n])}"
            for n, f in swaps
        )
        v = list(map(float, self._cmd(f"vt_trial {{{args}}}").split()))
        return [Timing(w, t, float("nan")) for w, t in zip(v[0::2], v[1::2])]

    # -- changes -----------------------------------------------------------

    def apply(self, assignment: dict[str, str]) -> None:
        """Set the flavour of the given instances."""
        todo = {n: f for n, f in assignment.items() if self.flavour[n] != f}
        if not todo:
            return
        args = " ".join(f"{n} {lib_cell(self.cell[n], f)}" for n, f in todo.items())
        self._cmd(f"vt_apply {{{args}}}")
        self.flavour.update(todo)

    def set_all(self, flavour: str) -> None:
        self.apply({n: flavour for n in self.cell})

    def keep_if_met(self, swaps: list[tuple[str, str]]) -> list[bool]:
        """Apply swaps one after another, keeping each only if setup and hold
        are still met afterwards. Returns one flag per swap."""
        if not swaps:
            return []
        args = " ".join(
            f"{n} {lib_cell(self.cell[n], f)} {lib_cell(self.cell[n], self.flavour[n])}"
            for n, f in swaps
        )
        kept = [w == "1" for w in self._cmd(f"vt_keep_if_met {{{args}}}").split()]
        for (n, f), ok in zip(swaps, kept):
            if ok:
                self.flavour[n] = f
        return kept
