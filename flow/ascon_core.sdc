# Timing constraints for ascon_core. Every STA script reads this one file, so
# the timing window, the baseline and the optimiser all time the design under
# the same conditions.
#
# Units follow the ASAP7 libraries: time in ps, capacitance in fF.
#
# The caller sets clk_period before reading the file:
#   set clk_period 300.0
#   source flow/ascon_core.sdc
#
# What is still not modelled: wire resistance and capacitance (there is no
# placement), and clock network delay (the clock is ideal).

if {![info exists clk_period]} {
  error "set clk_period (in ps) before reading ascon_core.sdc"
}

# Clock.
create_clock -name clk -period $clk_period [get_ports clk]

# Guard band. Stands in for clock skew and jitter, and for the wire delay this
# flow does not model. It is a fixed number of ps, not a fraction of the
# period, so that every design and every Vt assignment gets the same margin.
set_clock_uncertainty -setup 15.0 [get_clocks clk]
set_clock_uncertainty -hold  10.0 [get_clocks clk]

# Inputs. Assume each input comes from a flip-flop in the same clock domain
# outside the core: 60 ps is about the clock-to-output delay of DFFHQNx1 in
# RVT, and 20 ps a typical edge. The surrounding logic is assumed to buffer
# its own outputs, so fanout inside the core (start drives several hundred
# pins) is not charged to the driver.
set data_inputs [get_ports {rst start key0[*] key1[*] nonce0[*] nonce1[*]}]
set_input_delay 60.0 -clock clk $data_inputs
set_input_transition 20.0 $data_inputs

# Outputs. Assume each output is captured by a flip-flop outside the core
# (25 ps is about its setup time) through a load of 2 fF, roughly three
# minimum-size gate inputs. The load matters for x0..x4: it sits on the state
# register outputs, which also drive the round logic.
set data_outputs [get_ports {busy done x0[*] x1[*] x2[*] x3[*] x4[*]}]
set_output_delay 25.0 -clock clk $data_outputs
set_load 2.0 $data_outputs
