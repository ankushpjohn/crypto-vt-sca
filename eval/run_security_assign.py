#!/usr/bin/env python3
"""Security-driven Vt assignment: opt/vt_assign.py's loop with SecurityCost.

Same two phases as the baseline (close timing from all-SRAM, then recover),
same OpenSTA driver, same result-file format, so baseline and security
results can be compared directly. Only the cost differs. opt/vt_assign.py is
imported, not modified.

    python3 eval/run_security_assign.py --period 300 --metric var \
        --out results/vt/security_var_300ps.json

The signal data used by the optimiser is built with --seed; the final scores
in the result file are computed on separate data (--eval-seed), so they are
not flattered by the optimiser fitting estimation noise.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "opt"))

from netlist_eval import Core                                  # noqa: E402
from scoring import SecurityCost, SignalData, score            # noqa: E402
from sta import FLAVOURS, Sta                                  # noqa: E402
from vt_assign import close_timing, recover, sha256            # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--period", type=float, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--metric", default="var", choices=("var", "key"))
    ap.add_argument("--estimator", default="plain", choices=("plain", "split"),
                    help="estimator the optimiser minimises (split is unbounded below; see scoring.py)")
    ap.add_argument("--leak-weight", type=float, default=0.0,
                    help="add this many cost units per pW of mean leakage (0 = signal only)")
    ap.add_argument("--groups", type=int, default=2)
    ap.add_argument("--nonces", type=int, default=4096)
    ap.add_argument("--seed", type=int, default=1, help="seed of the optimiser's data")
    ap.add_argument("--eval-seed", type=int, default=7, help="seed of the held-out data")
    ap.add_argument("--clk", type=int, default=0, choices=(0, 1))
    ap.add_argument("--inputs", default="hold", choices=("hold", "zero", "random"))
    ap.add_argument("--netlist", default="build/ascon_core.v")
    ap.add_argument("--sdc", default="flow/ascon_core.sdc")
    ap.add_argument("--libdir", default="libs/asap7")
    ap.add_argument("--corner", default="TT")
    ap.add_argument("--batch-fraction", type=float, default=0.05)
    ap.add_argument("--recover-passes", type=int, default=4)
    args = ap.parse_args()
    log = lambda s: print(s, flush=True)
    t_start = time.time()

    core = Core(args.netlist, libdir=args.libdir, corner=args.corner)
    train = SignalData(core, args.groups, args.nonces, args.seed, args.clk, args.inputs, log=log)

    with Sta(args.netlist, "ascon_core", args.sdc, args.period, args.libdir, args.corner) as sta:
        sta.set_all("SRAM")
        cost = SecurityCost(train, sta.flavour, args.metric, args.estimator, leak_weight=args.leak_weight)
        log(f"ascon_core: period {args.period} ps, cost '{cost.name}', "
            f"all-SRAM signal {cost.signal_pw2():.1f} pW^2")
        c0 = cost.total()
        n_close = close_timing(sta, cost, args.batch_fraction, log)
        c1 = cost.total()
        log(f"  timing closed after {n_close} swaps: signal {cost.signal_pw2():.1f} pW^2")
        n_rec = recover(sta, cost, args.recover_passes, log)
        assignment = dict(sorted(sta.flavour.items()))

    with Sta(args.netlist, "ascon_core", args.sdc, args.period, args.libdir, args.corner) as check:
        check.apply(assignment)
        verified = check.summary()
    ok = verified.wns >= 0.0 and verified.hold >= 0.0

    fidx = core.flavour_index(assignment)
    score_train = score(train, fidx)
    cost_name, c2 = cost.name, cost.total()
    del cost, train                                   # free memory before the held-out data
    held = SignalData(core, args.groups, args.nonces, args.eval_seed, args.clk, args.inputs, log=log)
    counts = Counter(assignment.values())
    result = {
        "design": "ascon_core",
        "netlist": args.netlist,
        "netlist_sha256": sha256(args.netlist),
        "sdc_sha256": sha256(args.sdc),
        "corner": args.corner,
        "clk_period_ps": args.period,
        "cost": cost_name,
        "batch_fraction": args.batch_fraction,
        "signal_settings": {"metric": args.metric, "estimator": args.estimator, "groups": args.groups, "nonces": args.nonces,
                            "seed": args.seed, "eval_seed": args.eval_seed, "clk": args.clk,
                            "inputs": args.inputs, "leak_weight": args.leak_weight},
        "stats": {
            "cells": len(assignment),
            "flavour_counts": {f: counts.get(f, 0) for f in FLAVOURS},
            "cost_all_slowest": c0, "cost_after_close": c1, "cost_final": c2,
            "swaps_close": n_close, "swaps_recovered": n_rec,
            "wns_ps": verified.wns, "tns_ps": verified.tns, "hold_slack_ps": verified.hold,
            "timing_met": ok, "runtime_s": round(time.time() - t_start, 1),
            "score_train": score_train, "score_heldout": score(held, fidx),
        },
        "assignment": assignment,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1) + "\n", encoding="ascii", newline="\n")
    s = result["stats"]["score_heldout"]
    log(f"  flavours: " + "  ".join(f"{f} {counts.get(f, 0)}" for f in FLAVOURS))
    log(f"  held-out: var {s['var']:.1f}  key {s['key']:.1f}  leak {s['leak_nw']:.1f} nW")
    log(f"  verified: wns {verified.wns:.2f}  hold {verified.hold:.2f} -> "
        f"{'timing met' if ok else 'TIMING NOT MET'};  wrote {out} ({result['stats']['runtime_s']} s)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
