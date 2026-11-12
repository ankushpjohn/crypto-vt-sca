#!/usr/bin/env python3
"""Reference model of Ascon-AEAD128 (NIST SP 800-232).

This is the golden model for the hardware. It provides

  * round_fn, permutation    the Ascon permutation on five 64-bit words;
  * init_states              the state register of rtl/ascon_core.v in every
                             cycle of the initialisation, which is what the
                             testbench and the leakage evaluation compare with;
  * encrypt                  full authenticated encryption, used only to check
                             this model against the official test vectors.

Check against the official known-answer file (LWC_AEAD_KAT_128_128.txt from
the Ascon reference implementation, 1089 entries):

    python3 model/ascon_ref.py path/to/LWC_AEAD_KAT_128_128.txt

A state is a list of five integers [x0, x1, x2, x3, x4].
"""
from __future__ import annotations

import sys

MASK = (1 << 64) - 1
IV = 0x0000_1000_808C_0001          # Ascon-AEAD128
ROUNDS_A = 12                        # initialisation and finalisation
ROUNDS_B = 8                         # between data blocks

# Rotation amounts of the linear layer, one pair per state word.
ROTATIONS = ((19, 28), (61, 39), (1, 6), (10, 17), (7, 41))


def rotr(x: int, n: int) -> int:
    return ((x >> n) | (x << (64 - n))) & MASK


def round_constant(r: int) -> int:
    """Constant of round r (0..11) of the 12-round permutation: 0xf0, 0xe1, ..."""
    return ((0xF - r) << 4) | r


def round_fn(state: list[int], rc: int) -> list[int]:
    """One round: constant addition, S-box layer, linear layer."""
    x0, x1, x2, x3, x4 = state
    x2 ^= rc
    # S-box layer, bitsliced over the 64 columns.
    x0 ^= x4
    x4 ^= x3
    x2 ^= x1
    t0 = ~x0 & x1 & MASK
    t1 = ~x1 & x2 & MASK
    t2 = ~x2 & x3 & MASK
    t3 = ~x3 & x4 & MASK
    t4 = ~x4 & x0 & MASK
    x0 ^= t1
    x1 ^= t2
    x2 ^= t3
    x3 ^= t4
    x4 ^= t0
    x1 ^= x0
    x0 ^= x4
    x3 ^= x2
    x2 ^= MASK
    # Linear layer.
    out = []
    for x, (a, b) in zip((x0, x1, x2, x3, x4), ROTATIONS):
        out.append(x ^ rotr(x, a) ^ rotr(x, b))
    return out


def permutation(state: list[int], rounds: int) -> list[int]:
    """The last `rounds` rounds of the 12-round permutation."""
    for r in range(12 - rounds, 12):
        state = round_fn(state, round_constant(r))
    return state


def words(b: bytes) -> tuple[int, int]:
    """16 bytes -> two 64-bit words, loaded little-endian as the standard does.

    bytes 00 01 .. 0f  ->  (0x0706050403020100, 0x0f0e0d0c0b0a0908)
    """
    assert len(b) == 16
    return int.from_bytes(b[:8], "little"), int.from_bytes(b[8:], "little")


def init_states(key0: int, key1: int, nonce0: int, nonce1: int) -> list[list[int]]:
    """State register of ascon_core in the 13 cycles after `start`.

    Element 0 is the loaded state IV | key | nonce (the primary static-power
    attack point); element k is the state after k rounds; element 12 is what
    the core presents when `done` is high.
    """
    state = [IV, key0, key1, nonce0, nonce1]
    states = [state]
    for r in range(ROUNDS_A):
        state = round_fn(state, round_constant(r))
        states.append(state)
    return states


def encrypt(key: bytes, nonce: bytes, ad: bytes, pt: bytes) -> bytes:
    """Ascon-AEAD128 encryption. Returns ciphertext followed by the 16-byte tag."""
    k0, k1 = words(key)
    n0, n1 = words(nonce)
    s = init_states(k0, k1, n0, n1)[-1]
    s[3] ^= k0
    s[4] ^= k1

    def absorb_pair(block: bytes) -> None:
        s[0] ^= int.from_bytes(block[:8], "little")
        s[1] ^= int.from_bytes(block[8:], "little")

    if ad:
        padded = ad + b"\x01" + bytes(-(len(ad) + 1) % 16)
        for i in range(0, len(padded), 16):
            absorb_pair(padded[i:i + 16])
            s = permutation(s, ROUNDS_B)
    s[4] ^= 1 << 63                                   # domain separation

    ct = b""
    padded = pt + b"\x01" + bytes(-(len(pt) + 1) % 16)
    for i in range(0, len(padded), 16):
        absorb_pair(padded[i:i + 16])
        block = s[0].to_bytes(8, "little") + s[1].to_bytes(8, "little")
        if i + 16 < len(padded):
            ct += block
            s = permutation(s, ROUNDS_B)
        else:
            ct += block[:len(pt) - i]

    s[2] ^= k0
    s[3] ^= k1
    s = permutation(s, ROUNDS_A)
    s[3] ^= k0
    s[4] ^= k1
    return ct + s[3].to_bytes(8, "little") + s[4].to_bytes(8, "little")


def check_kat(path: str) -> tuple[int, int]:
    """Run every entry of a NIST-format known-answer file. Returns (entries, mismatches)."""
    rec: dict[str, str] = {}
    n = bad = 0
    with open(path, encoding="ascii") as f:
        for line in f:
            if "=" not in line:
                continue
            k, v = (t.strip() for t in line.split("=", 1))
            rec[k] = v
            if k == "CT":
                got = encrypt(*(bytes.fromhex(rec[x]) for x in ("Key", "Nonce", "AD", "PT")))
                n += 1
                bad += got != bytes.fromhex(v)
    return n, bad


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    entries, mismatches = check_kat(sys.argv[1])
    print(f"KAT entries checked: {entries}, mismatches: {mismatches}")
    sys.exit(1 if mismatches or not entries else 0)
