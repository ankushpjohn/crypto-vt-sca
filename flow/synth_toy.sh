#!/usr/bin/env bash
# Synthesise the toy S-box column onto the ASAP7 RVT library with Yosys, then
# prove the netlist equivalent to the RTL.
# Run from the project root:   flow/synth_toy.sh
#
# Outputs, in build/:
#   asap7_RVT_TT.lib        the five RVT libraries merged into one file
#   sbox_col_toy.v          gate-level netlist (for OpenSTA)
#   sbox_col_toy.json       the same netlist as JSON (for the Python tools)
#   sbox_col_toy.stat.txt   cell counts and area
#   sbox_col_toy.synth.log  full Yosys synthesis log
#   sbox_col_toy.equiv.log  full Yosys equivalence-check log
set -euo pipefail

LIBDIR=${LIBDIR:-libs/asap7}
BUILD=${BUILD:-build}
TOP=sbox_col_toy
RTL="rtl/ascon_sbox.v rtl/$TOP.v"
CORNER=TT

mkdir -p "$BUILD"
LIB="$BUILD/asap7_RVT_${CORNER}.lib"

# Yosys 0.9 takes one liberty file per command, so merge the five libraries.
python3 "$(dirname "$0")/merge_lib.py" "$LIB" \
  "$LIBDIR/asap7sc7p5t_SIMPLE_RVT_${CORNER}_nldm_211120.lib" \
  "$LIBDIR/asap7sc7p5t_INVBUF_RVT_${CORNER}_nldm_220122.lib" \
  "$LIBDIR/asap7sc7p5t_AO_RVT_${CORNER}_nldm_211120.lib" \
  "$LIBDIR/asap7sc7p5t_OA_RVT_${CORNER}_nldm_211120.lib" \
  "$LIBDIR/asap7sc7p5t_SEQ_RVT_${CORNER}_nldm_220123.lib"

echo "== synthesis"
yosys -q -l "$BUILD/$TOP.synth.log" -p "
  read_liberty -lib $LIB
  read_verilog $RTL
  hierarchy -check -top $TOP
  synth -top $TOP -flatten
  dfflibmap -liberty $LIB
  abc -liberty $LIB
  opt_clean -purge
  check -assert
  tee -o $BUILD/$TOP.stat.txt stat -liberty $LIB
  write_verilog -noattr -noexpr -nohex -nodec $BUILD/$TOP.v
  write_json $BUILD/$TOP.json
" 2>&1 | { grep -v "unsupported expression" || true; }
grep -E '_ASAP7_75t_|Number of cells|Chip area' "$BUILD/$TOP.stat.txt"

# Equivalence: the netlist, with cell behaviour taken from the liberty file,
# against the RTL. The toy has no feedback, so its outputs depend only on the
# last few inputs and a short induction is enough.
echo "== equivalence check (netlist vs RTL)"
yosys -q -l "$BUILD/$TOP.equiv.log" -p "
  read_verilog $RTL
  hierarchy -check -top $TOP
  proc; flatten; opt_clean
  rename $TOP gold
  design -stash gold

  read_liberty -ignore_miss_func $LIB
  read_verilog $BUILD/$TOP.v
  hierarchy -check -top $TOP
  proc; flatten; opt_clean
  rename $TOP gate
  design -stash gate

  design -copy-from gold -as gold gold
  design -copy-from gate -as gate gate
  equiv_make gold gate equiv
  hierarchy -top equiv
  equiv_simple -seq 4
  equiv_induct -seq 4
  equiv_status -assert
" 2>&1 | { grep -v "unsupported expression" || true; }
grep 'Equivalence successfully proven' "$BUILD/$TOP.equiv.log"
