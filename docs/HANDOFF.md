# Handoff for Ayush

Status as of 12 November 2026. Written so you can clone the repository and
start work without needing the earlier conversations.

## 1. Where the project stands

**Topic.** Security-aware threshold-voltage (Vt) assignment against
static-power side-channel attacks, on a round-per-cycle Ascon-AEAD128
permutation core in ASAP7. We assign a Vt flavour to every cell of a fixed
netlist, under a fixed clock period, to minimise the key-dependent static
leakage signal. Vt flavours share footprints, so area does not change. The
submitted proposal has the full statement and the claim (at least 3x more
traces to 90%-success key recovery than timing-driven assignment, under CPA
and a template attack).

**Not yet settled.**

- The proposal is not approved yet. We are starting anyway because of time.
- ASAP7 is not on the course brief's library list. Whether the professor
  accepts it is still to be confirmed. The method needs per-input-state
  leakage, which GT3 and GT2N do not provide.
- The deadline is tentatively 28 November, to be confirmed.

**Done so far.** The toy checkpoint is about two-thirds complete:

| Step | State |
|---|---|
| ASAP7 libraries fetched, leakage parser written and checked | Done |
| One S-box column synthesised onto ASAP7 and proven equal to the RTL | Done |
| OpenSTA Vt swap (`replace_cell`) demonstrated | Done |
| Netlist evaluator: every cell's pin values per input | **Not started** |
| First signal number for the toy | **Not started** |

## 2. Getting set up

The flow was developed and tested on WSL Ubuntu 22.04 with Yosys 0.9,
OpenSTA 2.0.17, Python 3.10 and NumPy. Newer tool versions have not been
tried.

    git clone https://github.com/ankushpjohn/crypto-vt-sca.git
    cd crypto-vt-sca

Fetch the libraries (about 80 MB download, 350 MB on disk, not in git).
Pinning the commit gives you exactly the files the results below came from:

    REF=a47d4fdc6534cb3cdfdd9ff76737a899a5bb2ee0 bash flow/get_asap7.sh

Then check that everything works on your machine:

    python3 eval/liberty_leakage.py libs/asap7
    bash flow/synth_toy.sh
    sta -no_init -no_splash -exit flow/sta_swap_test.tcl

Expected: the parser reports 202 cells and Vt ratios of 0.232 / 9.6 / 97.3;
synthesis reports 33 cells and "Equivalence successfully proven!"; the STA
test ends with "RESULT: all checks passed".

## 3. What is in the repository

| File | What it does |
|---|---|
| `flow/get_asap7.sh` | Downloads the ASAP7 7.5-track liberty files (4 Vt flavours, TT and SS) into `libs/asap7/` |
| `eval/liberty_leakage.py` | Parses per-state leakage into NumPy tables: `table[cell][flavour]` |
| `rtl/ascon_sbox.v` | Bitsliced Ascon S-box, `W` columns wide (`W = 64` for the full round) |
| `rtl/sbox_col_toy.v` | Toy design: register, one S-box column, register |
| `tb/ascon_sbox_ref.v` | The S-box as a lookup table, used only to check the RTL |
| `flow/merge_lib.py` | Merges the five ASAP7 libraries of one flavour into one file |
| `flow/synth_toy.sh` | Synthesises the toy with Yosys and proves netlist = RTL |
| `flow/sta_swap_test.tcl` | Times the toy in each flavour and tests single-cell Vt swaps |

Generated files go to `build/` (ignored by git). The toy netlist is written
both as Verilog (`build/sbox_col_toy.v`) and as Yosys JSON
(`build/sbox_col_toy.json`); the JSON is the easier one to read from Python.

## 4. Facts established so far

**Library (TT corner, 25 C, 0.70 V).**

- 202 cells, each in four Vt flavours with identical function, pins and area.
  Cell names end in `_ASAP7_75t_SRAM`, `_R`, `_L` or `_SL`. We call the
  flavours SRAM, RVT, LVT and SLVT, slowest to fastest. "SRAM" is a threshold
  flavour (the highest Vt), not a memory cell.
- Every cell lists leakage per logic state. Example, RVT NAND2xp5 in pW:
  27.1 (A=0,B=0), 50.3 (A=0,B=1), 54.7 (A=1,B=0), 66.3 (A=1,B=1).
- Median leakage relative to RVT: SRAM 0.23x, LVT 9.6x, SLVT 97x.
- Leakage is in pW and time in ps throughout.

**Toy netlist.** 33 cells: 10 DFFHQNx1, 7 INVx1, 6 XNOR2xp5, 4 NAND2xp33,
2 XOR2xp5, 2 NOR2xp33, 1 AOI21xp33, 1 OA21x2.

**Toy timing, whole design in one flavour, 150 ps clock.**

| Flavour | Setup slack (ps) | Hold slack (ps) |
|---|---|---|
| SRAM | -97.48 | 94.65 |
| RVT | -45.62 | 71.80 |
| LVT | 4.09 | 57.17 |
| SLVT | 26.46 | 41.90 |

So the minimum period is about 247 ps all-SRAM and 124 ps all-SLVT.

## 5. Interfaces

**Fixed (already in code).**

- *Leakage table.* `load_leakage(lib_dir, corner)` returns
  `table[cell][flavour]`, with `cell` the base name (`"NAND2xp5"`) and
  `flavour` one of `"SRAM"`, `"RVT"`, `"LVT"`, `"SLVT"`. Each entry has:
  - `pins`: every pin named in the library's leakage conditions, sorted
    alphabetically. **Outputs are included** (`A, B, Y` for a NAND2;
    `CLK, D, QN` for a flip-flop), because a flip-flop's leakage depends on
    its stored value.
  - `leak`: array of length `2 ** len(pins)`. The state index is
    `sum(value(pins[i]) << i)`, so `pins[0]` is the least significant bit.
  - States that cannot occur (NAND2 with A=1, B=1, Y=1) are NaN on purpose:
    a wrong net value then shows up as NaN in the leakage sum.
- *Toy bit order.* In `sbox_col_toy`, `d[4]` is x0 (most significant S-box
  input bit) and `d[0]` is x4. `q` uses the same order for the output.

**Proposed, to agree between us.**

- *Cell-state array.* NumPy integer array, shape (executions, cell
  instances), each entry the state index defined above, with the instance
  order stored alongside. Plus arrays for key, nonce and S-box output per
  execution.
- *Vt assignment file.* Plain text or JSON mapping instance name to flavour.
- *Scoring function.* Takes the state array and an assignment, returns the
  signal per column and the change in signal for a candidate swap.

## 6. Your part

From the proposal: Ascon golden model and verification; leakage traces and
scoring; LiCSPA RTL; CPA attack.

**First tasks, in order.**

1. **Golden model.** Python Ascon-AEAD128 permutation checked against the
   NIST SP 800-232 test vectors. Take the byte order and IV from the
   standard, not from the older competition version: they changed, and they
   decide which key bits land in which S-box column.
2. **Check the S-box table.** `tb/ascon_sbox_ref.v` was typed from memory.
   The RTL is proven equal to it, so if the table is wrong, both are. Please
   compare it once against the standard or your model.
3. **Netlist evaluator and toy signal.** This finishes the toy checkpoint.
   It sits on the border between our parts, so let us agree who writes it.
   The pieces:
   - read `build/sbox_col_toy.json`;
   - for each of the 32 values of `d`, with the registers loaded, compute
     every cell's pin values (cell functions can come from the liberty
     `function` attributes, or a small hand-written table for the 8 cell
     types in the toy);
   - turn those into state indices and look up leakage for a given Vt
     assignment;
   - compute the signal as defined below.

**The signal.** For one S-box column the inputs are one IV bit (x0), two key
bits (x1, x2) and two nonce bits (x3, x4). The target value v is the column's
S-box output.

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

## 7. Things that will otherwise cost you time

- **ASAP7's small flip-flops have only an inverted output (QN).** Yosys adds
  inverters to compensate, which is where several of the toy's INVx1 cells
  come from. They sit on the state register outputs, so they leak with the
  state.
- **Yosys 0.9 takes one liberty file per command.** That is why
  `flow/merge_lib.py` exists.
- **The Yosys equivalence check will not work for the full round.** It
  relies on the toy having no feedback. The full netlist has to be checked
  by simulating it against your golden model.
- **A Vt swap can make timing worse.** A faster flavour has about 15-20%
  more input capacitance, so swapping a cell that hangs off a critical net
  slows that net's driver. Measured on the toy: up to -1.7 ps, against
  +14 to +27 ps for cells on the critical path.
- **Scripts need Unix line endings.** `.gitattributes` enforces this; if you
  edit on Windows and a script fails with `$'\r': command not found`, that
  is the cause.
- **`flow/sta_swap_test.tcl` reads slack through `sta::worst_slack_cmd`**,
  an internal command of this old OpenSTA. A newer version may need a
  different call in that one helper.

## 8. Working together

- We both push to `master`. Pull before starting and again before pushing.
- Keep to your own files where possible; conflicts only arise when we both
  edit the same lines.
- Use a branch only for a change that could break the other person's work,
  such as a change to an interface in section 5.
- Record the random seed of every experiment.

## 9. Remaining plan

About 16 days are left, so the original four-week plan is compressed.

| Dates | Ankush | Ayush | Checkpoint |
|---|---|---|---|
| 12-15 Nov | Full round RTL; flow scripts | Golden model; toy evaluator and signal | Toy end to end |
| 16-19 Nov | Timing window; baseline (total-leakage) loop | Full-round verification; trace generator; scoring | Verified netlist, baseline numbers, headroom check |
| 20-23 Nov | Greedy optimiser; template attack, TVLA | LiCSPA primitive; CPA | First optimised-vs-baseline comparison |
| 24-27 Nov | Sweeps; method sections | Sweeps; evaluation section | Report and presentation |

**Headroom check (about 18 Nov).** Before building the full optimiser,
compare the baseline's signal with a few other assignments that meet the
same timing. If they differ by only 20-30%, the 3x claim is in doubt and we
need to know early.

**If we fall behind, cut in this order:** the ILP reference, the SS corner,
the secondary attack point (after round 1), then LiCSPA. Dropping LiCSPA
costs the most, because the proposal names it as a comparison.
