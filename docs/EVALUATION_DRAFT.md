# Evaluation (draft)

Draft of the evaluation section, written from the committed results. Every number below comes from
`results/figures/summary.md` (regenerate with `python3 eval/make_figures.py`) or from the result files
it reads. Items in **[square brackets]** are decisions or additions still open. Figure numbers are
placeholders.

---

## 1. Experimental setup

**Design.** The round-per-cycle Ascon-AEAD128 initialisation core, synthesised with Yosys 0.9 onto the
ASAP7 7.5-track library: 3040 cells (326 flip-flops, 2714 combinational), 363.0 µm². Every cell
exists in four threshold-voltage flavours (SRAM, RVT, LVT, SLVT, slowest to fastest) with identical
function, pins and footprint, so a Vt assignment changes neither the logic nor the area. All
results use the typical corner (TT, 0.70 V, 25 °C). With every cell in one flavour, the minimum
clock period ranges from 233.3 ps (all SLVT) to 455.0 ps (all SRAM). We evaluate three periods
inside this window: 260, 300 and 360 ps.

**Attack point.** The clock is stopped one cycle after `start`, held low. At that moment the state
register holds IV ‖ key ‖ nonce and the round-1 logic has settled. S-box column *j* of round 1
takes IV bit *j* (fixed), two key bits and two nonce bits, so with the key fixed its output takes
four values, one per nonce class.

**Leakage model.** The static power of an execution is the sum, over all cells, of the leakage the
ASAP7 library lists for that cell's flavour and its logic state (the values on all its pins,
outputs included). Cell states come from a vectorised gate-level evaluation of the synthesised
netlist (`eval/netlist_eval.py`). Traces are noise-free unless stated; measurement noise, where
used, is additive Gaussian.

**Designs compared** (all at the same clock period, all verified in a fresh OpenSTA run: setup met;
hold slack ≥ 42.8 ps for the plain core, ≥ 28.2 ps for LiCSPA):

| Design | How the Vt flavours are chosen |
|---|---|
| Timing-driven baseline | Greedy optimiser: start all-SRAM, speed cells up until timing is met, then slow cells down where timing allows; cost = total leakage |
| Security-driven | The same optimiser and loop; cost = key-dependent leakage signal (§2) |
| Security-driven, low power | As above, cost = signal + *w* × total leakage, *w* = 10⁻⁶ per pW (the signal term is normalised to 1 for an all-RVT design) |
| LiCSPA [2] | 24 randomly chosen state bits (7.5% of the state register) each replaced by two LVT flip-flops with a random path select and an output multiplexer; all other cells timing-driven, as in the baseline. Eight configurations with the minimum flip-flop size and eight with random sizes (DFFHQNx1/x2/x3) per period; the configuration with the lowest signal is attacked |

**[LiCSPA assumptions to state.]** The original evaluates AES in a 28 nm library under CPA. In our
reimplementation the path-select bit is random per encryption and held for the whole run, so the
output multiplexer can use it directly; ASAP7 offers flip-flop sizes x1–x3 instead of X2–X8; and
timing is closed with the same greedy loop as the other designs.

**Signal metric.** For column *j*, key *k* and nonce class *c*, let *S*(*k*, *j*, *c*) be the summed
mean leakage of all cells over executions in that class. The signal is

  `var` = mean over keys of Σⱼ Var_c *S*(*k*, *j*, *c*),

the variance of the class means with the key fixed and the nonce varying, summed over the 64
columns and averaged over 8 keys. A key that is fixed contributes only a constant offset, which an
attacker cannot use. We also report `key`, the part of `var` that depends on key and nonce jointly:
the remainder is nonce-only leakage, identical under every key hypothesis. Class means are computed
from 4096 nonces per key. The optimiser is trained on one data set (seed 1); every reported signal
is computed on a held-out set (seed 7) with an estimator that removes the finite-sample bias of a
variance (product of two independent halves).

**Traces and attacks.** For each design: 20 random keys (seed 2026) × 400 000 random nonces each; all
designs see identical keys and nonces. Per column, the attacker ranks the four hypotheses for the two
key bits:

- *Textbook CPA:* Pearson correlation with the Hamming weight of the predicted S-box output.
- *Profiled CPA:* the attacker first builds, on a profiling device of the same design with known
  keys (8 keys × 131 072 nonces, seed 31), the mean leakage for every (key class, nonce class) pair
  of every column. A hypothesis is scored by the squared distance between the observed and the
  predicted centred class means.

We report the per-column success rate (fraction of the 64 two-bit guesses that are correct, averaged
over the 20 keys), the number of traces *N* needed for 50%, 80% and 90% per-column success with a 90%
bootstrap interval over the keys (500 resamples), and the SNR per column (variance of the class
means, corrected for their estimation noise, over the mean within-class variance). *N* is read off a
40-point logarithmic grid from 10 to 400 000 traces, about 31% per step.

---

## 2. Verification

- **Reference model.** The Python model reproduces all 1089 official Ascon-AEAD128 known-answer
  tests. Its S-box, the testbench's S-box table and the table in SP 800-232 agree; the twelve round
  constants and the IV match the standard.
- **Netlist evaluator.** For random keys and nonces, both clock levels and three conventions for the
  input ports during the attack cycle, the evaluated state register equals the model's state before
  and after round 1, and `busy`/`done` are correct, with zero mismatches. No cell is ever in a logic
  state the library marks as impossible; a single wrong net anywhere would violate that. The same
  check passes on every LiCSPA netlist, with random path-select bits.
- **Reproducibility.** The flow is deterministic. The security-driven assignments and their scores
  were reproduced exactly, cell for cell, on two different machines.

---

## 3. Results

### 3.1 Key-dependent signal and its power cost

**Table 1.** Held-out signal and total static leakage.

| Period | Design | Leakage (nW) | vs baseline | `var` (pW²) | Signal reduction |
|---|---|---|---|---|---|
| 260 ps | Baseline | 1672 | 1.00× | 12 743 599 | – |
| | Security-driven | 3991 | 2.39× | 2 113 996 | 6.0× |
| | Low power (*w* = 10⁻⁶) | 2257 | 1.35× | 1 916 820 | 6.6× |
| 300 ps | Baseline | 514 | 1.00× | 2 547 900 | – |
| | Security-driven | 2190 | 4.26× | 96 641 | 26.4× |
| | Low power | 726 | 1.41× | 97 688 | 26.1× |
| 360 ps | Baseline | 143 | 1.00× | 50 094 | – |
| | Security-driven | 581 | 4.05× | 20 733 | 2.4× |
| | Low power | 159 | 1.11× | 19 260 | 2.6× |

Optimising for the signal reduces it at every period, most at 300 ps (26×). The gain depends on how
much freedom timing leaves. At 360 ps most cells are already SRAM in any valid assignment (2402 of
3040 in the baseline), so little can change. At 260 ps so many cells must be fast that the choice
is again constrained. The middle of the window leaves the most room.

The signal-only cost reaches its goal by using many fast cells whose key-dependent parts are small
or cancel (336 SLVT cells against 21 in the baseline at 300 ps), so total leakage rises by 2.4–4.3×.
Adding a small leakage term removes most of that cost without losing security: with *w* = 10⁻⁶ the
signal reduction is unchanged (26.1× against 26.4× at 300 ps) while total leakage is only 1.11–1.41×
the baseline's. Figure [2] shows the trade-off at 300 ps across *w* = 0, 10⁻⁶, 10⁻⁵ and 10⁻⁴: the
curve has a sharp knee at 10⁻⁶, and even *w* = 10⁻⁴ (2% more leakage than the baseline) still cuts
the signal 2.9×.

### 3.2 Key recovery

**Table 2.** Profiled CPA, no added noise: traces to per-column success [90% interval] (ratio to the
baseline at the same period).

| Period | Design | SNR | *N* for 50% | *N* for 80% | *N* for 90% |
|---|---|---|---|---|---|
| 260 ps | Baseline | 9.4·10⁻³ | 341 [260, 341] | 3 006 [3 006, 3 944] | 15 347 [11 696, 26 426] |
| | Security-driven | 1.4·10⁻³ | 2 291 (6.7×) | >400 000 (>133×) | >400 000 (>26×) |
| | Low power | 1.6·10⁻³ | 1 745 (5.1×) | >400 000 (>133×) | >400 000 (>26×) |
| | LiCSPA | – | no configuration met timing | | |
| 300 ps | Baseline | 1.0·10⁻² | 198 [151, 260] | 2 291 [1 745, 2 291] | 6 792 [5 176, 8 913] |
| | Security-driven | 4.8·10⁻⁴ | 3 944 [3 006, 3 944] (20×) | 59 710 [34 677, 59 710] (26×) | >400 000 (>59×) |
| | Low power | 5.6·10⁻⁴ | 3 006 [2 291, 3 944] (15×) | 78 352 [59 710, 102 814] (34×) | >400 000 (>59×) |
| | LiCSPA | 8.2·10⁻³ | 260 [260, 448] (1.3×) | 2 291 [2 291, 3 006] (1.0×) | 5 176 [5 176, 6 792] (0.8×) |
| 360 ps | Baseline | 7.7·10⁻³ | 198 [151, 260] | 1 745 [1 330, 2 291] | 8 913 [5 176, 11 696] |
| | Security-driven | 2.6·10⁻³ | 448 [341, 448] (2.3×) | 5 176 [5 176, 6 792] (3.0×) | 45 503 [34 677, 304 830] (5.1×) |
| | Low power | 3.0·10⁻³ | 448 [341, 588] (2.3×) | 5 176 [5 176, 6 792] (3.0×) | 59 710 [34 677, >400 000] (6.7×) |
| | LiCSPA | 1.9·10⁻³ | 1 745 [772, 2 291] (8.8×) | 26 426 [26 426, 34 677] (15×) | >400 000 (>45×) |

Figure [1] shows the full success-rate curves.

At 300 ps the security-driven assignments raise the number of traces 15–34× at 50% and 80% success,
and beyond the 400 000 available at 90% (more than 59×). Even comparing the most favourable end of
the baseline's interval with the least favourable end of the security design's, the factor at 50%
stays above 11× (8.8× for the low-power design). At 260 ps the attack does not reach 80% per-column success within 400 000 traces against
either security design, whereas the baseline needs about 3000. At 360 ps the gain is 2.3× at 50%,
3.0× at 80% and 5–7× at 90%, consistent with the small signal reduction there.

Three independent measures agree. At 300 ps the signal falls 26×, the per-column SNR 22× (18× for
the low-power design), and the traces needed for 50–80% success rise 15–34×.

The low-power designs are statistically indistinguishable from the signal-only designs: their
intervals overlap at every period and success level.

### 3.3 Measurement noise

At 300 ps, adding Gaussian noise of σ = 500 pW changes almost nothing, and σ = 2000 pW roughly
doubles the traces needed for every design, without changing their ratio (baseline 448 / 3 944;
security-driven 8 913 / 102 814 at 50% / 80%: still 20× and 26×). The leakage of the 63 columns not
under attack already varies by about 2 nW from trace to trace, so it acts as noise comparable to
the largest added level. Real measurement noise would therefore lengthen attacks on all designs
alike, and the protection factor would remain.

### 3.4 The textbook attack fails

CPA with the Hamming-weight model reaches only 0.39 (baseline) and 0.27 (security-driven)
per-column success after 400 000 traces at 300 ps, against 0.25 for guessing. The static leakage of
these cells does not follow the Hamming weight of the S-box output. This is why all comparisons use
the profiled attacker, which is the stronger and more realistic adversary for static-power analysis.

### 3.5 LiCSPA

- **260 ps:** none of the 16 configurations met timing with the greedy loop (worst slack −2.2 to
  −29.9 ps). The output multiplexer lies on the critical path, and the pinned LVT flip-flops are
  slower than the SLVT cells the plain design can use there.
- **300 ps:** all configurations met timing at +4.6–8.2% area, but every one has a *larger* signal
  than the baseline (best 1.4×, means 3.6× and 4.5×), and the best configuration gives no
  protection (1.0–1.3× at 50–80%, 0.8× at 90%). To close timing around the multiplexer, the
  optimiser needs 460–682 LVT cells instead of the baseline's 359, and these fast cells leak more key-dependent
  signal than the randomised flip-flops hide.
- **360 ps:** with more timing slack the extra fast cells are no longer needed, and LiCSPA becomes
  effective: 8.8× at 50% and 15× at 80%, better than our assignments at this period (2.3×, 3.0×), at
  +7.8% area and 2.0× the baseline's leakage (292 nW, against 159 nW for our low-power design). Its
  `var` is still 2.1× the baseline's, but its SNR is 4.1× lower. LiCSPA works mainly by *adding
  noise*: the idle flip-flop of each pair holds a value unrelated to the current data, and the
  random path select makes the leakage of each protected bit vary from execution to execution.
  Our signal metric counts only the change of the mean leakage with the data, not the noise, so it
  cannot see this effect. This is not a flaw in either method: it is a difference between
  *reducing* the signal and *masking* it with noise, and the two could be combined (§5).

At equal power the comparison at 300 ps is direct: the best LiCSPA configuration leaks 721 nW, our
low-power design 726 nW. Our design reduces the signal 26× at no area cost; LiCSPA increases it 1.4×
at +8% area (Figure [2]).

---

## 4. Discussion and limitations

**Full-key recovery and the claim.** No design reaches 90% full-key recovery within 400 000 traces,
not even the baseline (4–5 of 20 keys fully recovered at 300 ps; 0 for the security-driven designs).
Per-column success saturates below 1 because the round's linear layer combines three S-box
columns: the leakage of the cells after it depends on the key bits of neighbouring columns, which a
per-column profile averages over. [Optional: a diagnostic in which the profile was rebuilt with the
other key bits fixed to the attacked key corrected 16 of 26 failing columns; it was a one-off run
on 4 keys and is not in the repository. Rerun it or leave it out.] In practice, an attacker with
one or two uncertain columns would enumerate the remaining hypotheses. **[Agree the wording with
Ankush.]** We therefore state the result per column: *at equal clock period and zero area overhead,
the security-driven assignment increases the traces needed for 50–90% per-column key recovery by
15–34× at 300 ps (more than 59× at 90%) and by at least 5× at 260 ps; at 360 ps the gain is 2.3–6.7×,
reaching the proposal's 3× target only at 80% success and above.* **[Template-attack results to add:
Ankush.]**

**Limitations.**
- **Simulated traces.** Leakage comes from the library's per-state tables at the typical corner
  only; there is no process or temperature variation, no wire or package effects, and noise is
  Gaussian. Absolute trace counts would differ on silicon; the comparisons between designs, which
  share every modelling assumption, are the meaningful result.
- **Signal-only cost.** As LiCSPA at 360 ps shows, a cost based on the mean leakage ignores
  noise. An SNR-based cost would capture both.
- **Greedy optimisation.** Timing closure and assignment are greedy. A better optimiser might close
  LiCSPA at 260 ps or find stronger assignments; the ILP reference was not implemented.
- **One attack point and corner.** Only the primary attack point (state = IV ‖ key ‖ nonce) and the
  TT corner were evaluated.
- **LiCSPA reimplementation.** It follows the published description, with the assumptions listed in
  §1; the configuration attacked was chosen by lowest signal, which (given the previous point) may
  not be the hardest to attack.
- **Statistics.** 20 keys per design; trace counts are resolved to one grid step (about 31%).

---

## 5. Future work

- **Combine both countermeasures:** keep LiCSPA's randomised flip-flop pairs (noise) and choose the
  remaining cells' flavours with the security cost (signal). The 360 ps result suggests the effects
  would add.
- **An SNR-based security cost,** to account for noise as well as signal.
- **A joint multi-column attack** (three neighbouring columns, 64 hypotheses), to measure full-key
  recovery directly.
- **Other corners and the secondary attack point** (state after round 1).
