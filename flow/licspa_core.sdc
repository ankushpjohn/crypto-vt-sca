# Timing constraints for licspa_core: exactly those of ascon_core, plus the
# LiCSPA control inputs. ctl is driven like every other data input (from a
# flip-flop outside the core, e.g. the RNG's output register), which is
# conservative: it is held constant for a whole run.
source flow/ascon_core.sdc
set ctl_inputs [get_ports {ctl[*]}]
set_input_delay 60.0 -clock clk $ctl_inputs
set_input_transition 20.0 $ctl_inputs
