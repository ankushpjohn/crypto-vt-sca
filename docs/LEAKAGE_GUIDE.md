# Leakage half: code, how to run it, and what it showed

For Ayush, 16 November 2026 (second version: adds LiCSPA and the results of a
full re-check). Covers handoff tasks 1–4, the headroom check, traces, CPA with
the proposal's metrics (SNR per column, traces to success with confidence
intervals), and LiCSPA reimplemented in ASAP7.

Everything was run on a netlist synthesised from the repository with Yosys 0.9
and timed with OpenSTA 2.0.17: 3040 cells, 28 types, 363.03 um², window
455.0 / 353.7 / 272.2 / 233.3 ps — identical to the handoff — and the instance
names match Ankush's files in `results/vt/`. None of Ankush's files is
modified.

## 0. Put the files in the repository

| File | What |
|---|---|
| `eval/check_model.py` | Tasks 1, 2: golden model, S-box table |
| `eval/netlist_eval.py` | Task 3: netlist evaluator, cell states |
| `eval/scoring.py` | Task 4: signal, security cost, headroom table |
| `eval/run_security_assign.py` | Security-driven Vt assignment (Ankush's loop, unchanged) |
| `eval/traces.py` | Trace generator |
| `eval/cpa.py` | CPA, SNR per column, traces to success with confidence intervals |
| `rtl/licspa_core.v` | LiCSPA: the core with two-path LVT flip-flop primitives |
| `flow/synth_licspa.sh` | Synthesises one LiCSPA configuration |
| `flow/licspa_core.sdc` | Ankush's constraints plus the LiCSPA `ctl` inputs |
| `eval/licspa_sweep.py` | LiCSPA: random configurations, timing closure, scores |
| `docs/LEAKAGE_GUIDE.md` | This file |

In your WSL terminal:

    cd ~/projects/crypto-vt-sca
    git pull origin master
    tar xzf /mnt/c/Users/ayush/Downloads/leakage_half.tar.gz
    git status                                  # the 11 new files, in red
    git add eval/*.py rtl/licspa_core.v flow/synth_licspa.sh flow/licspa_core.sdc docs/LEAKAGE_GUIDE.md
    git commit -m "Netlist evaluator, scoring, security cost, traces, CPA, LiCSPA"
    git pull origin master
    git push origin master

If you used the first bundle, this one replaces all of its files. Never
`git add .` (it would pick up `libs/` or `build/`). Commit result files
(`results/vt/security_*.json`, `results/licspa/*.json`) only after generating
them on your machine, so they carry your netlist hash.

## 1. Golden model and S-box (tasks 1 and 2)

    python3 eval/check_model.py ~/LWC_AEAD_KAT_128_128.txt

Compares three independent sources: the S-box implied by the model's
bitsliced round, the table in `tb/ascon_sbox_ref.v`, and the SP 800-232 table
typed into the script; also the 12 round constants and the IV. The KAT file is
in github.com/ascon/ascon-c, folder `crypto_aead/asconaead128/`. Expected:
`KAT entries checked: 1089, mismatches: 0` and `RESULT: all checks passed`.

## 2. Netlist evaluator (task 3)

    python3 eval/netlist_eval.py

Expected: six lines ending `OK`, then `RESULT: all checks passed` (3 s).

How it works:

1. **Reads the Verilog netlist, not the JSON**, because only the Verilog
   instance names (`_2402_`) match OpenSTA, `opt/sta.py` and the assignment
   files.
2. **Cell functions from the liberty `function` attributes**, compiled into
   NumPy expressions; the flip-flop form (`QN = !stored`, `next = D`) is
   checked.
3. **Clocks the netlist like the testbench** instead of forcing flip-flops by
   name: cycle 0 reset (flip-flops start random), cycle 1 `start`, cycle 2 =
   primary attack point, cycle 3 = secondary.
4. **One vectorised pass** over the combinational cells in topological order.
5. **Cell states** as the handoff defines them, `uint8`, shape
   `(executions, cells)`, column order `core.instances`.

The check: outputs equal `init_states(...)[0]` in the attack cycle and
`init_states(...)[1]` one cycle later, `busy=1`, `done=0`, for both clock levels
and three input-port conventions; and no cell is ever in a state the library
marks impossible — one wrong net anywhere would break that.

Extra input ports (LiCSPA's `ctl`) can be randomised per execution:
`--random-ports ctl`, or `Core(..., random_ports=("ctl",))`.

**Conventions to agree with Ankush:** `clk_level` (default 0, the level the
clock is stopped at) and `inputs` (default `hold`: the key/nonce ports still
carry key and nonce in the attack cycle).

## 3. Signal and security cost (task 4)

    python3 eval/scoring.py results/vt/*.json

Data: 8 keys × 4096 nonces. Keys come in groups of four so that, in every
column, each key class appears once per group. Per cell, flavour, key, column
and nonce class the mean leakage is stored once, so a swap's effect is exact
and costs microseconds.

Two metrics, always both reported:

- **`var`** — the handoff's definition (per key and column, variance over the
  4 nonce classes of the summed class means; summed over columns, averaged
  over keys).
- **`key`** — only the part that depends on key and nonce together. With the
  key fixed, the column output is a one-to-one function of the two nonce
  bits, so `var` also counts nonce-only leakage (flip-flops holding the nonce),
  which looks the same under every key guess. On the all-RVT design `key` is
  65% of `var`. Decision for Ankush; I suggest optimising `var` and reporting
  both.

Estimator: class means from finite samples bias a variance upwards. `split`
(product of two independent halves) removes the bias and is used for every
reported number, on held-out data (seed 7). It must not be the optimiser's
objective: it is unbounded below, and the optimiser drove it to −7 × 10⁶ pW².
The optimiser uses `plain`.

## 4. Security-driven assignment and the headroom check

    python3 eval/run_security_assign.py --period 300 --out results/vt/security_var_300ps.json
    python3 eval/run_security_assign.py --period 260 --out results/vt/security_var_260ps.json
    python3 eval/run_security_assign.py --period 360 --out results/vt/security_var_360ps.json
    python3 eval/scoring.py results/vt/*.json

1.5–3.5 min each. Held-out results (leakage nW, signal pW²):

| Period | Assignment | Leakage | `var` | `key` | `var` cut | `key` cut |
|---|---|---|---|---|---|---|
| 260 ps | baseline | 1672 | 12 743 599 | 4 597 683 | | |
| 260 ps | security | 3991 | 2 113 996 | 1 194 355 | 6.0× | 3.8× |
| 300 ps | baseline | 514 | 2 547 900 | 1 211 149 | | |
| 300 ps | security | 2190 | 96 641 | 60 112 | **26×** | **20×** |
| 360 ps | baseline | 143 | 50 094 | 32 017 | | |
| 360 ps | security | 581 | 20 733 | 15 174 | 2.4× | 2.1× |

All meet timing in a fresh OpenSTA. The headroom concern does not
materialise. The price is power: 2.4–4.3× more total leakage. `--leak-weight`
trades the two (the signal part of the cost is scaled to 1 for an all-RVT
design, the leakage part is in pW); a sweep (0, 1e-6, 1e-5, 1e-4) gives a
Pareto curve for the report.

## 5. LiCSPA (proposal reference [2])

**What it is.** LiCSPA (ISCAS 2025, arXiv 2402.03196) replaces randomly chosen
state-register flip-flops with a primitive of two LVT flip-flops: a random
control bit `CTL` picks which one captures; the other holds its old value
through a feedback loop; a mux selects the output. Optionally each flip-flop
gets a random drive strength. The configuration is chosen by sweeping random
ones. The paper evaluates AES in a 28 nm library under CPA (Hamming distance)
and reports 79–96× more traces at about 2–6% area.

**Our reimplementation (`rtl/licspa_core.v`).** The Ascon core with each
protected state bit made a primitive; `ctl` is a 320-bit input, one bit per
state bit. One interpretation was needed: the paper requires both paths to
give the same output but does not say when `CTL` changes. We hold `ctl`
constant for a run (a random value per encryption from an RNG outside the
core), so the output mux can use it directly. A per-cycle `CTL` would need a
third flip-flop per primitive. Write this assumption in the report.

**The flow (`eval/licspa_sweep.py`), per configuration:**

1. Draw `--bits` random state bits (default 24, which gives ≈5% area, the
   paper's range).
2. Synthesise (`flow/synth_licspa.sh`, same recipe as the core) and find the
   primitive flip-flops from their source-line attribute.
3. With `--drive random`, give each primitive flip-flop DFFHQNx1/x2/x3 at
   random (ASAP7's sizes; the paper used X2/X4/X8).
4. Check the netlist against the golden model with random `ctl`.
5. Pin the primitive flip-flops to LVT; give every other cell a timing-driven
   Vt with Ankush's baseline loop — the same treatment as the baseline.
6. Score on the same held-out data as every other design.

    python3 eval/licspa_sweep.py --period 300 --configs 8 --bits 24
    python3 eval/licspa_sweep.py --period 300 --configs 8 --bits 24 --drive random --seed 2026

About 2.5 min per configuration. Each writes `results/licspa/<tag>_cfg<r>.json`
(same format as the other assignment files, plus the mask, primitives and
sizes) and a `_summary.json`.

**Results at 300 ps (8 configurations each, all meet timing):**

| Design | Area (um²) | Leakage (nW) | `var` (pW²) | `key` (pW²) |
|---|---|---|---|---|
| Timing-driven baseline | 363.0 | 514 | 2 547 900 | 1 211 149 |
| Security-driven | 363.0 | 2190 | 96 641 | 60 112 |
| LiCSPA, fixed drive: mean (best) | 382.0 (+5.2%) | 1009 | 11 299 606 (6 469 164) | 4 487 880 (2 980 809) |
| LiCSPA, random drive: mean (best) | 385.1 (+6.1%) | 960 | 9 153 260 (3 603 646) | 5 086 525 (1 698 501) |

Every LiCSPA configuration has a **larger** signal than the baseline. The
reason is visible in the assignments: the primitive puts a mux between the
state flip-flops and the round logic, on the critical path, so timing closure
needs about 630 LVT cells instead of 359. Those extra fast cells leak more and
carry more key-dependent signal. The two best configurations both drew large
flip-flops (faster clock-to-output), needed fewer LVT cells, and came closest
to the baseline.

## 6. Traces

    python3 eval/traces.py --assign results/vt/leakage_300ps.json \
        results/vt/security_var_300ps.json --experiments 20 --traces 400000 \
        --seed 2026 --out results/raw/traces_300ps.npz
    python3 eval/traces.py --netlist build/licspa/<best tag>/licspa_core.v \
        --assign results/licspa/<best tag>.json --experiments 20 --traces 400000 \
        --seed 2026 --out results/raw/traces_300ps_licspa.npz

One trace = total leakage (pW) at the attack point; key fixed per experiment,
nonce varying. With the same `--seed`, `--experiments` and `--traces`, two
files have identical keys and nonces, so designs can be compared trace for
trace. Noise is added by the attack. 4 × 400 000 traces for two designs take
about 1.5 min and 100 MB.

## 7. CPA

    python3 eval/cpa.py results/raw/traces_300ps.npz --model distance
    python3 eval/cpa.py results/raw/traces_300ps_licspa.npz --model distance

Per column, 4 hypotheses for `(key0[j], key1[j])`. Models:

- `hw` — Hamming weight of the S-box output. **Fails here:** per-column
  success stays near chance (21–37% vs 25%) even at 60 000 traces.
- `profiled` — model learned on a profiling device with known keys (same
  design, separate seed), ranked by correlation.
- `distance` — same profile, ranked by squared distance between observed and
  predicted centred class means. Correlation ignores scale, so hypotheses
  with the same shape stay confused; distance does not. **Use this one.**

The output gives, per design: SNR per column (mean over columns), success at
the largest trace count per column and for the full key, the traces needed
for 50/80/90% per-column success, and a 90% confidence interval for each from
a bootstrap over the keys.

**Profile size matters.** The profile defaults to 131 072 nonces per key
(about 10 min per design). With 4096, as in my first version, the profile's
own noise (~40 pW per class mean) is close to a column's whole signal and it
handicaps low-signal designs most: it inflated the 300 ps ratio to 150×. The
corrected numbers below changed little from 32 768 to 131 072, so they have
converged.

**Results at 300 ps** (4 keys × 400 000 traces, noise 0; counts are on a
20-point log grid, so each is "between this and the previous grid point"):

| Design | SNR per column | Per-col. success @400k | N for 50% | N for 80% | N for 90% |
|---|---|---|---|---|---|
| Baseline | 1.03e-2 | 0.965 | 162 [93, 162] | 2 643 [1 513, 2 643] | 8 064 [8 064, 8 064] |
| Security-driven | 4.73e-4 | 0.895 | 4 616 [4 616, 4 616] | 42 973 [24 603, 75 061] | > 400 000 [75 061, > 400 000] |
| LiCSPA (best) | 8.22e-3 | 0.973 | 496 [283, 496] | 2 643 [2 643, 4 616] | 8 064 [8 064, 8 064] |

Brackets: 90% bootstrap interval over keys. Versus the baseline, the
security-driven assignment needs **28×** (50%), **16×** (80%) and **more than
9×** (90%) the traces; LiCSPA needs 3.1×, 1.0× and 1.0×. The SNR ratio (22×)
agrees with the signal ratio (26×). The 260 and 360 ps attack numbers from my
first version used the small profile; rerun them with the commands above.

**Full-key recovery.** At 400 000 traces, full-key success was 0/4 keys for the
baseline and the security design and 1/4 for LiCSPA. Per-column success
stops below 1 for a reason I tested: the round's linear layer mixes three
columns, so a column's class means also depend on other columns' key bits,
which a profile averaged over random keys cannot capture. Rebuilding the
profile with the attacked key's other bits fixed corrected 16 of 26 failing
columns. So "90%-success key recovery" in the proposal's claim needs one of:

1. per-column success (as above) or guessing entropy, stated as such;
2. full-key numbers from Ankush's template attack, if it models neighbouring
   columns jointly;
3. a multi-column CPA (3 columns, 64 hypotheses), extra work.

## 8. Errors found in the re-check, all fixed

| Where | Problem | Fix |
|---|---|---|
| `cpa.py` | Profile of 4096 nonces too noisy; 300 ps ratio overstated (150× → 28×) | Default 131 072, convergence checked |
| `scoring.py` | Building the data in one block used 3 GB at large nonce counts (crashed) | Processed in chunks of 4096 nonces |
| `cpa.py` | Bootstrap interval crashed when a level was never reached | Fixed; "not reached" shown as `>N` |
| `netlist_eval.py` | Could not read concatenated `assign` statements or escaped names | Parser extended (needed for LiCSPA) |
| `synth_licspa.sh` | Yosys wrote assigns OpenSTA 2.0.17 cannot parse | Generate-block names hidden before cleanup |
| Proposal metrics | SNR per column and confidence intervals were missing | Added to `cpa.py` |
| `eval/liberty_leakage.py` (Ankush's) | Area regex needs a trailing `;`; the INVBUF library omits it, so 42 buffer/inverter types (including the 349 `INVxp33`) get NaN area. Leakage is unaffected | Not edited; `licspa_sweep.py` reads areas itself (matches Yosys to 5 decimals). Tell Ankush: change `;` to `;?` in `_AREA_RE` |

Everything else re-checked without change: model (1089/1089 KATs), S-box,
evaluator (both netlists), metric formulas and class encoding (consistent
between `scoring.py` and `cpa.py`), held-out scores (reproduced exactly after
the chunking change), trace files (identical keys and nonces across designs).

## 9. Plan to 28 November

| Dates | You | Checkpoint |
|---|---|---|
| 16–17 Nov | Install, run sections 1–4, push. Send Ankush the decisions below | Ankush has the cost class |
| 17–18 Nov | LiCSPA sweeps at 260/300/360 ps (2 × 8 configs each, ~40 min per period) | All three designs per period |
| 19–21 Nov | 20-key trace sets and CPA, all designs and periods; noise sweep (0, 500, 2000 pW) | First full comparison |
| 22–23 Nov | `--leak-weight` sweep at 300 ps | Pareto figure |
| 24–27 Nov | Figures (success curves with intervals, Pareto, LiCSPA table), evaluation section | Report and slides |

**Decisions to send Ankush:**

1. `var` or `key` as the optimised metric.
2. Clock level and input-port contents at the attack point.
3. Rewording the 90%-full-key claim (section 7).
4. Whether the 2–4× power increase is acceptable, or to use `--leak-weight`.
5. The LiCSPA `ctl` interpretation (held per run).
6. The area-regex fix in his `eval/liberty_leakage.py`.
