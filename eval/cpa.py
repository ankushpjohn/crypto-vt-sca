#!/usr/bin/env python3
"""Correlation power analysis on simulated static-power traces.

Target: S-box column j in round 1. Its inputs are IV bit j (known),
key0[j], key1[j] (the 2-bit secret, 4 hypotheses) and nonce0[j], nonce1[j]
(known). For every hypothesis the model predicts a value from the S-box
output; the hypothesis whose prediction correlates best with the traces wins.
The key is recovered when all 64 columns are right (128 bits).

Models (--model):
  hw      Hamming weight of the 5-bit S-box output, rank by |rho|   (standard)
  hw+     same, rank by rho (assumes leakage grows with HW; one known-key
          device tells the attacker the sign)
  profiled  the model is learned on a profiling device with known keys: for
          column j, M_j(kc, c) = mean trace with key class kc and nonce
          class c (eval/scoring.SignalData, its own seed). Prediction of
          hypothesis h = M_j(h, c). Rank by rho. This is the model a capable
          attacker would use; the HW model fails on these circuits (its
          success stays near chance, 25% per column).
  distance  same profiled model, but instead of correlation the score is the
          squared distance between the observed class means (centred) and
          the predicted ones (centred), smallest wins. Correlation ignores
          the scale of the prediction, so two hypotheses whose predictions
          have the same shape stay confused for ever (per-column success
          plateaus near 0.86); the distance does not have that blind spot.
Measurement noise: Gaussian, standard deviation --noise pW, added here so one
trace file serves every noise level. Seeded (--seed).

Output: success rate against the number of traces, per column (mean over
columns and experiments) and for the full key; the number of traces needed
for each success level in --levels, with a 90% bootstrap confidence interval
over experiments (keys); and the SNR per column (proposal's metric):
Var over nonce classes of the class-mean trace / mean within-class variance,
key fixed, averaged over experiments. Ratios between assignments are the
project's claim.

    python3 eval/cpa.py results/raw/traces_300ps.npz --noise 0 1 5
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "model"))
sys.path.insert(0, str(ROOT / "eval"))

from ascon_ref import IV                       # noqa: E402
from netlist_eval import words_to_bits         # noqa: E402

# Ascon S-box (NIST SP 800-232), input x0..x4 = bits 4..0.
SBOX = np.array([0x04, 0x0b, 0x1f, 0x14, 0x1a, 0x15, 0x09, 0x02, 0x1b, 0x05, 0x08, 0x12,
                 0x1d, 0x03, 0x06, 0x1c, 0x1e, 0x13, 0x07, 0x0e, 0x00, 0x0d, 0x11, 0x18,
                 0x10, 0x0c, 0x01, 0x19, 0x16, 0x0a, 0x0f, 0x17])
HW = np.array([bin(v).count("1") for v in range(32)], dtype=float)
IV_BITS = np.array([(IV >> j) & 1 for j in range(64)])


def predictions(nonce0, nonce1, model="hw", profile=None):
    """(4 hypotheses, N, 64) predicted leakage per column."""
    nc = 2 * words_to_bits(nonce0).astype(int) + words_to_bits(nonce1)       # (N, 64)
    if model == "profiled":
        j = np.arange(64)[None, None, :]
        return profile[j, np.arange(4)[:, None, None], nc[None]]           # M[j, h, c]
    h = np.arange(4)[:, None, None]
    x = (IV_BITS[None, None, :] << 4) | (h << 2) | nc[None]
    if model in ("hw", "hw+"):
        return HW[SBOX[x]]
    raise ValueError(model)


def true_hyp(key0, key1):
    return 2 * words_to_bits(np.array([key0], np.uint64))[0].astype(int) + \
        words_to_bits(np.array([key1], np.uint64))[0]                        # (64,)


def cpa_curve(t, P, grid, signed, chunk=16384):
    """Correlations for every hypothesis and column at each trace count in grid.

    t (N,), P: function (lo, hi) -> predictions (4, hi-lo, 64) for those traces.
    Streams over the traces in chunks, so N can be large.
    Returns rho (len(grid), 4, 64).
    """
    grid = list(grid)
    out = np.zeros((len(grid), 4, 64))
    st = st2 = 0.0
    sp = np.zeros((4, 64)); sp2 = np.zeros((4, 64)); spt = np.zeros((4, 64))
    g = 0
    lo = 0
    N = len(t)
    while g < len(grid):
        hi = min(N, lo + chunk, grid[g])        # stop exactly at the next grid point
        tt = t[lo:hi]
        pp = P(lo, hi)
        st += tt.sum(); st2 += (tt * tt).sum()
        sp += pp.sum(axis=1); sp2 += (pp * pp).sum(axis=1)
        spt += np.einsum("hnj,n->hj", pp, tt)
        lo = hi
        while g < len(grid) and grid[g] == lo:
            n = float(lo)
            cov = spt - sp * st / n
            vp = np.maximum(sp2 - sp * sp / n, 1e-30)
            vt = max(st2 - st * st / n, 1e-30)
            out[g] = cov / np.sqrt(vp * vt)
            g += 1
    return out if signed else np.abs(out)


def learn_profile(core, fidx, groups, nonces, seed, clk, inputs, point):
    """M (64, 4 key classes, 4 nonce classes): mean leakage on a profiling device
    (same netlist and assignment as the attacked one, its own random keys)."""
    from scoring import SignalData
    data = SignalData(core, groups, nonces, seed, clk, inputs, point, log=lambda s: None)
    S = data.S(fidx).mean(axis=0)                                    # (K, 64, 4)
    M = np.zeros((64, 4, 4))
    for kc in range(4):
        sel = (data.key_class == kc)                                 # (K, 64)
        M[:, kc, :] = (S * sel[:, :, None]).sum(axis=0) / sel.sum(axis=0)[:, None]
    return M


def _class_sums(nc, values):
    """Per column j and nonce class c: sum of values over traces with class c.

    nc (n, 64) int, values (n,) -> (64, 4). Same as np.add.at(out, (cols, nc),
    values[:, None]) but uses np.bincount, which is fast on every NumPy version
    (np.add.at is about 50x slower before NumPy 1.25).
    """
    idx = (np.arange(64)[None, :] * 4 + nc).ravel()
    w = np.repeat(values, 64)
    return np.bincount(idx, weights=w, minlength=256).reshape(64, 4)


def distance_curve(t, nc_of, profile, grid, chunk=16384):
    """Score (len(grid), 4, 64): minus the squared distance between centred
    observed class means and centred predicted class means (larger is better)."""
    grid = list(grid)
    out = np.zeros((len(grid), 4, 64))
    cnt = np.zeros((64, 4)); sm = np.zeros((64, 4))
    pred = profile - profile.mean(axis=2, keepdims=True)              # (64, h, c)
    g, lo, N = 0, 0, len(t)
    cols = np.arange(64)[None, :]
    while g < len(grid):
        hi = min(N, lo + chunk, grid[g])
        nc = nc_of(lo, hi)                                             # (n, 64)
        tt = t[lo:hi]
        cnt += _class_sums(nc, np.ones(len(tt)))
        sm += _class_sums(nc, tt)
        lo = hi
        while g < len(grid) and grid[g] == lo:
            mean_c = sm / np.maximum(cnt, 1)
            w = cnt / cnt.sum(axis=1, keepdims=True)
            obs = mean_c - (w * mean_c).sum(axis=1, keepdims=True)     # (64, c)
            d = ((obs[:, None, :] - pred) ** 2 * w[:, None, :]).sum(axis=2)   # (64, h)
            out[g] = -d.T
            g += 1
    return out


def attack(traces, key0, key1, nonce0, nonce1, noise, grid, model, rng, profile=None):
    """Success flags: per column (E, G, 64) for one assignment's traces (E, N)."""
    E = traces.shape[0]
    ok = np.zeros((E, len(grid), 64), bool)
    for e in range(E):
        t = traces[e] + (rng.normal(0.0, noise, traces.shape[1]) if noise > 0 else 0.0)
        if model == "distance":
            nc_of = lambda lo, hi, e=e: 2 * words_to_bits(nonce0[e, lo:hi]).astype(int) + \
                words_to_bits(nonce1[e, lo:hi])
            rho = distance_curve(t, nc_of, profile, grid)
        else:
            P = lambda lo, hi, e=e: predictions(nonce0[e, lo:hi], nonce1[e, lo:hi], model, profile)
            rho = cpa_curve(t, P, grid, signed=(model != "hw"))
        best = rho.argmax(axis=1)                                 # (G, 64)
        ok[e] = best == true_hyp(key0[e], key1[e])[None, :]
    return ok


def snr_per_column(traces, nonce0, nonce1, noise, rng):
    """SNR of each S-box column's nonce class (key fixed), mean over experiments: (64,)."""
    out = []
    for e in range(traces.shape[0]):
        t = traces[e] + (rng.normal(0.0, noise, traces.shape[1]) if noise > 0 else 0.0)
        nc = 2 * words_to_bits(nonce0[e]).astype(int) + words_to_bits(nonce1[e])   # (N, 64)
        cnt = np.zeros((64, 4)); sm = np.zeros((64, 4)); sq = np.zeros((64, 4))
        cols = np.arange(64)[None, :]
        cnt += _class_sums(nc, np.ones(len(t)))
        sm += _class_sums(nc, t)
        sq += _class_sums(nc, t * t)
        mean = sm / cnt
        var = sq / cnt - mean ** 2
        # variance of the class means, minus the part due to their own estimation noise
        sig = mean.var(axis=1) - (var / cnt).mean(axis=1)
        out.append(sig / var.mean(axis=1))
    return np.mean(out, axis=0)


def bootstrap_n(ok, grid, level, reps=500, seed=0):
    """90% interval of the trace count for a per-column success level,
    resampling experiments (keys) with replacement. None = not reached."""
    rng = np.random.default_rng(seed)
    E = ok.shape[0]
    vals = []
    for _ in range(reps):
        sr = ok[rng.integers(0, E, E)].mean(axis=(0, 2))
        n = traces_for(sr, grid, level)
        vals.append(np.inf if n is None else n)
    vals = np.sort(vals)                       # inf (not reached) sorts last
    lo, hi = vals[int(0.05 * (reps - 1))], vals[int(np.ceil(0.95 * (reps - 1)))]
    f = lambda v: None if np.isinf(v) else int(v)
    return f(lo), f(hi)


def traces_for(sr, grid, level=0.9):
    for n, s in zip(grid, sr):
        if s >= level:
            return int(n)
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="CPA on simulated static-power traces.")
    ap.add_argument("tracefile")
    ap.add_argument("--noise", type=float, nargs="+", default=[0.0], help="noise std in pW")
    ap.add_argument("--model", default="hw", choices=("hw", "hw+", "profiled", "distance"))
    ap.add_argument("--profile-seed", type=int, default=31, help="seed of the profiling data")
    ap.add_argument("--profile-groups", type=int, default=2)
    ap.add_argument("--profile-nonces", type=int, default=131072,
                    help="nonces per profiling key. Too small a profile is noisy and penalises "
                         "low-signal designs most (4096 inflated the 300 ps ratio from 28x to "
                         "150x); results were stable from 32768 to 131072.")
    ap.add_argument("--points", type=int, default=40, help="trace counts evaluated (log-spaced)")
    ap.add_argument("--seed", type=int, default=99)
    ap.add_argument("--levels", type=float, nargs="+", default=[0.5, 0.8, 0.9],
                    help="per-column success rates to report the trace count for")
    ap.add_argument("--json", help="write the curves here")
    ap.add_argument("--bootstrap", type=int, default=500, help="bootstrap resamples (0 = off)")
    args = ap.parse_args()

    d = np.load(args.tracefile)
    names = list(d["names"])
    tr = d["traces"]
    A, E, N = tr.shape
    grid = np.unique(np.geomspace(10, N, args.points).astype(int))
    report = {"settings": vars(args), "grid": grid.tolist(), "results": {}}
    print(f"{E} experiments (keys) x {N} traces, model {args.model}")
    profiles = [None] * A
    if args.model in ("profiled", "distance"):
        from traces import load_assignments, make_core
        st = json.loads(str(d["settings"]))
        core = make_core(st.get("netlist", "build/ascon_core.v"), st.get("random_ports"))
        _, fidxs = load_assignments(core, st["assign"])
        profiles = [learn_profile(core, f, args.profile_groups, args.profile_nonces,
                                  args.profile_seed, st["clk"], st["inputs"], st["point"])
                    for f in fidxs]
    for noise in args.noise:
        print(f"\nnoise {noise} pW")
        hdr = "".join(f"{'N@' + format(l, 'g'):>10s}" for l in args.levels)
        print(f"  {'assignment':28s} {'SNR':>9s} {'col SR@N':>9s} {'key SR@N':>9s}{hdr} {'N90 key':>9s}")
        for a, name in enumerate(names):
            rng = np.random.default_rng(args.seed)          # same noise for every assignment
            ok = attack(tr[a], d["key0"], d["key1"], d["nonce0"], d["nonce1"],
                        noise, grid, args.model, rng, profiles[a])
            col_sr = ok.mean(axis=(0, 2))                    # per-column success
            key_sr = ok.all(axis=2).mean(axis=0)             # all 64 columns right
            n_lv = {l: traces_for(col_sr, grid, l) for l in args.levels}
            n_key = traces_for(key_sr, grid)
            fmt = lambda v: f">{N}" if v is None else str(v)
            cols = "".join(f"{fmt(n_lv[l]):>10s}" for l in args.levels)
            snr = snr_per_column(tr[a], d["nonce0"], d["nonce1"], noise, np.random.default_rng(args.seed))
            print(f"  {name:28s} {snr.mean():9.2e} {col_sr[-1]:9.3f} {key_sr[-1]:9.3f}{cols} {fmt(n_key):>9s}")
            ci = {}
            if args.bootstrap:
                ci = {str(l): bootstrap_n(ok, grid, l, args.bootstrap) for l in args.levels}
                print(f"  {'':28s} 90% CI over keys: " + "  ".join(
                    f"N@{l:g} [{fmt(ci[str(l)][0])}, {fmt(ci[str(l)][1])}]" for l in args.levels))
            report["results"].setdefault(str(noise), {})[name] = {
                "col_sr": col_sr.tolist(), "key_sr": key_sr.tolist(),
                "n_at_col_sr": {str(l): v for l, v in n_lv.items()}, "n_ci90": ci,
                "n90_key": n_key, "snr_per_column": snr.tolist()}
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
