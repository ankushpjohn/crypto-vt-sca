#!/usr/bin/env python3
"""Figures and tables for the report, built only from the committed result files.

    python3 eval/make_figures.py              # writes results/figures/

Reads (whatever exists; missing files are skipped with a note):
  results/cpa_<p>ps.json            baseline + security-driven attack   (p = 260, 300, 360)
  results/cpa_<p>ps_lw.json         low-power security design (leakage weight 1e-6)
  results/cpa_<p>ps_licspa.json     best LiCSPA configuration
  results/cpa_300ps_hw.json         textbook Hamming-weight CPA
  results/headroom_all.json         signal and leakage of every design (eval/scoring.py --json);
                                    falls back to results/pareto_300ps.json for 300 ps
  results/licspa/*_cfg*.json        every LiCSPA configuration (area, timing, held-out scores)
  results/licspa/licspa_<p>ps_timing_failures.txt

Writes to results/figures/:
  fig_success_curves.{png,pdf}   per-column success vs traces, one panel per clock period
  fig_signal_vs_power.{png,pdf}  300 ps: signal vs total leakage for every design
  summary.md                     all tables (headroom, attack, noise, LiCSPA sweep, HW attack)

Only the standard library, NumPy and matplotlib (Ubuntu: sudo apt install python3-matplotlib).
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results"
OUT = RES / "figures"
PERIODS = (260, 300, 360)
LEVELS = ("0.5", "0.8", "0.9")

# Validated categorical palette (dataviz reference instance, light mode, slots 1-3, all-pairs).
# The two security designs share one hue: solid = signal only, dashed = low-power variant.
DESIGNS = [
    # key,          label,                          colour,    linestyle
    ("baseline",    "Timing-driven baseline",       "#2a78d6", "-"),
    ("security",    "Security-driven",              "#eb6834", "-"),
    ("security_lw", "Security-driven, low power",   "#eb6834", "--"),
    ("licspa",      "LiCSPA (best configuration)",  "#1baf7a", "-"),
]
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"


def load(path):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return None


def notes_add(notes, text):
    notes.append(text)
    print("note:", text)


# --------------------------------------------------------------------------
# Collect attack results per period and design
# --------------------------------------------------------------------------

def attack_results(notes, noise="0.0"):
    """{period: {design: (record, grid, n_traces)}}, noise level as in the JSON keys."""
    out = {}
    for p in PERIODS:
        row = {}
        sources = [
            (f"cpa_{p}ps.json", {f"leakage_{p}ps": "baseline", f"security_var_{p}ps": "security"}),
            (f"cpa_{p}ps_lw.json", {f"security_var_{p}ps_lw1e-6": "security_lw"}),
            (f"cpa_{p}ps_licspa.json", None),     # any name -> licspa
        ]
        for fname, names in sources:
            d = load(RES / fname)
            if d is None:
                notes_add(notes, f"{fname} not found; skipped")
                continue
            res = d["results"].get(noise)
            if res is None:
                notes_add(notes, f"{fname} has no noise {noise} pW results; skipped")
                continue
            grid = d["grid"]
            for name, rec in res.items():
                design = "licspa" if names is None else names.get(name)
                if design:
                    row[design] = (name, rec, grid)
        out[p] = row
    return out


def fmt_n(v, nmax):
    return f">{nmax:,}" if v is None else f"{v:,}"


def ratio(a, b, nmax):
    """Traces ratio design/baseline as text; a or b may be None (= not reached by nmax)."""
    if b is None:
        return "–"
    if a is None:
        return f">{nmax / b:.0f}×" if nmax / b >= 10 else f">{nmax / b:.1f}×"
    r = a / b
    return f"{r:.0f}×" if r >= 10 else f"{r:.1f}×"


# --------------------------------------------------------------------------
# Figure 1: success-rate curves
# --------------------------------------------------------------------------

def fig_success(att, failures, notes):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.size": 9, "axes.edgecolor": INK2, "axes.labelcolor": INK,
                         "xtick.color": INK2, "ytick.color": INK2, "axes.linewidth": 0.6})
    fig, axes = plt.subplots(1, 3, figsize=(10.5, 3.6), sharey=True)
    for ax, p in zip(axes, PERIODS):
        row = att.get(p, {})
        ax.set_xscale("log")
        ax.set_ylim(0, 1.02)
        ax.grid(True, which="major", color=GRID, linewidth=0.6)
        ax.set_axisbelow(True)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        ax.axhline(0.25, color=INK2, linewidth=0.8, linestyle=":")
        nmax = None
        labels = []
        for key, label, colour, ls in DESIGNS:
            if key not in row:
                continue
            _, rec, grid = row[key]
            nmax = grid[-1]
            ax.plot(grid, rec["col_sr"], color=colour, linestyle=ls, linewidth=2,
                    solid_capstyle="round")
            labels.append((rec["col_sr"][-1], label, colour))
        if nmax is None:
            continue
        # Direct labels in a margin right of the line ends, pushed apart (top down) so
        # they never overlap each other or a line.
        ax.set_xlim(7, nmax * 14)
        ax.set_xticks([t for t in (10, 1e2, 1e3, 1e4, 1e5, 1e6) if t <= nmax])
        ax.spines["bottom"].set_bounds(7, nmax)
        from matplotlib.ticker import NullLocator
        ax.xaxis.set_minor_locator(NullLocator())
        ax.text(nmax * 1.25, 0.25, "guessing", va="center", fontsize=7.5, color=INK2)
        labels.sort(reverse=True)
        y_prev = None
        for y, label, colour in labels:
            y2 = y if y_prev is None else min(y, y_prev - 0.075)
            y_prev = y2
            short = {"Timing-driven baseline": "baseline", "Security-driven": "security",
                     "Security-driven, low power": "low power",
                     "LiCSPA (best configuration)": "LiCSPA"}.get(label, label)
            ax.text(nmax * 1.25, y2, short, va="center", fontsize=7.5, color=INK)
        if p in failures and "licspa" not in row:
            ax.text(0.97, 0.06, f"LiCSPA: 0 of {failures[p]} configurations\nmet {p} ps timing",
                    transform=ax.transAxes, ha="right", fontsize=7.5, color=INK2)
        ax.set_title(f"Clock period {p} ps", fontsize=10, color=INK, loc="left")
        ax.set_xlabel("Traces (log scale)")
    axes[0].set_ylabel("Per-column success rate")
    handles = [plt.Line2D([], [], color=c, linestyle=ls, linewidth=2, label=l)
               for k, l, c, ls in DESIGNS if any(k in att.get(p, {}) for p in PERIODS)]
    fig.legend(handles=handles, loc="lower center", ncol=len(handles), frameon=False,
               bbox_to_anchor=(0.5, -0.02), fontsize=8.5)
    fig.suptitle("Profiled CPA (distance) on simulated static-power traces, 20 keys, no added noise",
                 x=0.01, ha="left", fontsize=10.5, color=INK)
    fig.tight_layout(rect=(0, 0.07, 1, 0.95))
    for ext in ("png", "pdf"):
        fig.savefig(OUT / f"fig_success_curves.{ext}", dpi=200, facecolor="white")
    plt.close(fig)


# --------------------------------------------------------------------------
# Figure 2: signal vs total leakage at 300 ps
# --------------------------------------------------------------------------

def headroom_scores(notes):
    d = load(RES / "headroom_all.json")
    if d is None:
        notes_add(notes, "headroom_all.json not found; using pareto_300ps.json (300 ps only) "
                         "and the scores stored in the security assignment files")
        d = load(RES / "pareto_300ps.json") or {"scores": {}}
        scores = dict(d["scores"])
        for f in glob.glob(str(RES / "vt" / "security_var_*.json")):
            name = Path(f).stem
            if name not in scores:
                s = load(f)["stats"].get("score_heldout")
                if s:
                    scores[name] = s
        return scores
    return d["scores"]


def licspa_configs():
    rows = []
    for f in sorted(glob.glob(str(RES / "licspa" / "licspa_*ps_*_cfg*.json"))):
        r = load(f)
        m = re.match(r"licspa_(\d+)ps_(\d+)b_(\w+)_cfg(\d+)", Path(f).stem)
        st = r["stats"]
        rows.append({"name": Path(f).stem, "period": int(m.group(1)), "drive": m.group(3),
                     "cfg": int(m.group(4)), "area": st["area_um2"], "met": st["timing_met"],
                     "var": st["score_heldout"]["var"], "key": st["score_heldout"]["key"],
                     "leak": st["score_heldout"]["leak_nw"]})
    return rows


def fig_signal_power(scores, lic, notes, p=300):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6.2, 4.2))
    ax.set_yscale("log")
    ax.set_xscale("log")
    ax.grid(True, which="major", color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)

    lp = [r for r in lic if r["period"] == p and r["met"]]
    if lp:
        ax.scatter([r["leak"] for r in lp], [r["var"] for r in lp], s=40, color="#1baf7a",
                   edgecolor="white", linewidth=1.5, zorder=3, label=f"LiCSPA ({len(lp)} configurations)")
    sec = []
    for name, s in scores.items():
        m = re.fullmatch(rf"security_var_{p}ps(?:_lw([0-9e.\-]+))?", name)
        if m:
            w = float(m.group(1)) if m.group(1) else 0.0
            sec.append((w, s["leak_nw"], s["var"]))
    sec.sort(key=lambda t: t[1])
    if sec:
        ax.plot([t[1] for t in sec], [t[2] for t in sec], color="#eb6834", linewidth=2,
                marker="o", markersize=7, markeredgecolor="white", markeredgewidth=1.5, zorder=4,
                label="Security-driven (leakage weight)")
        xmax = max(t[1] for t in sec)
        for w, x, y in sec:
            txt = "w = 0" if w == 0 else "w = " + f"{w:.0e}".replace("e-0", "e-")
            right = x == xmax
            ax.annotate(txt, xy=(x, y), xytext=(-6 if right else 7, 9),
                        textcoords="offset points", ha="right" if right else "left",
                        fontsize=7.5, color=INK)
    b = scores.get(f"leakage_{p}ps")
    if b:
        ax.scatter([b["leak_nw"]], [b["var"]], s=70, color="#2a78d6", edgecolor="white",
                   linewidth=1.5, zorder=5, label="Timing-driven baseline")
        ax.annotate("baseline", xy=(b["leak_nw"], b["var"]), xytext=(8, 4),
                    textcoords="offset points", fontsize=7.5, color=INK)
    from matplotlib.ticker import NullFormatter, ScalarFormatter
    ax.set_xticks([500, 700, 1000, 1500, 2000, 3000])
    ax.xaxis.set_major_formatter(ScalarFormatter())
    ax.xaxis.set_minor_formatter(NullFormatter())
    ax.set_xlabel("Total static leakage (nW, log scale)")
    ax.set_ylabel("Key-dependent signal var (pW², log scale)")
    ax.set_title(f"Signal vs power at {p} ps (lower left is better)", loc="left", fontsize=10, color=INK)
    ax.legend(frameon=False, fontsize=8, loc="upper right")
    fig.tight_layout()
    for ext in ("png", "pdf"):
        fig.savefig(OUT / f"fig_signal_vs_power.{ext}", dpi=200, facecolor="white")
    plt.close(fig)


# --------------------------------------------------------------------------
# Tables
# --------------------------------------------------------------------------

def table(rows, header):
    w = [max(len(str(x)) for x in col) for col in zip(header, *rows)]
    line = lambda r: "| " + " | ".join(str(x).ljust(n) for x, n in zip(r, w)) + " |"
    return "\n".join([line(header), "|" + "|".join("-" * (n + 2) for n in w) + "|"] + [line(r) for r in rows])


def headroom_table(scores):
    rows = []
    for p in PERIODS:
        b = scores.get(f"leakage_{p}ps")
        for name, label in ((f"leakage_{p}ps", "Baseline"), (f"security_var_{p}ps", "Security-driven"),
                            (f"security_var_{p}ps_lw1e-6", "Security-driven, w = 1e-6")):
            s = scores.get(name)
            if not s:
                continue
            red = "–" if name.startswith("leakage") or not b else f"{b['var'] / s['var']:.1f}×"
            pw = "–" if not b else f"{s['leak_nw'] / b['leak_nw']:.2f}×"
            rows.append([f"{p} ps", label, f"{s['leak_nw']:.0f}", pw, f"{s['var']:,.0f}",
                         f"{s['key']:,.0f}", red])
    return table(rows, ["Period", "Design", "Leakage (nW)", "Leakage vs baseline", "Signal var (pW²)",
                        "Signal key (pW²)", "Signal reduction"])


def attack_table(att, failures, title_noise="0"):
    rows = []
    for p in PERIODS:
        row = att.get(p, {})
        base = row.get("baseline")
        for key, label, _, _ in DESIGNS:
            if key not in row:
                if key == "licspa" and p in failures:
                    rows.append([f"{p} ps", label, "no configuration met timing", "", "", "", "", ""])
                continue
            name, rec, grid = row[key]
            nmax = grid[-1]
            cells = []
            for lv in LEVELS:
                n = rec["n_at_col_sr"].get(lv)
                ci = rec.get("n_ci90", {}).get(lv)
                cell = fmt_n(n, nmax)
                if ci:
                    cell += f" [{fmt_n(ci[0], nmax)}, {fmt_n(ci[1], nmax)}]"
                if key != "baseline" and base:
                    cell += f" ({ratio(n, base[1]['n_at_col_sr'].get(lv), nmax)})"
                cells.append(cell)
            snr = float(np.mean(rec["snr_per_column"]))
            rows.append([f"{p} ps", label, f"{snr:.2e}", *cells, f"{rec['col_sr'][-1]:.3f}",
                         f"{rec['key_sr'][-1]:.2f}"])
    hdr = ["Period", "Design", "SNR", "N for 50% [90% CI] (vs baseline)", "N for 80%", "N for 90%",
           "Per-col. success at max", "Full-key success at max"]
    return table(rows, hdr)


def noise_table(p=300):
    rows = []
    for fname in (f"cpa_{p}ps.json", f"cpa_{p}ps_lw.json", f"cpa_{p}ps_licspa.json"):
        d = load(RES / fname)
        if not d:
            continue
        nmax = d["grid"][-1]
        for noise, res in d["results"].items():
            for name, rec in res.items():
                rows.append([f"{float(noise):g}", name, f"{float(np.mean(rec['snr_per_column'])):.2e}",
                             *[fmt_n(rec["n_at_col_sr"].get(l), nmax) for l in LEVELS]])
    rows.sort(key=lambda r: (r[1], float(r[0])))
    return table(rows, ["Noise σ (pW)", "Design", "SNR", "N for 50%", "N for 80%", "N for 90%"])


def licspa_table(lic, failures, scores):
    rows = []
    for p in PERIODS:
        for drive in ("fixed", "random"):
            rs = [r for r in lic if r["period"] == p and r["drive"] == drive]
            met = [r for r in rs if r["met"]]
            if p in failures and not rs:
                rows.append([f"{p} ps", drive, f"0/{failures[p] // 2 if failures[p] % 2 == 0 else '?'}",
                             "–", "–", "–", "–"])
                continue
            if not met:
                continue
            v = np.array([r["var"] for r in met])
            b = scores.get(f"leakage_{p}ps")
            rel = f"{v.min() / b['var']:.2f}× / {v.mean() / b['var']:.2f}×" if b else "–"
            rows.append([f"{p} ps", drive, f"{len(met)}/{len(rs)}",
                         f"{np.mean([r['area'] for r in met]):.1f}",
                         f"{np.mean([r['leak'] for r in met]):.0f}",
                         f"{v.min():,.0f} / {v.mean():,.0f} / {v.max():,.0f}", rel])
    return table(rows, ["Period", "Drive", "Met timing", "Mean area (µm²)", "Mean leakage (nW)",
                        "Signal var min / mean / max", "vs baseline (best / mean)"])


def hw_table():
    d = load(RES / "cpa_300ps_hw.json")
    if not d:
        return "(cpa_300ps_hw.json not found)"
    nmax = d["grid"][-1]
    rows = [[name, f"{rec['col_sr'][-1]:.3f}", fmt_n(rec["n_at_col_sr"].get("0.5"), nmax)]
            for name, rec in d["results"]["0.0"].items()]
    return table(rows, ["Design (300 ps)", f"Per-col. success at {nmax:,} traces (guessing = 0.25)",
                        "N for 50%"])


def failures_per_period():
    out = {}
    for f in glob.glob(str(RES / "licspa" / "licspa_*ps_timing_failures.txt")):
        p = int(re.search(r"licspa_(\d+)ps", f).group(1))
        out[p] = sum(1 for line in open(f) if "FAILED" in line)
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    notes = []
    att = attack_results(notes)
    failures = failures_per_period()
    scores = headroom_scores(notes)
    lic = licspa_configs()

    fig_success(att, failures, notes)
    fig_signal_power(scores, lic, notes)

    lic_fail = {p: n for p, n in failures.items()}
    grid = next((r[2] for row in att.values() for r in row.values()), [10, 13])
    step = (grid[-1] / grid[0]) ** (1 / (len(grid) - 1)) - 1
    md = [
        "# Results summary (generated by eval/make_figures.py; do not edit by hand)",
        "",
        "Per-column success: fraction of the 64 two-bit key guesses that are right. N: traces for that",
        f"success rate, read off a {len(grid)}-point log grid from {grid[0]} to {grid[-1]:,} traces (each point",
        f"about {step:.0%} above the previous one, so each N means 'between the previous grid point and",
        "this one'). Brackets: 90% bootstrap interval over the 20 keys. Ratios: traces vs the baseline at",
        "the same clock period. '>N' means not reached with N traces.",
        "",
        "## 1. Signal and leakage (held-out data, seed 7)",
        "", headroom_table(scores), "",
        "## 2. Attack: profiled CPA (distance), 20 keys × 400 000 traces, no added noise",
        "", attack_table(att, lic_fail), "",
        "## 3. Effect of measurement noise at 300 ps",
        "", noise_table(), "",
        "## 4. LiCSPA sweeps (24 protected bits; held-out signal)",
        "", licspa_table(lic, lic_fail, scores), "",
        "## 5. Textbook Hamming-weight CPA at 300 ps",
        "", hw_table(), "",
    ]
    if notes:
        md += ["## Notes", ""] + [f"- {n}" for n in notes] + [""]
    (OUT / "summary.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))
    print(f"\nwrote {OUT.relative_to(ROOT)}/: fig_success_curves.png/.pdf, "
          f"fig_signal_vs_power.png/.pdf, summary.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
