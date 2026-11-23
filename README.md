# Security-Aware Vt Assignment Against Static-Power Side-Channel Attacks

Course project by Ankush Philip John and Ayush Kumar.

Static-power attacks stop the clock and measure a circuit's leakage current,
which depends on the data it holds. Low-threshold (fast, leaky) cells amplify
that signal. This project assigns a threshold-voltage (Vt) flavour to every
cell of a fixed Ascon-AEAD128 netlist in ASAP7, under a fixed clock period, to
minimise the key-dependent part of the leakage, and compares the result with
a conventional timing-driven assignment.

New here? Read [docs/HANDOFF2AYUSH.md](docs/HANDOFF2AYUSH.md) first, then
[docs/LEAKAGE_GUIDE.md](docs/LEAKAGE_GUIDE.md) for the leakage and attack half.
All final numbers are in [results/figures/summary.md](results/figures/summary.md).

## Status (24 November 2026)

| Piece | State |
|---|---|
| ASAP7 libraries and per-state leakage parser | Done |
| Reference model of Ascon-AEAD128, checked against the official test vectors | Done (re-checked independently: 1089/1089) |
| Ascon core RTL, verified against the model in every round (2000 vectors) | Done |
| Synthesis to a gate-level netlist, verified by gate-level simulation | Done |
| Timing constraints and timing window | Done |
| Greedy Vt assignment with the baseline (total leakage) cost | Done (260, 300, 360 ps) |
| Netlist evaluator: every cell's logic state per execution | Done |
| Leakage signal scoring and the security cost | Done |
| Security-driven Vt assignment, plus a low-power variant (leakage weight 1e-6) | Done (260, 300, 360 ps) |
| Trace generation and CPA (textbook and profiled) | Done (all designs, 260/300/360 ps, 20 keys × 400 000 traces) |
| Template attack, TVLA | Not started |
| LiCSPA comparison design | Done (16 configurations per period; none met 260 ps) |
| Report figures and tables | Done (`eval/make_figures.py`) |
| Report and slides | Not started |

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
| `python3 eval/check_model.py <KAT file>` | Model, S-box table, round constants, official test vectors | `KAT entries checked: 1089, mismatches: 0` |
| `python3 eval/netlist_eval.py` | Netlist evaluator against the reference model | six `OK` lines; `RESULT: all checks passed` |
| `python3 eval/scoring.py results/vt/*.json` | Key-dependent signal and leakage of each assignment | headroom table |
| `python3 eval/run_security_assign.py --period 300 --out results/vt/security_var_300ps.json` | Security-driven assignment (`--leak-weight 1e-6` for the low-power variant) | `timing met`; 2–7 minutes |
| `python3 eval/licspa_sweep.py --period 300 --configs 8 --bits 24` | LiCSPA: random configurations, synthesis, timing closure, scores | `8/8 met timing`; about 4 minutes per configuration |
| `python3 eval/traces.py --assign <files> --experiments 20 --traces 400000 --seed 2026 --out results/raw/<name>.npz` | Simulated static-power traces | one `.npz` file (ignored by git) |
| `python3 eval/cpa.py results/raw/<name>.npz --model distance --json results/<name>.json` | Profiled CPA: success rate, traces to success, confidence intervals, SNR | about 15–20 minutes per design |
| `python3 eval/make_figures.py` | All report figures and tables from the result files | `results/figures/` (needs `python3-matplotlib`) |

The exact commands behind every committed result, with their seeds, are in
[docs/LEAKAGE_GUIDE.md](docs/LEAKAGE_GUIDE.md). NumPy needs an optimised BLAS
(`sudo apt install libopenblas0-pthread`); with Ubuntu's reference BLAS the
scoring runs about 20 times slower.

The toy design (one S-box column) has its own two scripts,
`flow/synth_toy.sh` and `flow/sta_swap_test.tcl`.

## Layout

| Folder | Contents |
|---|---|
| `docs/` | Handoff notes; guide to the leakage and attack half |
| `rtl/` | Ascon core, round, S-box; LiCSPA variant of the core; toy S-box column |
| `tb/` | Testbench for the core and the reference S-box table |
| `model/` | Python reference model of Ascon-AEAD128 and the test-vector generator |
| `flow/` | Library download, synthesis (core and LiCSPA), simulation, timing scripts and constraints |
| `eval/` | Leakage parser, netlist evaluator, signal scoring and security cost, security-driven assignment, LiCSPA sweep, trace generation, CPA, figures |
| `opt/` | Vt optimiser: OpenSTA driver, greedy loop, cost functions |
| `results/` | Vt assignments (`vt/`), LiCSPA configurations (`licspa/`), attack results (`cpa_*.json`), figures and summary tables (`figures/`); traces in `results/raw/` are ignored |
| `build/` | Generated netlists, merged libraries and logs (ignored) |
| `libs/` | ASAP7 liberty files (ignored) |

Planned and not yet created: `report/` for the report and slides.

## Results at a glance

Static leakage at the attack point, ASAP7 TT, 20 random keys × 400 000 traces
per design, profiled CPA. Traces for 50% per-column key-recovery success,
relative to the timing-driven baseline at the same clock period (full tables,
confidence intervals and caveats: `results/figures/summary.md`):

| Clock | Security-driven, low power (w = 1e-6) | Its leakage vs baseline | LiCSPA (best configuration) |
|---|---|---|---|
| 260 ps | 5.1× (and >133× at 80%) | 1.35× | no configuration met timing |
| 300 ps | 15× (34× at 80%) | 1.41× | 1.3× |
| 360 ps | 2.3× (3.0× at 80%) | 1.11× | 8.8× (+7.8% area) |

The security-driven designs add no area. No design, including the baseline,
reaches 90% full-key recovery within 400 000 traces, so results are stated per
S-box column.

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
