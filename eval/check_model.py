#!/usr/bin/env python3
"""Tasks 1 and 2 of the handoff: check the golden model and the S-box table.

1. The S-box implied by model/ascon_ref.py (its bitsliced round with the
   constant and linear layer removed) must equal the table in
   tb/ascon_sbox_ref.v, and that table must equal the one printed in
   NIST SP 800-232 (typed below, independently of both).
2. If you pass the official known-answer file, every entry is checked:

    python3 eval/check_model.py
    python3 eval/check_model.py path/to/LWC_AEAD_KAT_128_128.txt

The KAT file is in the Ascon reference implementation,
github.com/ascon/ascon-c, crypto_aead/asconaead128/LWC_AEAD_KAT_128_128.txt.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "model"))

import ascon_ref as m   # noqa: E402

# NIST SP 800-232, Table (S-box), input 0x00..0x1f.
SPEC = [0x04, 0x0b, 0x1f, 0x14, 0x1a, 0x15, 0x09, 0x02, 0x1b, 0x05, 0x08, 0x12,
        0x1d, 0x03, 0x06, 0x1c, 0x1e, 0x13, 0x07, 0x0e, 0x00, 0x0d, 0x11, 0x18,
        0x10, 0x0c, 0x01, 0x19, 0x16, 0x0a, 0x0f, 0x17]


def model_sbox(x: int) -> int:
    """S-box of the model: put x in column 0, run round_fn with rc = 0 and undo
    the linear layer by reading only the S-box outputs (rotations move bit 0
    elsewhere, so instead we recompute with all rotations removed)."""
    state = [(x >> (4 - i)) & 1 for i in range(5)]
    saved = m.ROTATIONS
    try:
        m.ROTATIONS = ((0, 0),) * 5           # x ^ x ^ x = x: linear layer becomes identity
        out = m.round_fn(state, 0)
    finally:
        m.ROTATIONS = saved
    out = [w & 1 for w in out]
    return sum(b << (4 - i) for i, b in enumerate(out))


def tb_table() -> list[int]:
    text = (ROOT / "tb" / "ascon_sbox_ref.v").read_text()
    pairs = re.findall(r"5'h([0-9a-f]{2}):\s*y\s*=\s*5'h([0-9a-f]{2})", text)
    table = [None] * 32
    for a, b in pairs:
        table[int(a, 16)] = int(b, 16)
    return table


def main() -> int:
    ok = True
    mod = [model_sbox(x) for x in range(32)]
    tb = tb_table()
    for name, t in (("model", mod), ("tb/ascon_sbox_ref.v", tb)):
        bad = [x for x in range(32) if t[x] != SPEC[x]]
        print(f"S-box of {name:22s}: {'matches SP 800-232' if not bad else f'MISMATCH at {bad}'}")
        ok &= not bad
    rc = [m.round_constant(r) for r in range(12)]
    want = [0xf0, 0xe1, 0xd2, 0xc3, 0xb4, 0xa5, 0x96, 0x87, 0x78, 0x69, 0x5a, 0x4b]
    print(f"round constants: {'match' if rc == want else 'MISMATCH'}")
    ok &= rc == want
    print(f"IV: {m.IV:#018x} ({'matches' if m.IV == 0x00001000808C0001 else 'MISMATCH'} Ascon-AEAD128)")
    if len(sys.argv) > 1:
        n, bad = m.check_kat(sys.argv[1])
        print(f"KAT entries checked: {n}, mismatches: {bad}")
        ok &= n > 0 and bad == 0
    print("RESULT: " + ("all checks passed" if ok else "CHECKS FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
