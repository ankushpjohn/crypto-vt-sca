#!/usr/bin/env python3
"""Cycle-accurate, vectorised evaluation of the synthesised Ascon core.

For a batch of (key, nonce) pairs this computes the value of every net of
build/ascon_core.v, and from that the logic state of every cell, in the clock
cycle we attack. The state of a cell is its leakage-table index (see
eval/liberty_leakage.py): sum(value(pins[i]) << i), pins sorted, outputs
included.

How it works
------------
* The netlist is read from the Verilog file, not the JSON, because the
  instance names in the Verilog (_2402_ ...) are the ones OpenSTA, opt/sta.py
  and the Vt assignment files use. The JSON has different internal names.
* Cell functions are read from the liberty `function` attributes of the
  merged RVT library (build/asap7_RVT_TT.lib, written by flow/synth_core.sh).
  All four flavours share the same function.
* Flip-flops (DFFHQNx1: CLK, D, QN) store a bit; QN = !stored. Every other
  cell is combinational and evaluated in topological order, one NumPy
  operation per cell over the whole batch.
* We do not poke flip-flops by name (synthesis renamed them and may have
  inverted some). Instead the netlist is clocked exactly as the testbench
  does:  cycle 0 rst=1  ->  cycle 1 start=1 with key/nonce  ->  cycle 2 is
  the primary attack point (state = IV|key|nonce, round 0 settling)  ->
  cycle 3 is the secondary attack point (state = round-1 output).
  Before the first edge every flip-flop holds a random value, which the
  reset/start sequence must make irrelevant; the check below proves it.

Checks (python3 eval/netlist_eval.py --check)
---------------------------------------------
* Outputs x0..x4 in the primary cycle equal init_states(...)[0], in the
  secondary cycle init_states(...)[1]; busy = 1 and done = 0 in both.
* The D input of every state flip-flop in the primary cycle equals the value
  it holds in the secondary cycle (i.e. the round-1 output was settled).
* Every cell state that occurs is a state the library lists (no NaN).

Usage from Python
-----------------
    from netlist_eval import Core
    core = Core()                                   # loads netlist + library
    run = core.run(key0, key1, nonce0, nonce1)       # uint64 arrays, shape (N,)
    run.states        # (N, cells) uint8, columns in order core.instances
    run.nets          # dict net -> bool array, primary attack cycle
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "model"))
sys.path.insert(0, str(ROOT / "opt"))

MASK64 = (1 << 64) - 1
WORDS = ("x0", "x1", "x2", "x3", "x4")
IN_WORDS = ("key0", "key1", "nonce0", "nonce1")


# --------------------------------------------------------------------------
# Liberty: pin directions and Boolean functions
# --------------------------------------------------------------------------

@dataclass
class CellType:
    name: str                      # full library name, e.g. NAND2xp33_ASAP7_75t_R
    inputs: list[str]
    outputs: dict[str, str]        # output pin -> liberty function text
    sequential: bool               # True for flip-flops


def read_cell_types(lib_path: Path, wanted: set[str]) -> dict[str, CellType]:
    """Pin directions and functions of the cells in `wanted`."""
    text = lib_path.read_text(encoding="ascii", errors="replace")
    types: dict[str, CellType] = {}
    for name in wanted:
        start = text.find(f"cell ({name})")
        if start < 0:
            raise KeyError(f"{name} not in {lib_path}")
        end = text.find("\n  cell (", start + 10)
        body = text[start:end if end > 0 else len(text)]
        inputs, outputs = [], {}
        # Each pin group: 'pin (X) {' ... up to the next 'pin (' at the same level.
        for m in re.finditer(r"\n\s*pin \((\w+)\)\s*\{", body):
            pin = m.group(1)
            nxt = re.search(r"\n\s*pin \(\w+\)\s*\{", body[m.end():])
            chunk = body[m.end(): m.end() + nxt.start() if nxt else len(body)]
            d = re.search(r"direction\s*:\s*(\w+)\s*;", chunk)
            if not d:
                continue
            if d.group(1) == "input":
                inputs.append(pin)
            elif d.group(1) == "output":
                f = re.search(r'function\s*:\s*"([^"]*)"', chunk)
                outputs[pin] = f.group(1) if f else ""
        seq = re.search(r"\n\s*ff\s*\(", body) is not None
        if seq:
            ff = re.search(r'ff\s*\((\w+)\s*,\s*(\w+)\)\s*\{[^}]*next_state\s*:\s*"([^"]*)"', body)
            # This evaluator supports the ASAP7 DFFHQN form only: QN = IQN,
            # next IQN = !D. Anything else must be added deliberately.
            if not ff or ff.group(3).replace(" ", "") != "!D" or set(outputs) != {"QN"} \
                    or outputs["QN"].strip() != ff.group(1):
                raise NotImplementedError(f"unsupported flip-flop {name}")
        types[name] = CellType(name, inputs, outputs, seq)
    return types


_TOKEN = re.compile(r"\s*(?:(\w+)|(.))")


def compile_function(expr: str, pins: list[str]):
    """Liberty function text -> Python function of bool arrays.

    Grammar: or := xor ('+'|'|' xor)* ; xor := and ('^' and)* ;
             and := unary (('*'|'&'|<juxtaposition>) unary)* ;
             unary := '!' unary | atom "'"* ; atom := name | 0 | 1 | '(' or ')'
    """
    toks = [(a or b) for a, b in _TOKEN.findall(expr) if (a or b).strip()]
    pos = 0

    def peek():
        return toks[pos] if pos < len(toks) else None

    def take():
        nonlocal pos
        pos += 1
        return toks[pos - 1]

    def p_or():
        t = p_xor()
        while peek() in ("+", "|"):
            take()
            t = f"({t} | {p_xor()})"
        return t

    def p_xor():
        t = p_and()
        while peek() == "^":
            take()
            t = f"({t} ^ {p_and()})"
        return t

    def p_and():
        t = p_unary()
        while peek() in ("*", "&") or (peek() not in (None, "+", "|", "^", ")", "'")):
            if peek() in ("*", "&"):
                take()
            t = f"({t} & {p_unary()})"
        return t

    def p_unary():
        if peek() == "!":
            take()
            return f"(~{p_unary()})"
        t = p_atom()
        while peek() == "'":
            take()
            t = f"(~{t})"
        return t

    def p_atom():
        t = take()
        if t == "(":
            v = p_or()
            if take() != ")":
                raise ValueError(f"unbalanced parentheses in {expr!r}")
            return v
        if t in ("0", "1"):
            return f"_c{t}"
        if t not in pins:
            raise ValueError(f"unknown pin {t!r} in {expr!r}")
        return f"v[{pins.index(t)}]"

    code = p_or()
    if pos != len(toks):
        raise ValueError(f"trailing tokens in {expr!r}")
    fn = eval(f"lambda v, _c0, _c1: {code}")      # noqa: S307 - text from the liberty file
    return fn, code


# --------------------------------------------------------------------------
# Verilog netlist (the structural output of Yosys write_verilog -noexpr)
# --------------------------------------------------------------------------

@dataclass
class Instance:
    name: str            # e.g. _2402_
    lib_cell: str        # e.g. NAND2xp33_ASAP7_75t_R
    pins: dict[str, str] # pin -> net name ("key0[3]", "_0583_", "1'b0")


_DECL = re.compile(r"^\s*(input|output|wire|reg)\s*(\[(\d+):(\d+)\])?\s*([^;]+);", re.M)
_INST = re.compile(r"^\s*(\w+)\s+(\\?\S+)\s*\((.*?)\);", re.M | re.S)
_CONN = re.compile(r"\.(\w+)\s*\(\s*([^()]*?)\s*\)")
_ASSIGN = re.compile(r"^\s*assign\s+(.*?)\s*=\s*(.*?)\s*;\s*$", re.M)


def _expand(sig: str, widths: dict[str, tuple[int, int]]) -> list[str]:
    """One connection expression -> list of single-bit net names, MSB first."""
    sig = sig.strip()
    if sig.startswith("\\") and sig in widths:          # escaped identifier, e.g. \bitreg[3].plain.r
        hi, lo = widths[sig]
        if widths.get(sig + "#scalar"):
            return [sig]
        return [f"{sig}[{i}]" for i in range(hi, lo - 1, -1)]
    if sig.startswith("{"):
        out = []
        for part in sig[1:-1].split(","):
            out += _expand(part, widths)
        return out
    m = re.fullmatch(r"(\d+)'b([01xz]+)", sig)
    if m:
        return [f"1'b{c}" for c in m.group(2)]
    m = re.fullmatch(r"(\\?\S+?)\s*\[(\d+):(\d+)\]", sig)
    if m:
        hi, lo = int(m.group(2)), int(m.group(3))
        step = -1 if hi >= lo else 1
        return [f"{m.group(1)}[{i}]" for i in range(hi, lo + step, step)]
    if re.fullmatch(r"\\?\S+\[\d+\]", sig):
        return [sig]
    if sig in widths:
        hi, lo = widths[sig]
        if (hi, lo) == (0, 0) and widths.get(sig + "#scalar"):
            return [sig]
        return [f"{sig}[{i}]" for i in range(hi, lo - 1, -1)]
    return [sig]


def read_netlist(path: Path, top: str | None = None):
    text = path.read_text(encoding="ascii")
    text = re.sub(r"\(\*.*?\*\)", "", text, flags=re.S)        # (* attributes *)
    if top is None:
        tops = re.findall(r"^\s*module\s+(\w+)", text, re.M)
        if len(tops) != 1:
            raise ValueError(f"{path}: {len(tops)} modules; pass top=")
        top = tops[0]
    m = re.search(rf"module\s+{re.escape(top)}\s*\((.*?)\);(.*?)endmodule", text, re.S)
    if not m:
        raise ValueError(f"module {top} not found in {path}")
    body = re.sub(r"/\*.*?\*/", "", m.group(2), flags=re.S)
    body = re.sub(r"//[^\n]*", "", body)

    widths: dict[str, tuple[int, int]] = {}
    ports: dict[str, tuple[str, list[str]]] = {}
    for d in _DECL.finditer(body):
        kind, rng = d.group(1), d.group(2)
        hi, lo = (int(d.group(3)), int(d.group(4))) if rng else (0, 0)
        for name in d.group(5).split(","):
            name = name.strip()
            widths[name] = (hi, lo)
            if not rng:
                widths[name + "#scalar"] = (1, 1)
            if kind in ("input", "output"):
                ports[name] = (kind, _expand(name, widths))
    for name, (kind, _) in list(ports.items()):
        ports[name] = (kind, _expand(name, widths))

    insts: list[Instance] = []
    decl_free = _DECL.sub("", body)
    decl_free = _ASSIGN.sub("", decl_free)
    for im in _INST.finditer(decl_free):
        pins = {}
        for c in _CONN.finditer(im.group(3)):
            bits = _expand(c.group(2), widths)
            if len(bits) != 1:
                raise ValueError(f"{im.group(2)}.{c.group(1)}: expected one bit, got {bits}")
            pins[c.group(1)] = bits[0]
        insts.append(Instance(im.group(2), im.group(1), pins))

    aliases = []
    for a in _ASSIGN.finditer(body):
        lhs, rhs = _expand(a.group(1), widths), _expand(a.group(2), widths)
        if len(lhs) != len(rhs):
            raise ValueError(f"assign width mismatch: {a.group(0)}")
        aliases += list(zip(lhs, rhs))
    return ports, insts, aliases


# --------------------------------------------------------------------------
# The evaluator
# --------------------------------------------------------------------------

@dataclass
class Run:
    key0: np.ndarray
    key1: np.ndarray
    nonce0: np.ndarray
    nonce1: np.ndarray
    states: np.ndarray            # (N, cells) uint8, primary attack cycle
    nets: dict                    # net -> bool array (N,), primary attack cycle
    nets_next: dict | None        # same, secondary attack cycle (if requested)


def words_to_bits(w: np.ndarray) -> np.ndarray:
    """uint64 (N,) -> bool (N, 64), column j = bit j."""
    w = np.asarray(w, dtype=np.uint64)
    return ((w[:, None] >> np.arange(64, dtype=np.uint64)) & np.uint64(1)).astype(bool)


def bits_to_words(b: np.ndarray) -> np.ndarray:
    """bool (N, 64) -> uint64 (N,)."""
    return (b.astype(np.uint64) << np.arange(64, dtype=np.uint64)).sum(axis=1, dtype=np.uint64)


class Core:
    """The synthesised core, ready to be evaluated for batches of inputs."""

    def __init__(self, netlist="build/ascon_core.v", top=None,
                 lib="build/asap7_RVT_TT.lib", libdir="libs/asap7", corner="TT",
                 table=None, random_ports=()):
        """random_ports: input ports (other than clk, rst, start, key, nonce)
        that get a fresh random value per execution, held for the whole run,
        e.g. ("ctl",) for LiCSPA. Any other extra input port is held at 0."""
        t0 = time.time()
        self.netlist = str(netlist)
        self.random_ports = tuple(random_ports)
        self.ports, insts, aliases = read_netlist(Path(netlist), top)
        types = read_cell_types(Path(lib), {i.lib_cell for i in insts})

        if table is None:
            from liberty_leakage import load_leakage
            table = load_leakage(libdir, corner)
        self.table = table

        # Net aliases from `assign` (none in the current netlist, but cheap).
        self._alias = {}
        for lhs, rhs in aliases:
            self._alias[lhs] = rhs

        self.instances = [i.name for i in insts]          # fixed column order
        self.cell = {}                                      # instance -> base name
        self._insts = insts
        self._types = types
        self._split_names()

        # Sequential and combinational cells; driver of every net.
        driver = {}
        self.flops = []
        for k, inst in enumerate(insts):
            ct = types[inst.lib_cell]
            for out in ct.outputs:
                net = self._net(inst.pins[out])
                if net in driver:
                    raise ValueError(f"net {net} has two drivers")
                driver[net] = k
            if ct.sequential:
                self.flops.append(k)
        flop_set = set(self.flops)

        # Topological order of the combinational cells (Kahn).
        deps = {}
        users = {}
        for k, inst in enumerate(insts):
            if k in flop_set:
                continue
            ct = types[inst.lib_cell]
            d = set()
            for p in ct.inputs:
                src = driver.get(self._net(inst.pins[p]))
                if src is not None and src not in flop_set:
                    d.add(src)
                    users.setdefault(src, []).append(k)
            deps[k] = d
        ready = [k for k, d in deps.items() if not d]
        order = []
        remaining = {k: len(d) for k, d in deps.items()}
        while ready:
            k = ready.pop()
            order.append(k)
            for u in users.get(k, []):
                remaining[u] -= 1
                if remaining[u] == 0:
                    ready.append(u)
        if len(order) != len(deps):
            raise ValueError("combinational loop in the netlist")
        self._order = order

        # Compiled functions per cell type.
        self._fn = {}
        for name, ct in types.items():
            if ct.sequential:
                continue
            self._fn[name] = {o: compile_function(f, ct.inputs)[0] for o, f in ct.outputs.items()}

        # Leakage pins per instance and per-state lookup tables.
        self._build_luts()
        self.load_time = time.time() - t0

    # -- helpers -----------------------------------------------------------

    def _split_names(self):
        from sta import split_lib_cell
        self.flavour_mapped = {}
        for inst in self._insts:
            self.cell[inst.name], self.flavour_mapped[inst.name] = split_lib_cell(inst.lib_cell)

    def _net(self, n: str) -> str:
        while n in self._alias:
            n = self._alias[n]
        return n

    def _build_luts(self):
        """LUT[f] has shape (cells, max_states): leakage of each cell in flavour f."""
        from liberty_leakage import FLAVOURS
        self.flavours = FLAVOURS
        self.leak_pins = []
        nmax = 1
        for inst in self._insts:
            entry = self.table[self.cell[inst.name]]["RVT"]
            for p in entry.pins:
                if p not in inst.pins:
                    raise KeyError(f"{inst.name} ({inst.lib_cell}) has no pin {p}")
            self.leak_pins.append(entry.pins)
            nmax = max(nmax, len(entry.leak))
        if nmax > 256:
            raise ValueError("a cell has more than 8 leakage pins; widen the state dtype")
        self.lut = np.full((len(FLAVOURS), len(self._insts), nmax), np.nan)
        for k, inst in enumerate(self._insts):
            for fi, f in enumerate(FLAVOURS):
                e = self.table[self.cell[inst.name]][f]
                if e.pins != self.leak_pins[k]:
                    raise ValueError(f"{inst.name}: pin order differs between flavours")
                self.lut[fi, k, :len(e.leak)] = e.leak

    # -- simulation --------------------------------------------------------

    def _settle(self, vals: dict, flop_q: np.ndarray, n: int):
        """Combinational settle. vals holds the primary inputs; flop_q (F, N) the stored bits."""
        c0 = np.zeros(n, dtype=bool)
        c1 = np.ones(n, dtype=bool)
        vals["1'b0"], vals["1'b1"] = c0, c1
        vals["1'bx"] = c0                     # unconnected constants: treat as 0
        for slot, k in enumerate(self.flops):
            vals[self._net(self._insts[k].pins["QN"])] = ~flop_q[slot]
        for k in self._order:
            inst = self._insts[k]
            ct = self._types[inst.lib_cell]
            args = [vals[self._net(inst.pins[p])] for p in ct.inputs]
            for out, fn in self._fn[inst.lib_cell].items():
                vals[self._net(inst.pins[out])] = fn(args, c0, c1)
        return vals

    def _inputs(self, n, rst, start, clk, words, extra):
        v = {}
        for name, (kind, bits) in self.ports.items():
            if kind != "input":
                continue
            if name in ("rst", "start", "clk"):
                val = {"rst": rst, "start": start, "clk": clk}[name]
                v[bits[0]] = np.full(n, bool(val))
                continue
            b = words.get(name)
            if b is None:
                b = extra.get(name)
            if b is None:
                b = np.zeros((n, len(bits)), bool)
            for net in bits:
                m = re.search(r"\[(\d+)\]$", net)
                v[net] = b[:, int(m.group(1)) if m else 0]
        return v

    def _extra_inputs(self, n, rng):
        extra = {}
        for name in self.random_ports:
            if name not in self.ports or self.ports[name][0] != "input":
                raise KeyError(f"no input port {name}")
            width = len(self.ports[name][1])
            extra[name] = rng.integers(0, 2, (n, width)).astype(bool)
        return extra

    def _d_values(self, vals):
        return np.stack([vals[self._net(self._insts[k].pins["D"])] for k in self.flops])

    def port_word(self, vals, name) -> np.ndarray:
        bits = self.ports[name][1]
        if len(bits) == 1:
            return vals[self._net(bits[0])].astype(np.uint64)
        cols = np.stack([vals[self._net(b)] for b in bits[::-1]], axis=1)  # col j = bit j
        return bits_to_words(cols)

    def run(self, key0, key1, nonce0, nonce1, *, clk_level=0, inputs="hold",
            secondary=False, seed=0) -> Run:
        """Evaluate the attack cycle(s) for N executions.

        clk_level  logic level of the clock while it is stopped (CLK pin of the
                   flip-flops); it changes their leakage state.
        inputs     what the key/nonce input ports carry in the attack cycle:
                   "hold" (still the key and nonce), "zero", or "random".
        """
        key0, key1, nonce0, nonce1 = (np.asarray(a, dtype=np.uint64) for a in (key0, key1, nonce0, nonce1))
        n = len(key0)
        rng = np.random.default_rng(seed)
        load = {"key0": words_to_bits(key0), "key1": words_to_bits(key1),
                "nonce0": words_to_bits(nonce0), "nonce1": words_to_bits(nonce1)}
        rand = lambda: words_to_bits(rng.integers(0, 2**63, n, dtype=np.uint64) * 2 + rng.integers(0, 2, n, dtype=np.uint64))
        zero = {k: np.zeros((n, 64), bool) for k in IN_WORDS}
        rnd = {k: rand() for k in IN_WORDS}
        attack_in = {"hold": load, "zero": zero, "random": rnd}[inputs]

        extra = self._extra_inputs(n, rng)                          # e.g. LiCSPA ctl, per run
        q = rng.integers(0, 2, (len(self.flops), n)).astype(bool)   # power-up: unknown
        # cycle 0: reset (inputs random, they must not matter)
        q = self._d_values(self._settle(self._inputs(n, 1, 0, 0, rnd, extra), q, n))
        # cycle 1: start with key and nonce
        q = self._d_values(self._settle(self._inputs(n, 0, 1, 0, load, extra), q, n))
        # cycle 2: primary attack point
        vals = self._settle(self._inputs(n, 0, 0, clk_level, attack_in, extra), q, n)
        nets_next = None
        if secondary:
            q2 = self._d_values(vals)
            nets_next = self._settle(self._inputs(n, 0, 0, clk_level, attack_in, extra), q2, n)
            nets_next["#q"] = q2
        vals["#q"] = q
        states = self.states_of(vals)
        return Run(key0, key1, nonce0, nonce1, states, vals, nets_next)

    def states_of(self, vals) -> np.ndarray:
        """Leakage-table state index of every cell, shape (N, cells), uint8."""
        n = len(vals["1'b0"])
        out = np.zeros((n, len(self._insts)), dtype=np.uint8)
        for k, inst in enumerate(self._insts):
            idx = np.zeros(n, dtype=np.uint8)
            for bit, p in enumerate(self.leak_pins[k]):
                idx |= vals[self._net(inst.pins[p])].astype(np.uint8) << np.uint8(bit)
            out[:, k] = idx
        return out

    def leakage(self, states: np.ndarray, assignment: dict | None = None) -> np.ndarray:
        """Total leakage (pW) per execution for one Vt assignment (default all RVT)."""
        fidx = self.flavour_index(assignment)
        per_cell = self.lut[fidx, np.arange(len(self._insts)), states]
        return per_cell.sum(axis=1)

    def flavour_index(self, assignment: dict | None) -> np.ndarray:
        """Assignment dict (instance -> flavour) -> flavour index per column."""
        if assignment is None:
            return np.full(len(self._insts), self.flavours.index("RVT"))
        missing = [i for i in self.instances if i not in assignment]
        extra = [i for i in assignment if i not in self.cell]
        if missing or extra:
            raise KeyError(f"assignment does not match the netlist: {len(missing)} instances "
                           f"missing (e.g. {missing[:3]}), {len(extra)} unknown (e.g. {extra[:3]})")
        return np.array([self.flavours.index(assignment[i]) for i in self.instances])


# --------------------------------------------------------------------------
# Self-check
# --------------------------------------------------------------------------

def random_words(rng, n):
    return rng.integers(0, 2**63, n, dtype=np.uint64) * np.uint64(2) + rng.integers(0, 2, n, dtype=np.uint64)


def self_check(core: Core, n: int, seed: int) -> bool:
    from ascon_ref import init_states
    rng = np.random.default_rng(seed)
    k0, k1, n0, n1 = (random_words(rng, n) for _ in range(4))
    # First three: official all-zero and all-one patterns, like the testbench.
    k0[0] = k1[0] = n0[0] = n1[0] = 0
    k0[1] = k1[1] = n0[1] = n1[1] = MASK64
    ok = True
    for clk in (0, 1):
        for inputs in ("hold", "zero", "random"):
            t = time.time()
            run = core.run(k0, k1, n0, n1, clk_level=clk, inputs=inputs, secondary=True, seed=seed + 1)
            dt = time.time() - t
            exp = [init_states(int(a), int(b), int(c), int(d)) for a, b, c, d in zip(k0, k1, n0, n1)]
            bad0 = bad1 = 0
            for w, name in enumerate(WORDS):
                got0 = core.port_word(run.nets, name)
                got1 = core.port_word(run.nets_next, name)
                bad0 += int(np.sum(got0 != np.array([e[0][w] for e in exp], dtype=np.uint64)))
                bad1 += int(np.sum(got1 != np.array([e[1][w] for e in exp], dtype=np.uint64)))
            busy = core.port_word(run.nets, "busy")
            done = core.port_word(run.nets, "done")
            ctrl_bad = int(np.sum(busy != 1) + np.sum(done != 0))
            nan = int(np.isnan(core.lut[core.flavours.index("RVT"),
                                        np.arange(len(core.instances)), run.states]).sum())
            this_ok = bad0 == bad1 == ctrl_bad == nan == 0
            ok &= this_ok
            print(f"  clk={clk} inputs={inputs:6s}: x0..x4 wrong in primary cycle {bad0}, "
                  f"after round 1 {bad1}; busy/done wrong {ctrl_bad}; impossible cell states {nan}"
                  f"  ({n} executions, {dt:.1f} s)  {'OK' if this_ok else 'FAIL'}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description="Evaluate and check the gate-level netlist.")
    ap.add_argument("--netlist", default="build/ascon_core.v")
    ap.add_argument("--lib", default="build/asap7_RVT_TT.lib")
    ap.add_argument("--random-ports", nargs="*", default=[], help="e.g. ctl for LiCSPA")
    ap.add_argument("--libdir", default="libs/asap7")
    ap.add_argument("--n", type=int, default=2000, help="executions for the check")
    ap.add_argument("--seed", type=int, default=20261116)
    args = ap.parse_args()

    core = Core(args.netlist, lib=args.lib, libdir=args.libdir, random_ports=args.random_ports)
    nflops = len(core.flops)
    print(f"netlist: {len(core.instances)} cells ({nflops} flip-flops, "
          f"{len(core._order)} combinational), loaded in {core.load_time:.1f} s")
    ok = self_check(core, args.n, args.seed)
    print("RESULT: " + ("all checks passed" if ok else "CHECKS FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
