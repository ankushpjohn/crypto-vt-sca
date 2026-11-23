#!/usr/bin/env python3
"""Key-dependent static-leakage signal of a Vt assignment, and the security cost.

Definitions (handoff section 7)
-------------------------------
Column j of the round-1 S-box layer takes IV bit j (fixed), key bits
key0[j], key1[j] and nonce bits nonce0[j], nonce1[j]. With the key fixed, the
column's S-box output v takes 4 values, one per nonce class
c = 2*nonce0[j] + nonce1[j]. For cell i in flavour f, mu_i(v) is its mean
leakage over executions in class v, S(v) = sum_i mu_i(v), and

    metric "var":  signal = mean over keys of  sum over columns of  Var_v S(v)

This is the definition in the handoff. It also counts leakage that depends on
the nonce alone (for example the flip-flops holding nonce0/nonce1), which a
fixed-key attacker cannot use: it looks the same under every key guess. So a
second metric is offered, and both are always reported:

    metric "key":  per column, M(kc, c) = mean leakage with key class
                   kc = 2*key0[j] + key1[j] and nonce class c (pooled over
                   keys). Remove the row and column means (the key-only offset
                   and the nonce-only part); what is left is the interaction,
                   the part that depends on key and nonce together. signal =
                   sum over columns of the mean square of that interaction.

Which one the optimiser should use is a decision to agree with Ankush.

Estimation noise
----------------
mu_i(v) is estimated from a finite sample, and a variance of noisy means is
biased upwards: an optimiser would partly fit the noise. With estimator
"split" each class is split into two independent halves A and B
and every square is replaced by a product of an A term and a B term, which
removes the bias. The result can be negative when the true signal is near zero.

Use "split" for reporting only. As an optimiser objective it is unbounded
below: the optimiser learns to make the A and B halves disagree and drives
the cost far negative (seen at 300 ps: -7e6 pW^2). The optimiser therefore
uses "plain" (>= 0), and final numbers come from a second data set with
another seed (held-out), scored with "split".

The optimiser's cost
--------------------
SecurityCost has the three methods opt/vt_assign.py expects: delta, commit,
total. Each cell's contribution to S is precomputed for all four flavours, so
a swap changes S by T[f', i] - T[f, i] and the new signal is exact and cheap.

Usage
-----
    python3 eval/scoring.py results/vt/leakage_*.json        # score assignment files
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
sys.path.insert(0, str(ROOT / "model"))

from netlist_eval import Core, random_words, words_to_bits   # noqa: E402

METRICS = ("var", "key")


def balanced_keys(groups: int, rng) -> tuple[np.ndarray, np.ndarray]:
    """4*groups keys such that, in every column, each group of 4 keys contains
    each key class (key0[j], key1[j]) exactly once, in a random order that is
    independent between columns and groups."""
    k0 = np.zeros(4 * groups, dtype=np.uint64)
    k1 = np.zeros(4 * groups, dtype=np.uint64)
    for g in range(groups):
        for j in range(64):
            perm = rng.permutation(4)                       # key t gets class perm[t]
            for t in range(4):
                kc = int(perm[t])
                k0[4 * g + t] |= np.uint64((kc >> 1) & 1) << np.uint64(j)
                k1[4 * g + t] |= np.uint64(kc & 1) << np.uint64(j)
    return k0, k1


class SignalData:
    """Per-cell, per-flavour class means, ready for fast scoring.

    T has shape (flavours, cells, 2, K, 64, 4): half, key, column, nonce class.
    """

    def __init__(self, core: Core, groups: int = 2, nonces: int = 4096, seed: int = 1,
                 clk_level: int = 0, inputs: str = "hold", point: str = "primary", log=print):
        t0 = time.time()
        if nonces % 8:
            raise ValueError("nonces per key must be a multiple of 8")
        rng = np.random.default_rng(seed)
        self.core = core
        self.seed, self.groups, self.nonces = seed, groups, nonces
        self.settings = dict(clk_level=clk_level, inputs=inputs, point=point)
        self.key0, self.key1 = balanced_keys(groups, rng)
        K = len(self.key0)
        ncell = len(core.instances)
        nfl = len(core.flavours)
        self.T = np.zeros((nfl, ncell, 2, K, 64, 4), dtype=np.float32)   # ~4*3040*2*K*256*4 bytes
        bits = lambda w: words_to_bits(np.full(1, w, dtype=np.uint64))[0].astype(int)
        self.key_class = np.stack([2 * bits(a) + bits(b) for a, b in zip(self.key0, self.key1)])  # (K, 64)
        self.min_count = np.inf
        chunk = 4096                       # bounds memory: ~chunk * cells * 8 bytes per flavour
        for k in range(K):
            n0, n1 = random_words(rng, nonces), random_words(rng, nonces)
            sums = np.zeros((nfl, 512, ncell))
            counts = np.zeros((512, 1))
            for lo in range(0, nonces, chunk):
                hi = min(nonces, lo + chunk)
                m = hi - lo
                run = core.run(np.full(m, self.key0[k]), np.full(m, self.key1[k]), n0[lo:hi], n1[lo:hi],
                               clk_level=clk_level, inputs=inputs, secondary=(point == "secondary"),
                               seed=seed * 1000003 + k * 1009 + lo)
                states = run.states if point == "primary" else core.states_of(run.nets_next)
                cls = 2 * words_to_bits(n0[lo:hi]).astype(np.int64) + words_to_bits(n1[lo:hi])  # (m, 64)
                half = np.arange(lo, hi) % 2                                                    # A/B halves
                # Row (h, j, c) collects executions of half h with class c in column j.
                rows = (half[:, None] * 256 + np.arange(64)[None, :] * 4 + cls).ravel()
                A = np.zeros((512, m))
                # Each (row, execution) pair occurs once (one row per column), so plain
                # assignment is exact; np.add.at is very slow before NumPy 1.25.
                A[rows, np.repeat(np.arange(m), 64)] = 1.0
                counts += A.sum(axis=1, keepdims=True)
                for fi in range(nfl):
                    sums[fi] += A @ core.lut[fi, np.arange(ncell), states]                    # (512, cells)
            if counts.min() == 0:
                raise ValueError("an empty class: use more nonces per key")
            self.min_count = min(self.min_count, counts.min())
            for fi in range(nfl):
                self.T[fi, :, :, k] = (sums[fi] / counts).T.reshape(ncell, 2, 64, 4)
        if np.isnan(self.T).any():
            raise ValueError("NaN in the class means: a cell is in a state the library does not list")
        log(f"signal data: {K} keys x {nonces} nonces, seed {seed}, {self.settings}, "
            f"smallest class half {int(self.min_count)}, {time.time() - t0:.1f} s")

    def S(self, fidx: np.ndarray) -> np.ndarray:
        """Summed class means for a flavour index per cell: shape (2, K, 64, 4)."""
        return self.T[fidx, np.arange(len(fidx))].sum(axis=0, dtype=np.float64)

    def key_groups(self):
        """For metric 'key': per column, which keys have each key class."""
        return self.key_class


def signal(S: np.ndarray, key_class: np.ndarray, metric: str = "var",
           estimator: str = "split") -> float:
    """Signal from summed class means S (2, K, 64, 4). Units: pW^2."""
    if estimator == "plain":
        Sm = S.mean(axis=0)
        S = np.stack([Sm, Sm])
    A, B = S[0], S[1]
    if metric == "var":
        dA = A - A.mean(axis=-1, keepdims=True)
        dB = B - B.mean(axis=-1, keepdims=True)
        return float((dA * dB).mean(axis=-1).sum(axis=-1).mean())
    if metric == "key":
        IA, IB = _interaction(A, key_class), _interaction(B, key_class)
        return float((IA * IB).mean(axis=(1, 2)).sum())
    if metric == "nonce":
        # nonce-only part: variance over nonce class of the mean over keys
        dA = A.mean(axis=0) - A.mean(axis=(0, 2))[:, None]
        dB = B.mean(axis=0) - B.mean(axis=(0, 2))[:, None]
        return float((dA * dB).mean(axis=-1).sum())
    raise ValueError(metric)


def _interaction(X: np.ndarray, key_class: np.ndarray) -> np.ndarray:
    """X (K, 64, 4) -> double-centred M (64, kc, c)."""
    K = X.shape[0]
    onehot = np.zeros((64, 4, K))
    onehot[np.arange(64)[:, None], key_class.T, np.arange(K)[None, :]] = 1.0
    onehot /= onehot.sum(axis=2, keepdims=True)
    M = np.einsum("jak,kjc->jac", onehot, X)
    M = M - M.mean(axis=2, keepdims=True) - M.mean(axis=1, keepdims=True) + M.mean(axis=(1, 2), keepdims=True)
    return M


class SecurityCost:
    """Cost for opt/vt_assign.py: the leakage signal of the current assignment.

    Optional `leak_weight` adds  leak_weight * mean total leakage (pW) so the
    optimiser does not spend power for a negligible signal change.
    """

    def __init__(self, data: SignalData, flavour: dict[str, str], metric: str = "var",
                 estimator: str = "plain", leak_weight: float = 0.0, scale: float | None = None):
        self.d = data
        self.metric, self.estimator, self.leak_weight = metric, estimator, leak_weight
        self.name = f"security-{metric}" + (f"+{leak_weight:g}leak" if leak_weight else "")
        core = data.core
        self._col = {inst: k for k, inst in enumerate(core.instances)}
        self._fl = {f: i for i, f in enumerate(core.flavours)}
        self._fidx = core.flavour_index(flavour)
        self._S = data.S(self._fidx)
        # Mean leakage of each cell per flavour (over all executions), for the leak term.
        self._mean = data.T.mean(axis=(2, 3, 4, 5), dtype=np.float64)                         # (flavours, cells)
        self._sig = self._signal(self._S)
        # Scale so the cost is O(1) relative to its value with every cell RVT
        # (keeps the optimiser's gain/cost ratios well conditioned).
        if scale is None:
            ref = abs(self._signal(data.S(np.full_like(self._fidx, self._fl["RVT"]))))
            scale = ref if ref > 0 else 1.0
        self.scale = scale

    def _signal(self, S):
        return signal(S, self.d.key_class, self.metric, self.estimator)

    def _leak(self):
        return float(self._mean[self._fidx, np.arange(len(self._fidx))].sum())

    def delta(self, inst: str, new_flavour: str) -> float:
        i = self._col[inst]
        f, nf = self._fidx[i], self._fl[new_flavour]
        if f == nf:
            return 0.0
        D = self.d.T[nf, i].astype(np.float64) - self.d.T[f, i]
        out = (self._signal(self._S + D) - self._sig) / self.scale
        if self.leak_weight:
            out += self.leak_weight * (self._mean[nf, i] - self._mean[f, i])
        return out

    def commit(self, inst: str, new_flavour: str) -> None:
        i = self._col[inst]
        f, nf = self._fidx[i], self._fl[new_flavour]
        if f == nf:
            return
        self._S += self.d.T[nf, i].astype(np.float64) - self.d.T[f, i]
        self._fidx[i] = nf
        self._commits = getattr(self, "_commits", 0) + 1
        if self._commits % 500 == 0:                 # wipe accumulated rounding error
            self._S = self.d.S(self._fidx)
        self._sig = self._signal(self._S)

    def total(self) -> float:
        t = self._sig / self.scale
        if self.leak_weight:
            t += self.leak_weight * self._leak()
        return t

    def signal_pw2(self) -> float:
        return self._sig


def score(data: SignalData, fidx: np.ndarray) -> dict:
    """Every metric, both estimators, plus mean total leakage, for one assignment."""
    S = data.S(fidx)
    out = {m: signal(S, data.key_class, m, "split") for m in ("var", "key", "nonce")}
    out.update({f"{m}_plain": signal(S, data.key_class, m, "plain") for m in ("var", "key")})
    out["leak_nw"] = float(data.T[fidx, np.arange(len(fidx))].mean(axis=(1, 2, 3, 4), dtype=np.float64).sum()) / 1000.0
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Score Vt assignment files (headroom check).")
    ap.add_argument("assignments", nargs="*", help="JSON files with an 'assignment' object")
    ap.add_argument("--groups", type=int, default=2, help="key groups (4 keys each)")
    ap.add_argument("--nonces", type=int, default=4096, help="nonces per key")
    ap.add_argument("--seed", type=int, default=7, help="seed of the evaluation data (use a "
                    "different one from the optimiser's)")
    ap.add_argument("--clk", type=int, default=0, choices=(0, 1))
    ap.add_argument("--inputs", default="hold", choices=("hold", "zero", "random"))
    ap.add_argument("--point", default="primary", choices=("primary", "secondary"))
    ap.add_argument("--netlist", default="build/ascon_core.v",
                    help="netlist the assignment files belong to (LiCSPA: its own netlist)")
    ap.add_argument("--json", help="also write the scores to this file")
    args = ap.parse_args()

    from traces import make_core
    core = make_core(args.netlist)
    data = SignalData(core, args.groups, args.nonces, args.seed, args.clk, args.inputs, args.point)
    rows = [(f"all {f}", np.full(len(core.instances), i)) for i, f in enumerate(core.flavours)]
    for p in args.assignments:
        a = json.loads(Path(p).read_text())
        rows.append((Path(p).stem, core.flavour_index(a["assignment"])))

    ref = None
    results = {}
    print(f"\n{'assignment':28s} {'leak nW':>9s} {'var pW2':>10s} {'key pW2':>10s} "
          f"{'nonce pW2':>10s} {'var/RVT':>8s} {'key/RVT':>8s}")
    for name, fidx in rows:
        s = score(data, fidx)
        if name == "all RVT":
            ref = s
        results[name] = s
    for name, s in results.items():
        print(f"{name:28s} {s['leak_nw']:9.1f} {s['var']:10.1f} {s['key']:10.2f} {s['nonce']:10.1f} "
              f"{s['var'] / ref['var']:8.3f} {s['key'] / ref['key']:8.3f}")
    print("\nvar = handoff metric; key = key-and-nonce interaction only; nonce = nonce-only part.")
    if args.json:
        Path(args.json).write_text(json.dumps({"settings": vars(args), "scores": results}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
