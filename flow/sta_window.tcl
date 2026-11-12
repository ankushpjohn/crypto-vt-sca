# Timing window of a netlist: the minimum clock period with every cell in one
# Vt flavour, for each of the four flavours. A clock period for the Vt
# assignment experiments has to lie between the all-SLVT and all-SRAM values.
#
# Run from the project root, after flow/synth_core.sh:
#   sta -no_init -no_splash -exit flow/sta_window.tcl
# Another design:
#   TOP=sbox_col_toy sta -no_init -no_splash -exit flow/sta_window.tcl
#
# Times are in ps. The clock is ideal, there is no wire load, and paths from
# input ports are not constrained, so only register-to-register paths count.

proc env_or {name default} {
  if {[info exists ::env($name)]} { return $::env($name) }
  return $default
}

set LIBDIR  [env_or LIBDIR libs/asap7]
set TOP     [env_or TOP ascon_core]
set NETLIST [env_or NETLIST build/$TOP.v]
set CORNER  [env_or CORNER TT]
set PERIOD  1000.0 ;# ps; arbitrary, only used to turn slack into a period

# Flavour name -> suffix on the ASAP7 cell name, slowest first.
set FLAVOURS {SRAM RVT LVT SLVT}
array set SUFFIX {SRAM SRAM RVT R LVT L SLVT SL}

foreach vt $FLAVOURS {
  foreach f [lsort [glob $LIBDIR/asap7sc7p5t_*_${vt}_${CORNER}_nldm_*.lib]] {
    read_liberty $f
  }
}
read_verilog $NETLIST
link_design $TOP
create_clock -name clk -period $PERIOD [get_ports clk]

# Worst setup (max) or hold (min) slack in ps.
proc worst_slack {min_max} {
  return [sta::time_sta_ui [sta::worst_slack_cmd $min_max]]
}

# Swap every instance to one flavour, keeping function and drive strength.
proc set_all {vt} {
  global SUFFIX
  foreach inst [get_cells *] {
    regsub {_(SRAM|SL|R|L)$} [get_property $inst ref_name] "_$SUFFIX($vt)" new_cell
    replace_cell $inst $new_cell
  }
}

puts "\n== Timing window of $TOP ($NETLIST, $CORNER, [llength [get_cells *]] cells)"
puts [format "%-8s %14s %14s" flavour min_period_ps hold_slack_ps]
foreach vt $FLAVOURS {
  set_all $vt
  set period($vt) [expr {$PERIOD - [worst_slack max]}]
  puts [format "%-8s %14.1f %14.1f" $vt $period($vt) [worst_slack min]]
}
puts [format "window: all-SRAM / all-SLVT = %.2f" [expr {$period(SRAM) / $period(SLVT)}]]

puts "\n== Critical path, all-RVT"
set_all RVT
report_checks -path_delay max -digits 1
exit
