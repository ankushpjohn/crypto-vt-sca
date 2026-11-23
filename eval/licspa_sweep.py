#!/usr/bin/env python3
"""LiCSPA reimplemented in ASAP7: random configurations, timing closure, scores.

LiCSPA (ISCAS 2025, arXiv 2402.03196; reference [2] of the proposal) replaces
randomly chosen state-register flip-flops with a two-path primitive of LVT
flip-flops (rtl/licspa_core.v), optionally with randomised drive strengths,
and picks a configuration by sweeping random ones. For each configuration
this script

  1. draws `--bits` random state bits to protect and writes licspa_cfg.vh;
  2. synthesises it (flow/synth_licspa.sh) and finds the primitive flip-flops
     from their src attribute;
  3. optionally gives each primitive flip-flop a random size (DFFHQNx1/x2/x3);
  4. checks the netlist against the golden model with random ctl
     (eval/netlist_eval.py's self-check);
  5. pins the primitive flip-flops to LVT and gives every other cell a
     timing-driven Vt (opt/vt_assign.py's loop with the baseline cost),
     exactly like the baseline it is compared with;
  6. scores it on the same held-out data as every other design
     (eval/scoring.py: var, key, nonce, leakage) and records area and timing.

    python3 eval/licspa_sweep.py --period 300 --configs 8 --bits 24
    python3 eval/licspa_sweep.py --period 300 --configs 8 --bits 24 --drive random

Results: results/licspa/<tag>_cfg<r>.json per configuration (same format as
the other assignment files, plus "licspa": mask, primitives, sizes, netlist)
and results/licspa/<tag>_summary.json. The best configuration (lowest held-out
`var`) is what the paper's sweep would pick; report the mean as well.

--bits 24 gives about the paper's 6% area overhead in this flow.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "opt"))

from netlist_eval import Core, self_check                       # noqa: E402
from scoring import SignalData, score                           # noqa: E402
from sta import FLAVOURS, Sta                                   # noqa: E402
from vt_assign import LeakageCost, close_timing, recover, sha256  # noqa: E402

TOP = "licspa_core"
SDC = "flow/licspa_core.sdc"
RTL = "rtl/licspa_core.v"
_ATTR_INST = re.compile(r'\(\*\s*src\s*=\s*"([^"]*)"\s*\*\)\s*(\w+)\s+(\\?\S+)\s*\(')


class PinnedSta:
    """Sta wrapper that hides pinned instances from the optimiser loop.

    close_timing and recover only consider sta.flavour, so pinned cells are
    never swapped; everything else is passed through.
    """

    def __init__(self, sta: Sta, pinned):
        self._sta = sta
        self._pinned = set(pinned)

    @property
    def flavour(self):
        return {k: v for k, v in self._sta.flavour.items() if k not in self._pinned}

    def __getattr__(self, name):
        return getattr(self._sta, name)


def primitive_lines() -> set[str]:
    """Source lines of the two primitive flip-flops in rtl/licspa_core.v."""
    lines = set()
    for n, line in enumerate((ROOT / RTL).read_text().splitlines(), 1):
        if "LICSPA_FF_A" in line or "LICSPA_FF_B" in line:
            lines.add(str(n))
    if len(lines) != 2:
        raise ValueError(f"expected two LICSPA_FF markers in {RTL}")
    return lines


def find_primitives(attr_netlist: Path) -> list[str]:
    lines = primitive_lines()
    prims = []
    for src, cell, name in _ATTR_INST.findall(attr_netlist.read_text()):
        src_lines = {s.rsplit(":", 1)[-1].split(".")[0] for s in src.split("|")}
        if cell.startswith("DFF") and src_lines & lines:
            prims.append(name)
    return prims


def resize(netlist: Path, sizes: dict[str, str]) -> None:
    """Change the cell of the named flip-flops in place, e.g. to DFFHQNx3."""
    text = netlist.read_text()
    for inst, size in sizes.items():
        pat = re.compile(rf"^(\s*)DFFHQNx\d(_ASAP7_75t_R)\s+{re.escape(inst)}\s*\(", re.M)
        text, n = pat.subn(rf"\1DFFHQN{size}\2 {inst} (", text)
        if n != 1:
            raise ValueError(f"could not resize {inst}")
    netlist.write_text(text, encoding="ascii", newline="\n")


_AREA = {}


def cell_areas(lib="build/asap7_RVT_TT.lib") -> dict[str, float]:
    """Area of every cell (full RVT name) in the merged library.

    Read here rather than from eval/liberty_leakage.py, whose area regex needs a
    trailing ';' that the INVBUF library omits ("area : 0.20412"), so buffers
    and inverters get NaN there. Vt flavours share footprints, so RVT areas
    hold for every flavour.
    """
    if lib not in _AREA:
        text = (ROOT / lib).read_text(errors="replace")
        _AREA[lib] = {m.group(1): float(m.group(2)) for m in re.finditer(
            r"cell\s*\(\s*(\w+)\s*\)\s*\{\s*area\s*:\s*([-+0-9.eE]+)", text)}
    return _AREA[lib]


def area(core: Core) -> float:
    a = cell_areas()
    return float(sum(a[inst.lib_cell] for inst in core._insts))


def _show(path: Path) -> str:
    """Path relative to the project if it is inside it, else as given (e.g. /tmp/...)."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def run_config(args, r: int, rng, log) -> dict:
    tag = f"{args.tag}_cfg{r}"
    d = ROOT / "build" / "licspa" / tag
    d.mkdir(parents=True, exist_ok=True)
    bits = sorted(rng.choice(320, size=args.bits, replace=False).tolist())
    mask = sum(1 << b for b in bits)
    (d / "licspa_cfg.vh").write_text(f"`define LICSPA_MASK 320'h{mask:080x}\n", newline="\n")
    log(f"[{tag}] {args.bits} protected bits: {bits}")

    t0 = time.time()
    subprocess.run(["bash", "flow/synth_licspa.sh", str(d.relative_to(ROOT))], cwd=ROOT,
                   check=True, stdout=subprocess.DEVNULL)
    netlist = d / f"{TOP}.v"
    prims = find_primitives(d / f"{TOP}_attr.v")
    if len(prims) != 2 * args.bits:
        raise RuntimeError(f"[{tag}] found {len(prims)} primitive flip-flops, expected {2 * args.bits}")
    sizes = {}
    if args.drive == "random":
        sizes = {p: f"x{int(rng.integers(1, 4))}" for p in prims}
        resize(netlist, sizes)
    log(f"[{tag}] synthesised in {time.time() - t0:.0f} s; {len(prims)} primitive flip-flops")

    core = Core(netlist, random_ports=("ctl",))
    if not self_check(core, 300, args.seed + r):
        raise RuntimeError(f"[{tag}] netlist does not match the golden model")

    rel = str(netlist.relative_to(ROOT))
    with Sta(rel, TOP, SDC, args.period, args.libdir, args.corner) as sta:
        sta.set_all("SRAM")
        sta.apply({p: "LVT" for p in prims})
        cost = LeakageCost(core.table, sta.cell, sta.flavour)
        pinned = PinnedSta(sta, prims)
        n_close = close_timing(pinned, cost, args.batch_fraction, lambda s: None)
        n_rec = recover(pinned, cost, args.recover_passes, lambda s: None)
        assignment = dict(sorted(sta.flavour.items()))
    with Sta(rel, TOP, SDC, args.period, args.libdir, args.corner) as check:
        check.apply(assignment)
        t = check.summary()
    ok = t.wns >= 0.0 and t.hold >= 0.0

    held = SignalData(core, args.groups, args.nonces, args.eval_seed, log=lambda s: None)
    s = score(held, core.flavour_index(assignment))
    del held
    counts = Counter(assignment.values())
    result = {
        "design": TOP, "netlist": rel, "netlist_sha256": sha256(netlist), "sdc_sha256": sha256(ROOT / SDC),
        "corner": args.corner, "clk_period_ps": args.period, "cost": "leakage (LiCSPA primitives pinned LVT)",
        "batch_fraction": args.batch_fraction,
        "licspa": {"protected_bits": bits, "mask_hex": f"{mask:080x}", "primitives": prims,
                   "drive": args.drive, "sizes": sizes, "seed": args.seed, "config": r},
        "signal_settings": {"groups": args.groups, "nonces": args.nonces, "eval_seed": args.eval_seed,
                            "clk": 0, "inputs": "hold", "random_ports": ["ctl"]},
        "stats": {"cells": len(assignment), "area_um2": area(core),
                  "flavour_counts": {f: counts.get(f, 0) for f in FLAVOURS},
                  "swaps_close": n_close, "swaps_recovered": n_rec,
                  "wns_ps": t.wns, "tns_ps": t.tns, "hold_slack_ps": t.hold, "timing_met": ok,
                  "score_heldout": s, "runtime_s": round(time.time() - t0, 1)},
        "assignment": assignment,
    }
    out = ROOT / args.out_dir / f"{tag}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1) + "\n", encoding="ascii", newline="\n")
    log(f"[{tag}] area {result['stats']['area_um2']:.1f} um2, wns {t.wns:.2f}, hold {t.hold:.2f} "
        f"({'met' if ok else 'NOT MET'}); var {s['var']:.0f}, key {s['key']:.0f}, "
        f"leak {s['leak_nw']:.0f} nW; {result['stats']['runtime_s']} s -> {_show(out)}")
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--period", type=float, required=True)
    ap.add_argument("--configs", type=int, default=8, help="random configurations to try")
    ap.add_argument("--bits", type=int, default=24, help="protected state bits per configuration")
    ap.add_argument("--drive", default="fixed", choices=("fixed", "random"),
                    help="random: each primitive flip-flop gets DFFHQNx1/x2/x3 at random")
    ap.add_argument("--seed", type=int, default=2025)
    ap.add_argument("--eval-seed", type=int, default=7, help="same as the other designs' held-out data")
    ap.add_argument("--groups", type=int, default=2)
    ap.add_argument("--nonces", type=int, default=4096)
    ap.add_argument("--tag", default=None, help="default: licspa_<period>ps_<bits>b_<drive>")
    ap.add_argument("--out-dir", default="results/licspa")
    ap.add_argument("--libdir", default="libs/asap7")
    ap.add_argument("--corner", default="TT")
    ap.add_argument("--batch-fraction", type=float, default=0.05)
    ap.add_argument("--recover-passes", type=int, default=4)
    args = ap.parse_args()
    args.tag = args.tag or f"licspa_{args.period:g}ps_{args.bits}b_{args.drive}"
    log = lambda s: print(s, flush=True)

    rng = np.random.default_rng(args.seed)
    results = []
    for r in range(args.configs):
        try:
            results.append(run_config(args, r, rng, log))
        except Exception as e:                       # keep sweeping; report the failure
            log(f"[{args.tag}_cfg{r}] FAILED: {e}")
    good = [x for x in results if x["stats"]["timing_met"]]
    if not good:
        log("no configuration met timing")
        return 1
    v = np.array([x["stats"]["score_heldout"]["var"] for x in good])
    k = np.array([x["stats"]["score_heldout"]["key"] for x in good])
    best = good[int(v.argmin())]
    summary = {
        "settings": vars(args), "configs_met_timing": len(good), "configs_tried": args.configs,
        "var_mean": float(v.mean()), "var_min": float(v.min()), "var_max": float(v.max()),
        "key_mean": float(k.mean()), "key_min": float(k.min()), "key_max": float(k.max()),
        "area_mean_um2": float(np.mean([x["stats"]["area_um2"] for x in good])),
        "leak_mean_nw": float(np.mean([x["stats"]["score_heldout"]["leak_nw"] for x in good])),
        "best_config": best["licspa"]["config"],
        "best_file": f"{args.out_dir}/{args.tag}_cfg{best['licspa']['config']}.json",
    }
    path = ROOT / args.out_dir / f"{args.tag}_summary.json"
    path.write_text(json.dumps(summary, indent=1) + "\n", encoding="ascii", newline="\n")
    log(f"\n{len(good)}/{args.configs} met timing. var mean {v.mean():.0f} "
        f"(min {v.min():.0f}, max {v.max():.0f}); key mean {k.mean():.0f} (min {k.min():.0f}); "
        f"best: {summary['best_file']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
