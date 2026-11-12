#!/usr/bin/env python3
"""Greedy Vt assignment under a fixed clock period.

Every cell starts in the slowest flavour (SRAM). Two phases follow:

  1. Close timing. While setup is violated, take the cells on violating
     paths, try moving each one flavour faster, and score the move as
         timing gained / cost added
     where "timing gained" is the improvement in total negative slack. The
     best-scoring moves are accepted, a batch at a time.
  2. Recover. Phase 1 overshoots a little. Try moving each fast cell one
     flavour slower again, most expensive first, and keep the move whenever
     setup and hold are still met.

The cost is pluggable. This file provides the baseline cost, total leakage
power, which gives a conventional timing-driven assignment. The security cost
(key-dependent leakage signal) will be a second class with the same three
methods, so both methods run through exactly the same loop.

Run from the project root, after flow/synth_core.sh:

    python3 opt/vt_assign.py --period 300 --out results/vt/leakage_300ps.json

All times are in ps and leakage in pW.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "opt"))

from liberty_leakage import load_leakage  # noqa: E402
from sta import FLAVOURS, Sta             # noqa: E402

FASTER = dict(zip(FLAVOURS[:-1], FLAVOURS[1:]))   # SRAM -> RVT -> LVT -> SLVT
SLOWER = dict(zip(FLAVOURS[1:], FLAVOURS[:-1]))


class LeakageCost:
    """Baseline cost: total leakage power of the design.

    Each cell's leakage is taken as the plain average over the logic states
    its library entry lists. That treats all states as equally likely, which
    is an approximation; it can be replaced by state probabilities from
    simulation once the netlist evaluator exists.
    """

    name = "leakage"

    def __init__(self, table, cell: dict[str, str], flavour: dict[str, str]):
        self._mean = {
            c: {f: float(np.nanmean(table[c][f].leak)) for f in FLAVOURS}
            for c in set(cell.values())
        }
        self._cell = cell
        self._flavour = dict(flavour)

    def delta(self, inst: str, new_flavour: str) -> float:
        """Change in cost if this instance moved to new_flavour."""
        m = self._mean[self._cell[inst]]
        return m[new_flavour] - m[self._flavour[inst]]

    def commit(self, inst: str, new_flavour: str) -> None:
        self._flavour[inst] = new_flavour

    def total(self) -> float:
        return sum(self._mean[self._cell[i]][f] for i, f in self._flavour.items())


class Infeasible(RuntimeError):
    pass


def close_timing(sta: Sta, cost, batch_fraction: float, log) -> int:
    """Phase 1: speed cells up until setup is met. Returns the number of swaps."""
    swaps = 0
    while True:
        now = sta.summary()
        if now.wns >= 0.0:
            return swaps
        slack = sta.instance_slacks()
        candidates = [
            (inst, FASTER[f]) for inst, f in sta.flavour.items()
            if f in FASTER and slack[inst] < 0.0
        ]
        if not candidates:
            raise Infeasible(
                f"setup still violated (wns {now.wns:.1f} ps) with every cell on "
                "the violating paths already in the fastest flavour"
            )
        trials = sta.trial(candidates)

        def score(gain_of):
            scored = []
            for (inst, f), t in zip(candidates, trials):
                gain = gain_of(t)                 # > 0 means less violation
                if gain <= 0.0:
                    continue
                c = cost.delta(inst, f)
                # Moves that cost nothing (or reduce cost) rank above all others.
                key = (1, gain) if c <= 0.0 else (0, gain / c)
                scored.append((key, inst, f))
            return scored

        scored = score(lambda t: t.tns - now.tns)
        if not scored:
            # OpenSTA reports a total negative slack of exactly 0 once the
            # remaining violation is a small fraction of a ps, so no swap
            # appears to help. The worst slack still shows the improvement.
            scored = score(lambda t: t.wns - now.wns)
        if not scored:
            raise Infeasible(f"no single swap improves timing (wns {now.wns:.1f} ps)")

        scored.sort(reverse=True)
        take = max(1, int(len(scored) * batch_fraction))
        batch = {inst: f for _, inst, f in scored[:take]}
        sta.apply(batch)
        for inst, f in batch.items():
            cost.commit(inst, f)
        swaps += len(batch)
        log(f"  close: wns {now.wns:8.2f}  tns {now.tns:11.1f}  "
            f"candidates {len(candidates):5d}  accepted {len(batch):4d}")


def recover(sta: Sta, cost, max_passes: int, log) -> int:
    """Phase 2: slow cells back down where timing allows. Returns swaps kept."""
    kept_total = 0
    for p in range(max_passes):
        moves = []
        for inst, f in sta.flavour.items():
            if f in SLOWER:
                saving = -cost.delta(inst, SLOWER[f])
                if saving > 0.0:
                    moves.append((saving, inst, SLOWER[f]))
        moves.sort(reverse=True)                       # biggest saving first
        swaps = [(inst, f) for _, inst, f in moves]
        kept = sta.keep_if_met(swaps)
        n = 0
        for (inst, f), ok in zip(swaps, kept):
            if ok:
                cost.commit(inst, f)
                n += 1
        kept_total += n
        log(f"  recover pass {p + 1}: tried {len(swaps)}, kept {n}")
        if n == 0:
            break
    return kept_total


def sha256(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--period", type=float, required=True, help="clock period in ps")
    ap.add_argument("--out", required=True, help="result file (JSON)")
    ap.add_argument("--top", default="ascon_core")
    ap.add_argument("--netlist", default=None, help="default: build/<top>.v")
    ap.add_argument("--sdc", default=None, help="default: flow/<top>.sdc")
    ap.add_argument("--libdir", default="libs/asap7")
    ap.add_argument("--corner", default="TT")
    ap.add_argument("--batch-fraction", type=float, default=0.05,
                    help="share of the improving swaps accepted per step (default 0.05)")
    ap.add_argument("--recover-passes", type=int, default=4)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    netlist = args.netlist or f"build/{args.top}.v"
    sdc = args.sdc or f"flow/{args.top}.sdc"
    log = (lambda s: None) if args.quiet else (lambda s: print(s, flush=True))
    t_start = time.time()

    table = load_leakage(args.libdir, args.corner)
    with Sta(netlist, args.top, sdc, args.period, args.libdir, args.corner) as sta:
        sta.set_all("SRAM")
        cost = LeakageCost(table, sta.cell, sta.flavour)
        start = sta.summary()
        cost_start = cost.total()
        log(f"{args.top}: {len(sta.cell)} cells, period {args.period} ps, cost '{cost.name}'")
        log(f"  all-SRAM: wns {start.wns:.2f}  hold {start.hold:.2f}  cost {cost.total():.0f}")

        n_close = close_timing(sta, cost, args.batch_fraction, log)
        closed = sta.summary()
        cost_closed = cost.total()
        log(f"  timing closed after {n_close} swaps: wns {closed.wns:.2f}  cost {cost_closed:.0f}")

        n_recover = recover(sta, cost, args.recover_passes, log)
        final = sta.summary()
        assignment = dict(sorted(sta.flavour.items()))

    # Independent check: a fresh OpenSTA process, loaded only from the result.
    with Sta(netlist, args.top, sdc, args.period, args.libdir, args.corner) as check:
        check.apply(assignment)
        verified = check.summary()
    ok = verified.wns >= 0.0 and verified.hold >= 0.0

    counts = Counter(assignment.values())
    result = {
        "design": args.top,
        "netlist": netlist,
        "netlist_sha256": sha256(netlist),
        "sdc_sha256": sha256(sdc),
        "corner": args.corner,
        "clk_period_ps": args.period,
        "cost": cost.name,
        "batch_fraction": args.batch_fraction,
        "stats": {
            "cells": len(assignment),
            "flavour_counts": {f: counts.get(f, 0) for f in FLAVOURS},
            "cost_all_slowest": cost_start,
            "cost_after_close": cost_closed,
            "cost_final": cost.total(),
            "swaps_close": n_close,
            "swaps_recovered": n_recover,
            "wns_ps": verified.wns,
            "tns_ps": verified.tns,
            "hold_slack_ps": verified.hold,
            "timing_met": ok,
            "runtime_s": round(time.time() - t_start, 1),
        },
        "assignment": assignment,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1) + "\n", encoding="ascii", newline="\n")

    log(f"  final: wns {final.wns:.2f}  hold {final.hold:.2f}  cost {cost.total():.0f}")
    log(f"  flavours: " + "  ".join(f"{f} {counts.get(f, 0)}" for f in FLAVOURS))
    log(f"  verified in a fresh OpenSTA: wns {verified.wns:.2f}  hold {verified.hold:.2f}"
        f"  -> {'timing met' if ok else 'TIMING NOT MET'}")
    log(f"  wrote {out}  ({result['stats']['runtime_s']} s)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
