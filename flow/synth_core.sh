#!/usr/bin/env bash
# Synthesise the Ascon core onto the ASAP7 RVT library with Yosys, then check
# the netlist by gate-level simulation of the RTL testbench.
# Run from the project root:   flow/synth_core.sh
#
# Outputs, in build/:
#   asap7_RVT_TT.lib          the five RVT libraries merged into one file
#   asap7_RVT_TT_sim.v        Verilog models of the cells, made from the library
#   ascon_core.v              gate-level netlist (for OpenSTA and simulation)
#   ascon_core.json           the same netlist as JSON (for the Python tools)
#   ascon_core.stat.txt       cell counts and area
#   ascon_core.synth.log      full Yosys log
#   ascon_core.gatesim.log    gate-level simulation log
#
# Every cell is mapped in RVT. The flavour of each cell is chosen afterwards;
# all four flavours share function, pins and footprint, so the netlist stays
# valid for any assignment.
set -euo pipefail

LIBDIR=${LIBDIR:-libs/asap7}
BUILD=${BUILD:-build}
TOP=ascon_core
RTL="rtl/ascon_sbox.v rtl/ascon_round.v rtl/ascon_core.v"
CORNER=TT
MAX_FANOUT=${MAX_FANOUT:-16}
VECTORS=${VECTORS:-300}      # test vectors for the gate-level simulation,
                             # which runs at about 6 vectors per second

mkdir -p "$BUILD"
LIB="$BUILD/asap7_RVT_${CORNER}.lib"
SIMLIB="$BUILD/asap7_RVT_${CORNER}_sim.v"

# Yosys 0.9 takes one liberty file per command, so merge the five libraries.
python3 "$(dirname "$0")/merge_lib.py" "$LIB" \
  "$LIBDIR/asap7sc7p5t_SIMPLE_RVT_${CORNER}_nldm_211120.lib" \
  "$LIBDIR/asap7sc7p5t_INVBUF_RVT_${CORNER}_nldm_220122.lib" \
  "$LIBDIR/asap7sc7p5t_AO_RVT_${CORNER}_nldm_211120.lib" \
  "$LIBDIR/asap7sc7p5t_OA_RVT_${CORNER}_nldm_211120.lib" \
  "$LIBDIR/asap7sc7p5t_SEQ_RVT_${CORNER}_nldm_220123.lib"

# ABC script: Yosys's standard liberty mapping script, followed by `buffer`,
# which caps the fanout of every net and resizes gates. Without it a net such
# as a 300-way mux select is driven by one minimum-size gate and sets the
# clock period by itself. (Commas stand for spaces in a Yosys +script.)
ABC_SCRIPT="+strash;ifraig;scorr;dc2;dretime;strash;&get,-n;&dch,-f;&nf;&put;buffer,-N,${MAX_FANOUT};stime,-p"

echo "== synthesis (fanout cap $MAX_FANOUT)"
yosys -q -l "$BUILD/$TOP.synth.log" -p "
  read_liberty -lib $LIB
  read_verilog $RTL
  hierarchy -check -top $TOP
  synth -top $TOP -flatten
  dfflibmap -liberty $LIB
  abc -liberty $LIB -script $ABC_SCRIPT
  opt_clean -purge
  check -assert
  tee -o $BUILD/$TOP.stat.txt stat -liberty $LIB
  write_verilog -noattr -noexpr -nohex -nodec $BUILD/$TOP.v
  write_json $BUILD/$TOP.json
" 2>&1 | { grep -v "unsupported expression" || true; }
grep -E '_ASAP7_75t_|Number of cells|Chip area' "$BUILD/$TOP.stat.txt"

# Gate-level simulation: the same testbench as flow/sim_core.sh, with the
# netlist in place of the RTL and fewer vectors (the first VECTORS of the
# same sequence). Cell behaviour comes from the liberty file's
# function attributes, written out as Verilog by Yosys. Zero-delay: this
# checks function only, timing is OpenSTA's job.
echo "== gate-level simulation"
yosys -q -p "
  read_liberty -ignore_miss_func $LIB
  write_verilog -noattr $SIMLIB
" 2>&1 | { grep -v "unsupported expression" || true; }

python3 model/gen_core_vectors.py --n "$VECTORS" --out "$BUILD/core_vectors.hex"
iverilog -g2005 -s tb_ascon_core -o "$BUILD/$TOP.gatesim.vvp" \
  "$SIMLIB" "$BUILD/$TOP.v" tb/tb_ascon_core.v
vvp -n "$BUILD/$TOP.gatesim.vvp" "+vectors=$BUILD/core_vectors.hex" > "$BUILD/$TOP.gatesim.log"
tail -n 2 "$BUILD/$TOP.gatesim.log"
grep -q "RESULT: all checks passed" "$BUILD/$TOP.gatesim.log"
