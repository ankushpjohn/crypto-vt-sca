#!/usr/bin/env bash
# Simulate the Ascon core's self-checking testbench with Icarus Verilog.
# Run from the project root:   flow/sim_core.sh        (add +vcd for waveforms)
#
# The test vectors and their expected values are generated first, from the
# reference model in model/. VECTORS sets how many (default 2000).
set -euo pipefail

BUILD=${BUILD:-build}
VECTORS=${VECTORS:-2000}
mkdir -p "$BUILD"

python3 model/gen_core_vectors.py --n "$VECTORS" --out "$BUILD/core_vectors.hex"

iverilog -g2005 -Wall -Wno-timescale -s tb_ascon_core -o "$BUILD/tb_ascon_core.vvp"   rtl/ascon_sbox.v rtl/ascon_round.v rtl/ascon_core.v tb/tb_ascon_core.v

vvp -n "$BUILD/tb_ascon_core.vvp" "+vectors=$BUILD/core_vectors.hex" "$@"   | tee "$BUILD/tb_ascon_core.sim.log"
grep -q "RESULT: all checks passed" "$BUILD/tb_ascon_core.sim.log"
