# Security-Aware Vt Assignment Against Static-Power Side-Channel Attacks

Course project by Ankush Philip John and Ayush Kumar.

Static-power attacks stop the clock and measure a circuit's leakage current,
which depends on the data it holds. Low-threshold (fast, leaky) cells amplify
that signal. This project assigns a threshold-voltage (Vt) flavour to every
cell of a fixed Ascon-AEAD128 netlist in ASAP7, under a fixed clock period, to
minimise the key-dependent part of the leakage, and compares the result with
a conventional timing-driven assignment.

New here? Read [docs/HANDOFF2AYUSH.md](docs/HANDOFF2AYUSH.md) first.

## Status (13 November 2026)

| Piece | State |
|---|---|
| ASAP7 libraries and per-state leakage parser | Done |
| Reference model of Ascon-AEAD128, checked against the official test vectors | Done |
| Ascon core RTL, verified against the model in every round (2000 vectors) | Done |
| Synthesis to a gate-level netlist, verified by gate-level simulation | Done |
| Timing constraints and timing window | Done |
| Greedy Vt assignment with the baseline (total leakage) cost | Done |
| Netlist evaluator: every cell's logic state per execution | Not started |
| Leakage signal scoring and the security cost | Not started |
| Trace generation, CPA, template attack, TVLA | Not started |
| LiCSPA comparison design | Not started |

## Setup

Developed on WSL Ubuntu 22.04 with Yosys 0.9, OpenSTA 2.0.17, Icarus Verilog
11.0, Python 3.10 and NumPy. Other versions have not been tried, and a
different Yosys may produce a different netlist.

Fetch the ASAP7 liberty files (about 80 MB to download, 350 MB on disk, not
committed). Pinning the upstream commit gives the files all results here came
from:

    REF=a47d4fdc6534cb3cdfdd9ff76737a899a5bb2ee0 bash flow/get_asap7.sh

## Running the flow

Run everything from the project root.

| Command | What it does | Expected result |
|---|---|---|
| `python3 eval/liberty_leakage.py libs/asap7` | Self-check of the leakage parser | 202 cells; ratios 0.232 / 9.6 / 97.3 |
| `bash flow/sim_core.sh` | RTL simulation of the core, 2000 vectors | `0 errors`; `RESULT: all checks passed` |
| `bash flow/synth_core.sh` | Synthesis, then gate-level simulation, 300 vectors | 3040 cells; `RESULT: all checks passed` |
| `sta -no_init -no_splash -exit flow/sta_window.tcl` | Minimum clock period per Vt flavour | 455.0 / 353.7 / 272.2 / 233.3 ps |
| `python3 opt/vt_assign.py --period 300 --out results/vt/leakage_300ps.json` | Baseline Vt assignment at a 300 ps clock | `timing met`; about 3 minutes |

The toy design (one S-box column) has its own two scripts,
`flow/synth_toy.sh` and `flow/sta_swap_test.tcl`.

## Layout

| Folder | Contents |
|---|---|
| `docs/` | Handoff notes |
| `rtl/` | Ascon core, round, S-box; toy S-box column |
| `tb/` | Testbench for the core and the reference S-box table |
| `model/` | Python reference model of Ascon-AEAD128 and the test-vector generator |
| `flow/` | Library download, synthesis, simulation, timing scripts and constraints |
| `eval/` | Leakage parser; later scoring, trace generation and attacks |
| `opt/` | Vt optimiser: OpenSTA driver, greedy loop, cost functions |
| `results/` | Summary tables, plots and Vt assignments (`results/raw/` is ignored) |
| `build/` | Generated netlists, merged libraries and logs (ignored) |
| `libs/` | ASAP7 liberty files (ignored) |

Planned and not yet created: `configs/` for experiment settings and
`report/` for the report and slides.

## Conventions

- Time is in ps, capacitance in fF, leakage in pW, as in the ASAP7 libraries.
- Vt flavours are called SRAM, RVT, LVT and SLVT, slowest to fastest. "SRAM"
  is the highest-Vt flavour of the logic cells, not a memory cell.
- Every experiment uses a fixed, recorded random seed.
- A Vt assignment is only meaningful for the exact netlist it was made for.
  Result files record the netlist's SHA-256; the handoff gives the current
  netlist's value.
- The gate-level simulation is slow (about 6 vectors per second), so it
  runs 300 vectors by default. `VECTORS=2000 bash flow/synth_core.sh` runs
  the full set.
- Scripts use Unix line endings (`.gitattributes` enforces this).
