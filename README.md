# Security-Aware Vt Assignment Against Static-Power Side-Channel Attacks

Course project: Ascon-AEAD128 permutation core in ASAP7 (7.5-track).
Ankush Philip John, Ayush Kumar.

## Setup (WSL Ubuntu)

Needs yosys, OpenSTA (`sta`), verilator, python3, curl, git.

    flow/get_asap7.sh

This fetches the ASAP7 liberty files into `libs/asap7/` (not committed).

## Layout

| Folder     | Contents                                             |
|------------|------------------------------------------------------|
| `rtl/`     | Ascon RTL, toy S-box column, LiCSPA primitive        |
| `tb/`      | Testbenches                                          |
| `model/`   | Python golden model and test vectors                 |
| `flow/`    | Synthesis, timing and library scripts                |
| `eval/`    | Leakage parser, scoring, trace generation, attacks   |
| `configs/` | Clock periods, seeds, Vt assignment files            |
| `results/` | Summary tables and plots (`results/raw/` is ignored) |
| `report/`  | Report and presentation                              |

## Conventions

- Fixed, recorded seeds for every experiment.
- Netlist versions are tagged in git; Vt assignments refer to a tag.
