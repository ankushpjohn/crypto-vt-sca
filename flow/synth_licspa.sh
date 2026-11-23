#!/usr/bin/env bash
# Synthesise one LiCSPA configuration of the core (rtl/licspa_core.v).
#
#   flow/synth_licspa.sh <dir>
#
# <dir> must contain licspa_cfg.vh (written by eval/licspa_sweep.py). Writes,
# in <dir>:
#   licspa_core.v        netlist for OpenSTA and the Python tools (no attributes)
#   licspa_core_attr.v   the same netlist with src attributes, used only to find
#                        the primitive flip-flops; instance names are identical
#   licspa_core.json     Yosys JSON
#   licspa_core.stat.txt cell counts and area
# Same synthesis recipe as flow/synth_core.sh, plus one rename: the
# generate-block register names (bitreg[i].plain.r) are hidden so that the
# netlist names the state nets by the output ports, as in ascon_core. Without
# it Yosys writes concatenated `assign` statements that OpenSTA 2.0.17 cannot
# parse. Needs build/asap7_RVT_TT.lib
# (run flow/synth_core.sh once first).
set -euo pipefail
DIR=${1:?usage: flow/synth_licspa.sh <dir>}
LIB=${LIB:-build/asap7_RVT_TT.lib}
MAX_FANOUT=${MAX_FANOUT:-16}
TOP=licspa_core
[[ -s $LIB ]] || { echo "missing $LIB: run flow/synth_core.sh first" >&2; exit 1; }
[[ -s $DIR/licspa_cfg.vh ]] || { echo "missing $DIR/licspa_cfg.vh" >&2; exit 1; }

ABC_SCRIPT="+strash;ifraig;scorr;dc2;dretime;strash;&get,-n;&dch,-f;&nf;&put;buffer,-N,${MAX_FANOUT};stime,-p"
yosys -q -l "$DIR/$TOP.synth.log" -p "
  read_liberty -lib $LIB
  read_verilog -I$DIR rtl/ascon_sbox.v rtl/ascon_round.v rtl/licspa_core.v
  hierarchy -check -top $TOP
  synth -top $TOP -flatten
  dfflibmap -liberty $LIB
  abc -liberty $LIB -script $ABC_SCRIPT
  rename -hide w:bitreg* w:q w:nxt
  opt_clean -purge
  check -assert
  tee -o $DIR/$TOP.stat.txt stat -liberty $LIB
  write_verilog -noattr -noexpr -nohex -nodec $DIR/$TOP.v
  write_verilog -noexpr -nohex -nodec $DIR/${TOP}_attr.v
  write_json $DIR/$TOP.json
" 2>&1 | { grep -v "unsupported expression" || true; }
grep -E 'Number of cells|Chip area' "$DIR/$TOP.stat.txt"
