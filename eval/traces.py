#!/usr/bin/env python3
"""Simulated static-power traces for one or more Vt assignments.

A static-power trace is one number per execution: the total leakage (pW) of
the core with the clock stopped at the attack point. For each experiment a
random key is fixed and the nonce varies, as for a real attacker. The traces
are noise-free; measurement noise is added by the attack (eval/cpa.py), so
the same file serves every noise level.

    python3 eval/traces.py --assign results/vt/leakage_300ps.json \
        results/vt/security_var_300ps.json --experiments 20 --traces 20000 \
        --out results/raw/traces_300ps.npz

Besides assignment files, --assign accepts all:SRAM, all:RVT, all:LVT, all:SLVT.
Output (npz): names, key0, key1 (E,), nonce0, nonce1 (E, N), traces (A, E, N)
in pW, and the settings including the seed.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "eval"))

from netlist_eval import Core, random_words                      # noqa: E402


def make_core(netlist="build/ascon_core.v", random_ports=None) -> Core:
    """Core for a netlist; LiCSPA's ctl port is randomised unless told otherwise."""
    if random_ports is None:
        from netlist_eval import read_netlist
        ports = read_netlist(Path(netlist))[0]
        random_ports = ["ctl"] if "ctl" in ports else []
    return Core(netlist, random_ports=random_ports)


def load_assignments(core: Core, specs: list[str]):
    names, fidx = [], []
    for s in specs:
        if s.startswith("all:"):
            f = s[4:]
            names.append(s)
            fidx.append(np.full(len(core.instances), core.flavours.index(f)))
        else:
            a = json.loads(Path(s).read_text())
            names.append(Path(s).stem)
            fidx.append(core.flavour_index(a["assignment"]))
    return names, fidx


def generate(core, fidx_list, experiments, traces, seed, clk=0, inputs="hold",
             point="primary", chunk=8192, log=print):
    rng = np.random.default_rng(seed)
    E, N, A = experiments, traces, len(fidx_list)
    key0, key1 = random_words(rng, E), random_words(rng, E)
    nonce0 = np.zeros((E, N), np.uint64)
    nonce1 = np.zeros((E, N), np.uint64)
    out = np.zeros((A, E, N))
    cols = np.arange(len(core.instances))
    t0 = time.time()
    for e in range(E):
        nonce0[e], nonce1[e] = random_words(rng, N), random_words(rng, N)
        for s in range(0, N, chunk):
            sl = slice(s, min(N, s + chunk))
            n = sl.stop - sl.start
            run = core.run(np.full(n, key0[e]), np.full(n, key1[e]), nonce0[e, sl], nonce1[e, sl],
                           clk_level=clk, inputs=inputs, secondary=(point == "secondary"),
                           seed=seed * 7919 + e * 131 + s)
            st = run.states if point == "primary" else core.states_of(run.nets_next)
            for a, fidx in enumerate(fidx_list):
                out[a, e, sl] = core.lut[fidx, cols, st].sum(axis=1)
        log(f"  experiment {e + 1}/{E} done ({time.time() - t0:.0f} s)")
    if np.isnan(out).any():
        raise ValueError("NaN leakage: a cell is in a state the library does not list")
    return key0, key1, nonce0, nonce1, out


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate static-power traces.")
    ap.add_argument("--assign", nargs="+", required=True)
    ap.add_argument("--experiments", type=int, default=20, help="number of random keys")
    ap.add_argument("--traces", type=int, default=20000, help="traces (nonces) per key")
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--clk", type=int, default=0, choices=(0, 1))
    ap.add_argument("--inputs", default="hold", choices=("hold", "zero", "random"))
    ap.add_argument("--point", default="primary", choices=("primary", "secondary"))
    ap.add_argument("--netlist", default="build/ascon_core.v",
                    help="e.g. build/licspa/<tag>/licspa_core.v for a LiCSPA design")
    ap.add_argument("--random-ports", nargs="*", default=None,
                    help="input ports randomised per execution (default: ctl if the netlist has it)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    core = make_core(args.netlist, args.random_ports)
    args.random_ports = list(core.random_ports)
    names, fidx = load_assignments(core, args.assign)
    k0, k1, n0, n1, tr = generate(core, fidx, args.experiments, args.traces, args.seed,
                                  args.clk, args.inputs, args.point)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.out, names=np.array(names), key0=k0, key1=k1, nonce0=n0, nonce1=n1,
                        traces=tr, settings=json.dumps(vars(args)))
    for a, name in enumerate(names):
        print(f"{name:28s} mean {tr[a].mean() / 1000:9.2f} nW   std within a key "
              f"{tr[a].std(axis=1).mean():8.2f} pW")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
