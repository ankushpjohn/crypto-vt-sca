#!/usr/bin/env python3
"""Write the test-vector file for tb/tb_ascon_core.v.

    python3 model/gen_core_vectors.py --out build/core_vectors.hex

One line per vector, seven hexadecimal fields:

    wait rst key0 key1 nonce0 nonce1 states

  key0 key1 nonce0 nonce1   the inputs applied together with `start`
  states                    13 x 320 bits: the expected x0..x4 in each of the
                            13 cycles after `start` (loaded state first, then
                            after round 1, ... after round 12), from
                            model/ascon_ref.py
  wait                      idle cycles after the start cycle before the
                            testbench does its next action. The core needs 12
                            to finish, so 0..11 cuts this run short and 12
                            makes the next start coincide with `done`.
  rst                       1: the next action is a one-cycle reset, and the
                            next vector follows it; 0: it is the next vector.

The first three vectors are fixed (official test-vector key and nonce, all
zeros, all ones); the rest are random. About a fifth of the vectors are cut
short by an early start or a reset, to exercise the control logic. The same
seed always gives the same file.
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ascon_ref import MASK, init_states, words  # noqa: E402

FULL = 12        # idle cycles the core needs after the start cycle


def line(wait: int, rst: int, k0: int, k1: int, n0: int, n1: int) -> str:
    states = "".join(f"{w:016x}" for s in init_states(k0, k1, n0, n1) for w in s)
    return f"{wait:02x} {rst:x} {k0:016x} {k1:016x} {n0:016x} {n1:016x} {states}\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=2000, help="number of vectors (default 2000)")
    ap.add_argument("--seed", type=int, default=20261112)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    k_official = words(bytes(range(0x00, 0x10)))
    n_official = words(bytes(range(0x10, 0x20)))
    fixed = [(*k_official, *n_official), (0, 0, 0, 0), (MASK, MASK, MASK, MASK)]

    lines = []
    for i in range(args.n):
        if i < len(fixed):
            inputs, wait, rst = fixed[i], FULL + 1, 0      # always run to completion
        else:
            inputs = tuple(rng.getrandbits(64) for _ in range(4))
            u = rng.random()
            if u < 0.60:                                   # completes, then a gap
                wait, rst = FULL + rng.randint(1, 4), 0
            elif u < 0.80:                                 # next start in the done cycle
                wait, rst = FULL, 0
            elif u < 0.90:                                 # cut short by the next start
                wait, rst = rng.randint(0, FULL - 1), 0
            else:                                          # cut short by a reset
                wait, rst = rng.randint(0, FULL - 1), 1
        lines.append(line(wait, rst, *inputs))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(lines), encoding="ascii", newline="\n")
    print(f"wrote {out}: {len(lines)} vectors, seed {args.seed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
