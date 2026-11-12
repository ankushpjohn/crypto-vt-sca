#!/usr/bin/env bash
# Simulate the Ascon core's self-checking testbench with Icarus Verilog.
# Run from the project root:   flow/sim_core.sh        (add +vcd for waveforms)
set -euo pipefail

BUILD=${BUILD:-build}
mkdir -p "$BUILD"

iverilog -g2005 -Wall -Wno-timescale -o "$BUILD/tb_ascon_core.vvp" \
  rtl/ascon_sbox.v rtl/ascon_round.v rtl/ascon_core.v \
  tb/tb_ascon_core.v tb/sim_ascon_core.v

vvp -n "$BUILD/tb_ascon_core.vvp" "$@" | tee "$BUILD/tb_ascon_core.sim.log"
grep -q "RESULT: all checks passed" "$BUILD/tb_ascon_core.sim.log"
