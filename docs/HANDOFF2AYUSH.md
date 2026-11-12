# Handoff for Ayush

Status as of the evening of 12 November 2026. Written so you can clone the
repository and start work without needing the earlier conversations. This
replaces the first version, which predated the full core.

## 1. Where the project stands

**Topic.** Security-aware threshold-voltage (Vt) assignment against
static-power side-channel attacks, on a round-per-cycle Ascon-AEAD128 core in
ASAP7. We assign a Vt flavour to every cell of a fixed netlist, under a fixed
clock period, to minimise the key-dependent static leakage signal. Vt
flavours share footprints, so area does not change. The submitted proposal
has the full statement and the claim (at least 3x more traces to 90%-success
key recovery than timing-driven assignment, under CPA and a template attack).

**Not yet settled.**

- The proposal is not approved yet. We are starting anyway because of time.
- ASAP7 is not on the course brief's library list. Whether the professor
  accepts it is still to be confirmed. The method needs per-input-state
  leakage, which GT3 and GT2N do not provide.
- The deadline is tentatively 28 November, to be confirmed.

**Done so far.**

| Step | State |
|---|---|
| ASAP7 libraries fetched, leakage parser written and checked | Done |
| Toy S-box column: synthesis, equivalence proof, OpenSTA Vt swaps | Done |
| Full core RTL, verified against official test vectors | Done |
| Core synthesised and the netlist verified by gate-level simulation | Done |
| Timing constraints and timing window | Done |
| Greedy Vt assignment with the baseline (total leakage) cost | Done |
| Netlist evaluator: every cell's logic state per execution | **Not started** |
| Signal scoring and the security cost | **Not started** |
| Trace generation and attacks | **Not started** |

The timing half of the project is in place. The leakage half, which is your
part, is what the next steps wait on.

## 2. Getting set up

Developed and tested on WSL Ubuntu 22.04 with Yosys 0.9, OpenSTA 2.0.17,
Icarus Verilog 11.0, Python 3.10 and NumPy. Newer versions have not been
tried.

    git clone https://github.com/ankushpjohn/crypto-vt-sca.git
    cd crypto-vt-sca

Fetch the libraries (about 80 MB download, 350 MB on disk, not in git).
Pinning the commit gives you exactly the files the results below came from:

    REF=a47d4fdc6534cb3cdfdd9ff76737a899a5bb2ee0 bash flow/get_asap7.sh

Then check that everything works on your machine:

    python3 eval/liberty_leakage.py libs/asap7
    bash flow/sim_core.sh
    bash flow/synth_core.sh
    sta -no_init -no_splash -exit flow/sta_window.tcl

Expected: the parser reports 202 cells and Vt ratios of 0.232 / 9.6 / 97.3;
both simulations end with "RESULT: all checks passed"; synthesis reports
2986 cells; the window script prints 441.1 / 343.2 / 262.2 / 222.7 ps.

**Check your netlist matches.** The netlist is generated, not stored in git
(see section 8). After `flow/synth_core.sh`, run

    sha256sum build/ascon_core.v

and compare with

    62ff752312c04f1dc3e9ae213037369329f8e738ff9ead21723c946c68ed7b98

If it differs, your Yosys produced a different netlist and instance names
will not match Vt assignment files. Tell Ankush before going further.

## 3. What is in the repository

| File | What it does |
|---|---|
| `flow/get_asap7.sh` | Downloads the ASAP7 7.5-track liberty files (4 Vt flavours, TT and SS) into `libs/asap7/` |
| `flow/merge_lib.py` | Merges the five ASAP7 libraries of one flavour into one file |
| `eval/liberty_leakage.py` | Parses per-state leakage into NumPy tables: `table[cell][flavour]` |
| `rtl/ascon_sbox.v` | Bitsliced Ascon S-box, `W` columns wide |
| `rtl/ascon_round.v` | One combinational permutation round |
| `rtl/ascon_core.v` | The core: state register, round counter, control |
| `tb/tb_ascon_core.v`, `tb/sim_ascon_core.v` | Self-checking testbench and its simulation wrapper |
| `flow/sim_core.sh` | Runs the testbench on the RTL in Icarus Verilog |
| `flow/synth_core.sh` | Synthesises the core, then runs the testbench on the netlist |
| `flow/ascon_core.sdc` | Timing constraints, shared by every timing script |
| `flow/sta_window.tcl` | Minimum clock period with every cell in each flavour |
| `opt/sta_server.tcl`, `opt/sta.py` | One long-running OpenSTA process driven from Python |
| `opt/vt_assign.py` | Greedy Vt assignment loop and the baseline cost |
| `rtl/sbox_col_toy.v`, `tb/ascon_sbox_ref.v`, `flow/synth_toy.sh`, `flow/sta_swap_test.tcl` | The toy single-column design and its checks |

Generated files go to `build/` (ignored by git). The core netlist is written
as Verilog (`build/ascon_core.v`) and as Yosys JSON (`build/ascon_core.json`);
the JSON is the easier one to read from Python. `build/asap7_RVT_TT_sim.v`
holds a Verilog model of every library cell.

## 4. The core

**Behaviour.** On `start` the state register loads

    x0 = IV = 0x00001000808c0001,  x1 = key0,  x2 = key1,  x3 = nonce0,  x4 = nonce1

and the core applies one permutation round per clock cycle. `done` is high
for exactly one cycle, 13 cycles after `start`, when `x0..x4` hold the state
after 12 rounds.

- `key0`, `key1`, `nonce0`, `nonce1` are the standard's 64-bit state words
  S1 to S4. Converting the 16-byte key and nonce into them (SP 800-232 loads
  bytes little-endian) is left to the testbench and the software model.
- Bit j of every word belongs to S-box column j. In the first round, column
  j therefore sees IV bit j, `key0[j]`, `key1[j]`, `nonce0[j]`, `nonce1[j]`.
- The round constant for round r is `{~r, r}` on four bits each: 0xf0, 0xe1,
  ... 0x4b. It is XORed into the low byte of x2.
- Only the 12-round initialisation is implemented, not the 8-round data
  phase.

**The state register is free-running.** It has no hold enable and keeps
applying rounds after `done`, so the result is valid for one cycle only. A
hold enable is one flip-flop driving all 320 state bits; in this flow that
net, not the round logic, became the critical path. The attack points are
unaffected.

**Attack points.**

- Primary: the cycle after `start`. The state register holds IV, key and
  nonce, the round counter is 0, and the round logic has settled on round 1.
- Secondary: one cycle later. The state register holds the round-1 output.

**Verification.** The testbench runs four key/nonce pairs and checks the
final state and the `done` cycle. Its expected values came from a throwaway
Python model that reproduced all 1089 official Ascon-AEAD128 known-answer
tests. That model is not in the repository; ask Ankush if you want it as a
starting point for the golden model.

## 5. Facts established so far

**Library (TT corner, 25 C, 0.70 V).**

- 202 cells, each in four Vt flavours with identical function, pins and area.
  Cell names end in `_ASAP7_75t_SRAM`, `_R`, `_L` or `_SL`. We call the
  flavours SRAM, RVT, LVT and SLVT, slowest to fastest. "SRAM" is a threshold
  flavour (the highest Vt), not a memory cell.
- Every cell lists leakage per logic state. Example, RVT NAND2xp5 in pW:
  27.1 (A=0,B=0), 50.3 (A=0,B=1), 54.7 (A=1,B=0), 66.3 (A=1,B=1).
- Median leakage relative to RVT: SRAM 0.23x, LVT 9.6x, SLVT 97x.
- Leakage is in pW, time in ps, capacitance in fF throughout.

**Core netlist.** 2986 cells of 23 types, 362.7 um^2, all mapped in RVT. The
largest groups: 823 XNOR2x2, 391 NAND2xp33, 372 OAI21xp33, 330 INVxp33,
326 DFFHQNx1, 266 NOR2xp33, 214 XOR2x2, 144 AOI21xp33. Synthesis caps fanout
at 16 with ABC's `buffer` command.

**Timing constraints (`flow/ascon_core.sdc`).** Clock uncertainty 15 ps
setup and 10 ps hold; inputs arrive 60 ps after the clock with a 20 ps edge;
outputs need 25 ps before the next clock and drive 2 fF. There is no wire
load and the clock is ideal.

**Timing window, every cell in one flavour.**

| Flavour | Minimum period (ps) | Hold slack (ps) |
|---|---|---|
| SRAM | 441.1 | 53.6 |
| RVT | 343.2 | 47.5 |
| LVT | 262.2 | 38.9 |
| SLVT | 222.7 | 24.9 |

Clock periods for the experiments have to lie between 223 and 441 ps. Above
441 ps every cell can be SRAM and there is nothing to decide; below 223 ps no
assignment meets timing. We plan to use two or three periods, for example
260, 300 and 360 ps, because the amount of choice varies across the window.

**Baseline Vt assignment (cost = total leakage).**

| Clock (ps) | SRAM | RVT | LVT | SLVT | Leakage (nW) | Run time |
|---|---|---|---|---|---|---|
| 360 | 2392 | 552 | 42 | 0 | 125.8 | 96 s |
| 300 | 1318 | 1393 | 265 | 10 | 387.3 | 184 s |
| 260 | 822 | 1113 | 1000 | 51 | 1445 | 226 s |

For scale, the all-SRAM design leaks 87.6 nW and the all-LVT design 3728 nW.
These leakage figures average each cell over its listed states, as if all
states were equally likely; real state probabilities need your evaluator.

## 6. Interfaces

**Fixed (already in code).**

- *Leakage table.* `load_leakage(lib_dir, corner)` returns
  `table[cell][flavour]`, with `cell` the base name (`"NAND2xp33"`) and
  `flavour` one of `"SRAM"`, `"RVT"`, `"LVT"`, `"SLVT"`. Each entry has:
  - `pins`: every pin named in the library's leakage conditions, sorted
    alphabetically. **Outputs are included** (`A, B, Y` for a NAND2;
    `CLK, D, QN` for a flip-flop), because a flip-flop's leakage depends on
    its stored value.
  - `leak`: array of length `2 ** len(pins)`. The state index is
    `sum(value(pins[i]) << i)`, so `pins[0]` is the least significant bit.
  - States that cannot occur (NAND2 with A=1, B=1, Y=1) are NaN on purpose:
    a wrong net value then shows up as NaN in the leakage sum.
- *Instance and cell names.* `opt/sta.py` gives, for the loaded netlist,
  `cell[instance]` (base cell name) and `flavour[instance]`. Instance names
  are Yosys's, such as `_2402_`.
- *Vt assignment file.* `opt/vt_assign.py` writes JSON with an `assignment`
  object mapping instance name to flavour, plus the clock period, the cost
  used, statistics, and the SHA-256 of the netlist and constraints file.
- *Cost function.* The optimiser takes any object with three methods:
  - `delta(instance, new_flavour)`: change in cost if that instance moved to
    that flavour, without changing anything;
  - `commit(instance, new_flavour)`: make the move permanent;
  - `total()`: current cost.

  `LeakageCost` in `opt/vt_assign.py` is the baseline. The security cost is
  a second class with the same methods, and plugs into the same loop.

**Proposed, to agree between us.**

- *Cell-state array.* NumPy integer array, shape (executions, cell
  instances), each entry the state index defined above, with the instance
  order stored alongside. Plus arrays for key, nonce and each column's
  S-box output per execution.
- *Scoring.* From the state array and an assignment: the signal per column,
  and the change in signal for one candidate swap. That is what the security
  cost's `delta` will call.

## 7. Your part

From the proposal: Ascon golden model and verification; leakage traces and
scoring; LiCSPA RTL; CPA attack.

**First tasks, in order.**

1. **Golden model.** Python Ascon-AEAD128 checked against the NIST
   SP 800-232 test vectors, exposing the state after each round. Take the
   byte order and IV from the standard, not from the older competition
   version.
2. **Check the S-box table** in `tb/ascon_sbox_ref.v` against the standard
   or your model. It was typed from memory. The full core has since matched
   official test vectors, so an error is unlikely, but it costs a minute.
3. **Netlist evaluator.** This is the piece everything now waits on.
   - Read `build/ascon_core.json`.
   - For a batch of (key, nonce) pairs, set the state flip-flops to IV, key
     and nonce, the round counter to 0 and `running` to 1, and compute the
     value of every net. With NumPy this is one vectorised pass over the
     cells in topological order.
   - Cell functions for the 23 cell types can come from the liberty
     `function` attributes or from `build/asap7_RVT_TT_sim.v`.
   - Check it: the D inputs of the state flip-flops must equal your golden
     model's round-1 output.
   - Turn pin values into state indices (section 6).
4. **Scoring and the security cost.** Signal per column as defined below,
   and its change for one swap.

**The signal.** For S-box column j in round 1, the inputs are one IV bit,
two key bits and two nonce bits. The target value v is that column's S-box
output.

- For each cell i in flavour f, mu_i(v) is its mean leakage over executions
  where the output is v.
- S(v) is the sum of mu_i(v) over all cells; the signal is the variance of
  S(v) over v.
- **Compute it with the key fixed and the nonce varying, then average over
  several keys.** With random keys, cells that depend only on the key look
  like signal, but to an attacker facing one fixed key they are a constant
  offset.
- With a fixed key only 4 of the 32 output values occur per column, and over
  all keys only 16 (the IV bit is fixed too).
- A swap of cell i from f to f' changes S(v) by mu_i,f'(v) - mu_i,f(v), so
  the new variance can be computed exactly without touching other cells.

## 8. Things that will otherwise cost you time

- **The netlist is not in git.** `build/` is ignored, so each of us
  generates it. Until we commit a frozen copy, use the hash check in
  section 2.
- **ASAP7's small flip-flops have only an inverted output (QN).** Yosys adds
  an inverter per flip-flop, which is where most of the 330 INVxp33 cells
  come from. They sit on the state register outputs, so they leak with the
  state.
- **Synthesis resizes gates.** ABC's `buffer` step turned most XOR and XNOR
  cells into the `x2` size. Leakage tables are per cell name, so look up
  exactly the cell named in the netlist.
- **Yosys 0.9 takes one liberty file per command.** That is why
  `flow/merge_lib.py` exists.
- **A Vt swap can make timing worse.** A faster flavour has about 15-20%
  more input capacitance, so swapping a cell that hangs off a critical net
  slows that net's driver. Measured on the toy: up to -1.7 ps.
- **OpenSTA's `source` carries on after an error.** A broken constraints
  file leaves the design unconstrained, and OpenSTA then reports a huge
  positive slack. `opt/sta.py` refuses to run in that case; a hand-written
  Tcl script will not.
- **Slack is read through internal OpenSTA commands** (`worst_slack_cmd`,
  `Vertex_slacks`). A newer OpenSTA may need different calls; they are
  marked in `opt/sta_server.tcl`.
- **Scripts need Unix line endings.** `.gitattributes` enforces this; if a
  script fails with `$'\r': command not found`, that is the cause.

## 9. Working together

- We both push to `master`. Pull before starting and again before pushing.
- Keep to your own files where possible; conflicts only arise when we both
  edit the same lines.
- Use a branch only for a change that could break the other person's work,
  such as a change to an interface in section 6.
- Record the random seed of every experiment.

## 10. Remaining plan

About 16 days are left.

| Dates | Ankush | Ayush | Checkpoint |
|---|---|---|---|
| 12-15 Nov | Done early: core, flow, baseline loop. Next: freeze netlist | Golden model; netlist evaluator | Cell states for the full core |
| 16-19 Nov | Security cost in the loop; clock periods fixed | Scoring; trace generator | Headroom check; baseline and optimised assignments |
| 20-23 Nov | Template attack, TVLA | LiCSPA primitive; CPA | First optimised-vs-baseline comparison |
| 24-27 Nov | Sweeps; method sections | Sweeps; evaluation section | Report and presentation |

**Headroom check (about 18 Nov).** As soon as scoring exists, compare the
signal of the baseline assignment with the security-driven one at the same
clock period. If they differ by only 20-30%, the 3x claim is in doubt and we
need to know early.

**If we fall behind, cut in this order:** the ILP reference, the SS corner,
the secondary attack point, then LiCSPA. Dropping LiCSPA costs the most,
because the proposal names it as a comparison.
