# OpenSTA command server for the Vt optimiser. Started by opt/sta.py as
#   sta -no_init -no_splash opt/sta_server.tcl
# It reads one Tcl command per line on stdin, evaluates it, and answers with
# the result followed by a marker line, so that one long-running OpenSTA
# process (libraries loaded once) can serve thousands of queries.
#
# Loops over many cells run here, inside OpenSTA, because a pipe round trip
# per cell would cost more than the timing update itself.
#
# Times are in ps. Slack helpers use internal commands of OpenSTA 2.0.x
# (worst_slack_cmd, total_negative_slack_cmd, Vertex_slacks); a newer OpenSTA
# may need different calls in the four procs marked "version-specific".

# ---- slack queries (version-specific) ------------------------------------

proc vt_wns {} {    ;# worst setup slack
  return [sta::time_sta_ui [sta::worst_slack_cmd max]]
}
proc vt_tns {} {    ;# total negative setup slack, summed over endpoints
  return [sta::time_sta_ui [sta::total_negative_slack_cmd max]]
}
proc vt_hold {} {   ;# worst hold slack
  return [sta::time_sta_ui [sta::worst_slack_cmd min]]
}
# Worst setup slack of any path through an instance's output pins.
# Vertex_slacks returns {hold_slack setup_slack} for one transition.
proc vt_inst_slack {inst} {
  set worst 1e30
  foreach pin [get_pins -of_objects $inst] {
    if {[get_property $pin direction] ne "output"} continue
    foreach v [$pin vertices] {
      foreach tr {rise fall} {
        set s [lindex [sta::Vertex_slacks $v $tr] 1]
        if {$s < $worst} { set worst $s }
      }
    }
  }
  return [sta::time_sta_ui $worst]
}

# ---- commands used by opt/sta.py -----------------------------------------

# Load every Vt flavour of one corner, the netlist and the constraints.
proc vt_load {libdir corner netlist top sdc period} {
  global INST
  foreach f [lsort [glob $libdir/asap7sc7p5t_*_${corner}_nldm_*.lib]] {
    read_liberty $f
  }
  read_verilog $netlist
  link_design $top
  # OpenSTA's `source` runs the file at global level and carries on after an
  # error, so the period must be a global and the result must be checked.
  set ::clk_period $period
  source $sdc
  if {[llength [all_clocks]] == 0} {
    error "no clock defined after reading $sdc"
  }
  foreach inst [get_cells *] { set INST([get_full_name $inst]) $inst }
  return [array size INST]
}

# {instance lib_cell instance lib_cell ...} for the whole design.
proc vt_cells {} {
  global INST
  set out {}
  foreach name [lsort [array names INST]] {
    lappend out $name [get_property $INST($name) ref_name]
  }
  return $out
}

# "wns tns hold"
proc vt_summary {} {
  return [list [vt_wns] [vt_tns] [vt_hold]]
}

# {instance setup_slack ...} for the whole design.
proc vt_inst_slacks {} {
  global INST
  set out {}
  foreach name [array names INST] { lappend out $name [vt_inst_slack $INST($name)] }
  return $out
}

# Make swaps permanent. pairs = {instance lib_cell ...}
proc vt_apply {pairs} {
  global INST
  foreach {name cell} $pairs { replace_cell $INST($name) $cell }
  return [llength $pairs]
}

# Try each swap on its own and undo it. triples = {instance new_cell old_cell ...}
# Returns {wns tns ...}, one pair per swap.
proc vt_trial {triples} {
  global INST
  set out {}
  foreach {name new old} $triples {
    replace_cell $INST($name) $new
    lappend out [vt_wns] [vt_tns]
    replace_cell $INST($name) $old
  }
  return $out
}

# Try each swap in order and keep it only if setup and hold are still met.
# triples = {instance new_cell old_cell ...}. Returns one 0/1 flag per swap.
proc vt_keep_if_met {triples} {
  global INST
  set out {}
  foreach {name new old} $triples {
    replace_cell $INST($name) $new
    if {[vt_wns] >= 0.0 && [vt_hold] >= 0.0} {
      lappend out 1
    } else {
      replace_cell $INST($name) $old
      lappend out 0
    }
  }
  return $out
}

# ---- command loop --------------------------------------------------------

while {[gets stdin line] >= 0} {
  if {$line eq "quit"} break
  if {[catch {uplevel #0 $line} result]} {
    puts $result
    puts "@@ERR@@"
  } else {
    puts $result
    puts "@@OK@@"
  }
  flush stdout
}
exit
