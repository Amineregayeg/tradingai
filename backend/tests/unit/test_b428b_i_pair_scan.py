"""**THE PAIR SCAN, RUN AS A TEST** (`B449`, `B461`; T-0144 R4/R15, DESIGN §1.2 and §6; kill set P-5).

Alpaca spells a crypto POSITION `BTCUSD` and its ORDERS, ASSETS and FILLs `BTC/USD`; the loop's pair is `BTC/USD`. An
exact `==` between two of those spellings is how `_has_position` never saw an Alpaca position (`B449`) and how the
reconcilers would mark an OPEN trade CLOSED (`B461`). Every comparison between a VENUE-sourced symbol and a pair from
another source must go through `app.services.broker.symbols.same_pair` / `canonical_pair`.

The comparison sites are DERIVED from the source on every run, never a pinned list of lines. The rules, in order:

VOCABULARY (derived per run, printed on failure)
  * an identifier (name, attribute, parameter, keyword, function, identifier-like string key) whose `_`/camelCase
    tokens include `pair`, `pairs`, `symbol` or `symbols` (`binance_symbol`, `live_pairs`; not `repair`, `pairing`);
  * a LOCAL assigned (or bound by a `for`/comprehension target) from a PAIR-VALUED expression, per function scope,
    iterated to a fixpoint: a vocabulary name/attribute, a string field read (`x["pair"]`, `x.get("pair")`,
    `getattr(x, "symbol")`), `str()`/`.strip()`/`.upper()`/... of one, a comprehension of one, `canonical_pair(...)`
    (never `same_pair`, a bool), a call to a function THE TARGETS DEFINE only if one of its own `return`s is
    pair-valued (so `dec_id = await self._open_decision_id_from_db(pair)` is not a pair), and a call of a plain name
    they do not define on a pair argument (`norm(p.symbol)`: a home-grown normaliser is what must not escape);
  * a string FIELD, per file, that the file writes a pair-valued value under (`{"position_id": getattr(raw, "symbol")}`
    in alpaca.py makes `position_id` a pair field THERE and nowhere else);
  * a PAIR-KEYED CONTAINER, per file: one subscripted / `.get` / `.pop` / `.setdefault` with a pair-valued key.

VENUE-SOURCED: an expression CONTAINING an attribute `.pair` / `.symbol` / `.venue_symbol` (on any object, a model
  class included — a column is examined, and its exemption says which spelling the column holds), or a read of field
  `pair` / `symbol` / `venue_symbol` / a venue-derived field by `x[...]`, `x.get(...)` or `getattr(x, ...)` from an
  object that is NOT `self.<attr>` (the object's own dicts), or a local derived from such an expression, or a
  PARAMETER of a function defined in the same file that some call passes such an expression (flow-insensitive: one
  venue call site makes the parameter venue-sourced for the whole body — the old `_same_symbol(a, b)` is found so).

SHAPES (R15), mutually exclusive (each predicate excludes the others); a pair-valued operand MENTIONS the vocabulary
  s3 SQL predicate: a Compare with a pair-valued operand containing an attribute of an Uppercase name (`Trade.pair`);
  s2 membership: `in` / `not in` (a comprehension, a literal, a vocabulary name or a pair-keyed container);
  s5 attribute compare: `==` / `!=` whose pair-valued operands are all attributes (`a.symbol != b.pair`);
  s1 equality: any other `==` / `!=`;
  s4 dict key: `x[k]` or `x.get(k)` / `x.pop(k)` / `x.setdefault(k)` whose key k mentions the vocabulary and is not a
     string field name.

VIOLATION: a Compare with at least two pair-valued operands, at least one of them venue-sourced, and at least one
  pair-valued operand that is not CANONICAL; or a key site whose key is venue-sourced and not canonical. CANONICAL is a
  call to `same_pair` / `canonical_pair` or to a derived delegate (a function whose body is `return <canonical call>`),
  or a comprehension/literal of such calls. `canonical_pair(a.symbol) == pair` IS a violation: one side is still raw.
  Excused only by `EXEMPT` (file, enclosing function, normalised expression, reason — never a line number), and every
  `EXEMPT` entry must still match exactly one violation, so a stale exemption fails instead of rotting.
"""
from __future__ import annotations

import ast
import functools
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

BACKEND = Path(__file__).resolve().parents[2]
TARGETS = (
    "app/services/live/crypto_loop.py",
    "app/services/broker/alpaca.py",
    "app/services/broker/reconciler.py",
    "app/services/broker/reconciliation.py",
)
CANONICAL = frozenset({"same_pair", "canonical_pair"})
CANONICAL_MODULE = "app.services.broker.symbols"
VOCAB_TOKENS = frozenset({"pair", "pairs", "symbol", "symbols"})
VENUE_ATTRS = frozenset({"pair", "symbol", "venue_symbol"})
VENUE_KEYS = frozenset({"pair", "symbol", "venue_symbol"})
PAIR_LITERAL = re.compile(r"^[A-Z0-9]{2,10}[/_\-]?(USD|USDT|USDC|BTC|ETH|EUR|GBP|JPY)$")
IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
STR_TRANSFORMS = frozenset({"replace", "upper", "lower", "strip", "rstrip", "lstrip", "removesuffix", "removeprefix",
                            "casefold", "split", "rsplit", "partition", "rpartition"})
COLLECTION_CALLS = frozenset({"str", "list", "set", "sorted", "tuple", "frozenset"})
SCALAR_CALLS = frozenset({"len", "bool", "int", "float", "isinstance", "round", "abs", "sum", "any", "all", "hash",
                          "id", "type", "repr", "Decimal", "range", "enumerate", "zip", "next", "iter", "hasattr",
                          "callable", "max", "min", "print"})
KEY_METHODS = frozenset({"get", "pop", "setdefault"})
SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
EQ_OPS = (ast.Eq, ast.NotEq)
IN_OPS = (ast.In, ast.NotIn)


def _tokens(name: str) -> list[str]:
    return [t.lower() for t in re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])", name)]


def _vocab(name: str) -> bool:
    return bool(VOCAB_TOKENS.intersection(_tokens(name)))


def _callee(call: ast.Call) -> str | None:
    f = call.func
    return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None


def _own(e: ast.AST) -> bool:
    """`self.<attr>` — the object's own container."""
    return isinstance(e, ast.Attribute) and isinstance(e.value, ast.Name) and e.value.id == "self"


def _norm(expr: str) -> str:
    return ast.unparse(ast.parse(expr, mode="eval").body)


@dataclass(frozen=True)
class Site:
    file: str
    line: int
    function: str
    shape: str
    expr: str
    pair_sides: tuple[str, ...]
    venue: bool
    violation: bool

    def __str__(self) -> str:
        return (f"{self.file}:{self.line} [{self.function}] {self.shape} `{self.expr}` "
                f"(pair-valued: {', '.join(self.pair_sides)}; venue-sourced: {self.venue})")


@dataclass
class ScanResult:
    sites: list[Site]
    compares_seen: int
    canonical_calls: dict[str, int]          # file -> direct `same_pair`/`canonical_pair` calls
    vocabulary: dict[str, object]

    @property
    def violations(self) -> list[Site]:
        return [s for s in self.sites if s.violation]

    def vocabulary_text(self) -> str:
        return "\n".join(f"  {k} ({len(v)}): {sorted(v) if not isinstance(v, dict) else v}"
                         for k, v in self.vocabulary.items())


class _PairScan:
    def __init__(self, files: list[tuple[str, str]]):
        self.trees = {path: ast.parse(src, filename=path) for path, src in files}   # a parse error REFUSES
        self.parent: dict[ast.AST, ast.AST] = {}
        self.scope: dict[ast.AST, ast.AST] = {}
        for tree in self.trees.values():
            self._map_scopes(tree, tree)
        self.seed: set[str] = set()
        self.pair_locals: dict[int, set[str]] = {}
        self.venue_locals: dict[int, set[str]] = {}
        self.local_origin: dict[str, str] = {}
        self.fields: dict[str, dict[str, bool]] = {p: {} for p in self.trees}       # file -> field -> venue
        self.keyed: dict[tuple[str, str], set[bool]] = {}                          # (file, container) -> canonical keys?
        self.delegates: set[str] = set()
        self.defs = [(p, n) for p, t in self.trees.items() for n in ast.walk(t)
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        self.defined = {n.name for _, n in self.defs}
        self.pair_returning: set[str] = set()

    def _map_scopes(self, node: ast.AST, scope: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            self.parent[child] = node
            self.scope[child] = scope
            self._map_scopes(child, child if isinstance(child, SCOPES) else scope)

    def _chain(self, node: ast.AST):
        s = self.scope.get(node)
        while s is not None:
            yield s
            s = self.scope.get(s)

    def _local(self, name: ast.Name, table: dict[int, set[str]]) -> bool:
        return any(name.id in table.get(id(s), ()) for s in self._chain(name))

    def function_of(self, node: ast.AST) -> str:
        n = node
        while n in self.parent:
            n = self.parent[n]
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return n.name
        return "<module>"

    # ---- classification -------------------------------------------------------------------------------------
    def field_name(self, e: ast.AST, f: str) -> bool:
        return (isinstance(e, ast.Constant) and isinstance(e.value, str) and bool(IDENT.match(e.value))
                and (_vocab(e.value) or e.value in self.fields[f]))

    def venue_field(self, e: ast.AST, f: str) -> bool:
        return (isinstance(e, ast.Constant) and isinstance(e.value, str)
                and (e.value in VENUE_KEYS or self.fields[f].get(e.value) is True))

    def container_key(self, e: ast.AST) -> str:
        return f"{e.id}@{id(self.scope.get(e))}" if isinstance(e, ast.Name) else ast.unparse(e)

    def is_keyed(self, e: ast.AST, f: str) -> bool:
        return (f, self.container_key(e)) in self.keyed

    def canonical(self, e: ast.AST, f: str) -> bool:
        if isinstance(e, ast.Await):
            return self.canonical(e.value, f)
        if isinstance(e, ast.Call):
            return _callee(e) in CANONICAL or _callee(e) in self.delegates
        if isinstance(e, (ast.SetComp, ast.ListComp, ast.GeneratorExp)):
            return self.canonical(e.elt, f)
        if isinstance(e, ast.DictComp):
            return self.canonical(e.key, f)
        if isinstance(e, (ast.Set, ast.List, ast.Tuple)):
            return bool(e.elts) and all(self.canonical(x, f) or not self.mentions(x, f) for x in e.elts)
        if self.is_keyed(e, f):
            return self.keyed[(f, self.container_key(e))] == {True}
        return False

    def pair_valued(self, e: ast.AST, f: str) -> bool:
        """STRICT: the expression's VALUE is a pair (used to derive locals, fields and keyed containers)."""
        if isinstance(e, ast.Constant):
            return isinstance(e.value, str) and bool(PAIR_LITERAL.match(e.value))
        if isinstance(e, ast.Name):
            return _vocab(e.id) or self._local(e, self.pair_locals)
        if isinstance(e, ast.Attribute):
            return _vocab(e.attr)
        if isinstance(e, ast.Await):
            return self.pair_valued(e.value, f)
        if isinstance(e, ast.Subscript):
            if self.field_name(e.slice, f):
                return True
            return not isinstance(e.slice, ast.Constant) and self.pair_valued(e.value, f)
        if isinstance(e, ast.Call):
            name = _callee(e)
            if name == "canonical_pair":
                return True
            if name in CANONICAL:
                return False                                   # `same_pair` answers a bool
            if name in self.defined:
                return name in self.pair_returning             # a function the targets define: its returns decide
            if name == "getattr" and len(e.args) >= 2:
                return self.field_name(e.args[1], f)
            if isinstance(e.func, ast.Attribute):
                if e.func.attr in STR_TRANSFORMS:
                    return self.pair_valued(e.func.value, f)
                if e.func.attr in KEY_METHODS and e.args:
                    if isinstance(e.args[0], ast.Constant):
                        return self.field_name(e.args[0], f)
                    return self.pair_valued(e.func.value, f)
            if name in COLLECTION_CALLS:
                return bool(e.args) and self.pair_valued(e.args[0], f)
            if name is not None and _vocab(name):
                return True                                    # a converter defined elsewhere: `to_cft_symbol(x)`
            return isinstance(e.func, ast.Name) and name not in SCALAR_CALLS and any(
                self.pair_valued(a, f) for a in e.args if not isinstance(a, ast.Starred))   # a lambda/function of a pair
        if isinstance(e, ast.BoolOp):
            return any(self.pair_valued(v, f) for v in e.values)
        if isinstance(e, ast.IfExp):
            return self.pair_valued(e.body, f) or self.pair_valued(e.orelse, f)
        if isinstance(e, (ast.SetComp, ast.ListComp, ast.GeneratorExp)):
            return self.pair_valued(e.elt, f)
        if isinstance(e, ast.DictComp):
            return self.pair_valued(e.key, f)                  # `in` and iteration see the keys
        if isinstance(e, (ast.Set, ast.List, ast.Tuple)):
            return bool(e.elts) and all(self.pair_valued(x, f) for x in e.elts)   # `(to, fields, pair)` is not a pair
        return False

    def venue(self, e: ast.AST, f: str) -> bool:
        for n in ast.walk(e):
            if isinstance(n, ast.Attribute) and n.attr in VENUE_ATTRS:
                return True
            if isinstance(n, ast.Name) and self._local(n, self.venue_locals):
                return True
            if isinstance(n, ast.Subscript) and self.venue_field(n.slice, f) and not _own(n.value):
                return True
            if isinstance(n, ast.Call):
                if _callee(n) == "getattr" and len(n.args) >= 2 and self.venue_field(n.args[1], f) and not _own(n.args[0]):
                    return True
                if (isinstance(n.func, ast.Attribute) and n.func.attr in KEY_METHODS and n.args
                        and self.venue_field(n.args[0], f) and not _own(n.func.value)):
                    return True
        return False

    def mentions(self, e: ast.AST, f: str) -> list[str]:
        hits = []
        for n in ast.walk(e):
            if isinstance(n, ast.Name) and (_vocab(n.id) or self._local(n, self.pair_locals)):
                hits.append(n.id)
            elif isinstance(n, ast.Attribute) and _vocab(n.attr):
                hits.append("." + n.attr)
            elif isinstance(n, ast.Constant) and isinstance(n.value, str) and (
                    PAIR_LITERAL.match(n.value) or self.field_name(n, f)):
                hits.append(repr(n.value))
        if self.is_keyed(e, f):
            hits.append(f"<pair-keyed {ast.unparse(e)}>")
        return hits

    # ---- derivation (fixpoint) ------------------------------------------------------------------------------
    def derive(self) -> None:
        for tree in self.trees.values():
            for n in ast.walk(tree):
                names = []
                if isinstance(n, ast.Name):
                    names.append(n.id)
                elif isinstance(n, ast.Attribute):
                    names.append(n.attr)
                elif isinstance(n, ast.arg):
                    names.append(n.arg)
                elif isinstance(n, ast.keyword) and n.arg:
                    names.append(n.arg)
                elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    names.append(n.name)
                elif isinstance(n, ast.Constant) and isinstance(n.value, str) and IDENT.match(n.value):
                    names.append(n.value)
                self.seed.update(x for x in names if _vocab(x))
        for _ in range(25):
            before = self._state_size()
            for f, tree in self.trees.items():
                for n in ast.walk(tree):
                    self._derive_node(n, f)
            for f, d in self.defs:
                if d.name not in self.pair_returning and any(
                        isinstance(r, ast.Return) and r.value is not None and self.scope.get(r) is d
                        and self.pair_valued(r.value, f) for r in ast.walk(d)):
                    self.pair_returning.add(d.name)
            if self._state_size() == before:
                return
        raise RuntimeError("REFUSING: the vocabulary derivation reached no fixpoint in 25 rounds")

    def _state_size(self) -> int:
        return (sum(map(len, self.pair_locals.values())) + sum(map(len, self.venue_locals.values()))
                + sum(len(v) for v in self.fields.values()) + sum(map(len, self.keyed.values()))
                + len(self.keyed) + sum(1 for d in self.fields.values() for v in d.values() if v)
                + len(self.delegates) + len(self.pair_returning))

    def _bind(self, target: ast.AST, value: ast.AST, node: ast.AST, f: str, why: str) -> None:
        if isinstance(target, ast.Tuple) and isinstance(value, ast.Tuple):
            for t, v in zip(target.elts, value.elts):
                self._bind(t, v, node, f, why)
        elif isinstance(target, ast.Name) and self.pair_valued(value, f):
            self._add_local(self.scope.get(target), target.id, self.venue(value, f),
                            f"{f}:{self.function_of(node)}:{target.id}", f"{why} {ast.unparse(value)[:60]}")
        elif (isinstance(target, ast.Subscript) and isinstance(target.slice, ast.Constant)
              and isinstance(target.slice.value, str) and IDENT.match(target.slice.value)
              and self.pair_valued(value, f)):
            self._field(f, target.slice.value, self.venue(value, f))

    def _add_local(self, scope: ast.AST | None, name: str, venue: bool, where: str, why: str) -> None:
        """A vocabulary name needs no derivation (it is already a pair) but can still become venue-sourced."""
        if not _vocab(name) and name not in self.pair_locals.setdefault(id(scope), set()):
            self.pair_locals[id(scope)].add(name)
            self.local_origin[where] = why
        if venue:
            self.venue_locals.setdefault(id(scope), set()).add(name)

    def _field(self, f: str, key: str, venue: bool) -> None:
        self.fields[f][key] = self.fields[f].get(key, False) or venue

    def _key(self, container: ast.AST, key: ast.AST, f: str) -> None:
        if not self.field_name(key, f) and self.pair_valued(key, f):
            self.keyed.setdefault((f, self.container_key(container)), set()).add(self.canonical(key, f))

    def _derive_node(self, n: ast.AST, f: str) -> None:
        if isinstance(n, ast.Assign):
            for t in n.targets:
                self._bind(t, n.value, n, f, "=")
        elif isinstance(n, (ast.AnnAssign, ast.NamedExpr)) and n.value is not None:
            self._bind(n.target, n.value, n, f, "=")
        elif isinstance(n, (ast.For, ast.AsyncFor, ast.comprehension)):
            self._bind_iter(n.target, n.iter, n, f)
        elif isinstance(n, ast.Dict):
            for k, v in zip(n.keys, n.values):
                if (isinstance(k, ast.Constant) and isinstance(k.value, str) and IDENT.match(k.value)
                        and self.pair_valued(v, f)):
                    self._field(f, k.value, self.venue(v, f))
        elif isinstance(n, ast.Subscript):
            self._key(n.value, n.slice, f)
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in KEY_METHODS and n.args:
            self._key(n.func.value, n.args[0], f)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body = [s for s in n.body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
            if (len(body) == 1 and isinstance(body[0], ast.Return) and isinstance(body[0].value, ast.Call)
                    and (_callee(body[0].value) in CANONICAL or _callee(body[0].value) in self.delegates)):
                self.delegates.add(n.name)
        if isinstance(n, ast.Call) and _callee(n) in self.defined:
            self._bind_params(n, f)

    def _bind_params(self, call: ast.Call, f: str) -> None:
        """A pair argument makes the callee's parameter a pair local (venue if the argument is): the old
        `_same_symbol(a, b)` compared `norm(a) == norm(b)` on parameters no vocabulary names. Same-file callees only."""
        for p, d in self.defs:
            if p != f or d.name != _callee(call):
                continue
            params = [a.arg for a in d.args.posonlyargs + d.args.args]
            if params and params[0] in ("self", "cls") and isinstance(call.func, ast.Attribute):
                params = params[1:]
            bound = []
            for name, arg in zip(params, call.args):
                if isinstance(arg, ast.Starred):
                    break
                bound.append((name, arg))
            names = set(params) | {a.arg for a in d.args.kwonlyargs}
            bound += [(k.arg, k.value) for k in call.keywords if k.arg in names]
            for name, arg in bound:
                if not self.pair_valued(arg, f):
                    continue
                self._add_local(d, name, self.venue(arg, f), f"{f}:{d.name}:{name}",
                                f"parameter <- :{call.lineno} {ast.unparse(arg)[:50]}")

    def _bind_iter(self, target: ast.AST, it: ast.AST, node: ast.AST, f: str) -> None:
        while isinstance(it, ast.Call) and _callee(it) in COLLECTION_CALLS and it.args:
            it = it.args[0]
        base, meth = it, None
        if isinstance(it, ast.Call) and isinstance(it.func, ast.Attribute) and it.func.attr in ("items", "keys", "values"):
            base, meth = it.func.value, it.func.attr
        collection = self.pair_valued(base, f)          # `self.symbols`, `live_pairs`, a comprehension of pairs
        keyed = self.is_keyed(base, f)
        # a mapping's VALUES are pairs only when the mapping itself is named for them (`self.symbols`: pair -> symbol)
        named = _vocab(base.id if isinstance(base, ast.Name) else base.attr if isinstance(base, ast.Attribute) else "")
        pairs_of: list[ast.AST] = []
        if meth == "items" and isinstance(target, ast.Tuple) and len(target.elts) == 2:
            if collection or keyed:
                pairs_of.append(target.elts[0])
            if named:
                pairs_of.append(target.elts[1])
        elif meth == "values":
            if named:
                pairs_of.append(target)
        elif collection or keyed:
            pairs_of.append(target)
        for t in pairs_of:
            if isinstance(t, ast.Name):
                self._add_local(self.scope.get(t), t.id, self.venue(base, f), f"{f}:{self.function_of(node)}:{t.id}",
                                f"for-target over {ast.unparse(it)[:60]}")

    # ---- sites ----------------------------------------------------------------------------------------------
    def compare_sides(self, n: ast.Compare, f: str) -> list[ast.AST]:
        return [o for o in [n.left, *n.comparators] if self.mentions(o, f)]

    def scan(self, shapes: dict[str, Callable]) -> ScanResult:
        self.derive()
        sites: list[Site] = []
        compares = 0
        calls = {p: 0 for p in self.trees}
        for f, tree in self.trees.items():
            for n in ast.walk(tree):
                if isinstance(n, ast.Call) and _callee(n) in CANONICAL:
                    calls[f] += 1
                if isinstance(n, ast.Compare) and any(isinstance(o, EQ_OPS + IN_OPS) for o in n.ops):
                    compares += 1
                shape = next((name for name, pred in shapes.items() if pred(self, n, f)), None)
                if shape is None:
                    continue
                if isinstance(n, ast.Compare):
                    sides = self.compare_sides(n, f)
                    venue = any(self.venue(o, f) for o in sides)
                    violation = len(sides) >= 2 and venue and any(not self.canonical(o, f) for o in sides)
                    shown = tuple(ast.unparse(o) for o in sides)
                else:
                    key = n.slice if isinstance(n, ast.Subscript) else n.args[0]
                    venue = self.venue(key, f)
                    violation = venue and not self.canonical(key, f)
                    shown = (ast.unparse(key), f"<container {ast.unparse(n.value if isinstance(n, ast.Subscript) else n.func.value)}>")
                sites.append(Site(f, n.lineno, self.function_of(n), shape, ast.unparse(n), shown, venue, violation))
        vocabulary = {
            "identifiers": self.seed,
            "derived_locals": {k: v for k, v in sorted(self.local_origin.items())},
            "derived_fields": {f"{f}:{k}": ("venue" if v else "pair") for f, d in self.fields.items() for k, v in d.items()},
            "pair_keyed_containers": {f"{f}:{c}" for f, c in self.keyed},
            "canonical_delegates": self.delegates,
            "pair_returning_functions": self.pair_returning,
        }
        return ScanResult(sites, compares, calls, vocabulary)


# ---- the R15 shapes: each predicate claims only its own shape (mutually exclusive by construction) ----------------
def _is_compare_site(scan: _PairScan, n: ast.AST, f: str) -> bool:
    return (isinstance(n, ast.Compare) and any(isinstance(o, EQ_OPS + IN_OPS) for o in n.ops)
            and bool(scan.compare_sides(n, f)))


def _sql_column(scan: _PairScan, n: ast.Compare, f: str) -> bool:
    return any(isinstance(a, ast.Attribute) and isinstance(a.value, ast.Name) and a.value.id[:1].isupper()
               for side in scan.compare_sides(n, f) for a in ast.walk(side))


def _membership(n: ast.Compare) -> bool:
    return any(isinstance(o, IN_OPS) for o in n.ops)


def _attribute_compare(scan: _PairScan, n: ast.Compare, f: str) -> bool:
    sides = scan.compare_sides(n, f)
    return len(sides) >= 2 and all(isinstance(s, ast.Attribute) for s in sides)


def s1_equality(scan: _PairScan, n: ast.AST, f: str) -> bool:
    return (_is_compare_site(scan, n, f) and not _sql_column(scan, n, f) and not _membership(n)
            and not _attribute_compare(scan, n, f))


def s2_membership(scan: _PairScan, n: ast.AST, f: str) -> bool:
    return _is_compare_site(scan, n, f) and not _sql_column(scan, n, f) and _membership(n)


def s3_sql_predicate(scan: _PairScan, n: ast.AST, f: str) -> bool:
    return _is_compare_site(scan, n, f) and _sql_column(scan, n, f)


def s4_dict_key(scan: _PairScan, n: ast.AST, f: str) -> bool:
    if isinstance(n, ast.Subscript):
        key = n.slice
    elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in KEY_METHODS and n.args:
        key = n.args[0]
    else:
        return False
    return not scan.field_name(key, f) and not isinstance(key, ast.Slice) and bool(scan.mentions(key, f))


def s5_attribute_compare(scan: _PairScan, n: ast.AST, f: str) -> bool:
    return (_is_compare_site(scan, n, f) and not _sql_column(scan, n, f) and not _membership(n)
            and _attribute_compare(scan, n, f))


SHAPES: dict[str, Callable] = {
    "s1": s1_equality, "s2": s2_membership, "s3": s3_sql_predicate, "s4": s4_dict_key, "s5": s5_attribute_compare,
}


def scan_sources(files: list[tuple[str, str]], shapes: dict[str, Callable] = SHAPES) -> ScanResult:
    return _PairScan(files).scan(shapes)


def _read_targets() -> list[tuple[str, str]]:
    out = []
    for rel in TARGETS:
        path = BACKEND / rel
        assert path.is_file(), f"REFUSING: target {path} does not exist — the scan would scan nothing"
        out.append((rel, path.read_text(encoding="utf-8")))
    return out


@functools.cache
def _scan_targets() -> ScanResult:
    return scan_sources(_read_targets())


# ---- exemptions: matched by (file, enclosing function, normalised expression), NEVER by line ----------------------
@dataclass(frozen=True)
class Exempt:
    file: str
    function: str
    expr: str
    reason: str

    def matches(self, site: Site) -> bool:
        return site.file == self.file and site.function == self.function and site.expr == _norm(self.expr)


LOOP = "app/services/live/crypto_loop.py"
ALPACA = "app/services/broker/alpaca.py"

#: Violations by the rule that are one spelling by construction. Each must match EXACTLY ONE violation.
EXEMPT: tuple[Exempt, ...] = (
    Exempt(ALPACA, "_fetch_asset", "got != symbol",
           "EXACT BY DESIGN (DESIGN §1.2 #2): `get_asset(symbol)` answers in the ORDER/ASSET spelling, which is the "
           "loop's `BTC/USD`; an answer for another spelling is the venue describing a different asset and must refuse, "
           "so canonicalising here would hide exactly the mismatch the check exists for"),
    Exempt(LOOP, "_take_partials", "plan['pair'] != pair",
           "LOOP-INTERNAL L vs L (DESIGN §1.2 #12): `_tranche_plans` has one writer, `_tick_symbol`'s entry path, with "
           "`\"pair\": pair` (the loop's `BTC/USD`), and `pair` here is the tick's pair; the plan moves to the "
           "decision-id keyed book in commit (ii)"),
    Exempt(LOOP, "_resolve_decision", "self._open_decision.pop(pair, None)",
           "SIMULATOR EVENT, L vs L in commit (i) (DESIGN §1.2 #10): `pair = str(ev.get('pair'))` and `ev` arrives only "
           "through the `_on_settle` hook, which only the simulators fire (`PaperBroker`, `cft_sim`; `AlpacaAdapter` "
           "has neither `_on_settle` nor `on_tick`, B428) with the pair the loop passed to `on_tick`; `_open_decision` "
           "is keyed by the loop's pair. Commit (ii)'s SettleEvent carries the loop spelling (§2.4) and keys venue "
           "positions by decision id (§4.3) — this entry goes stale then, and must be re-examined, not re-pinned"),
    Exempt(LOOP, "_open_decision_id_from_db", "DecisionRecord.symbol == pair",
           "DB(L) vs EV(L) (DESIGN §1.2 #9): the column is written by the loop with its own pair, and the only caller "
           "passes `_resolve_decision`'s event pair, which is the loop's spelling (see the `_open_decision.pop` entry); "
           "the lookup moves to the decision id in §4"),
)

#: Sites DESIGN §1.2 #13 states as loop-internal keys (L vs L). Each must match exactly one site and must NOT be a
#: violation: an entry here never excuses anything, so a key that becomes venue-sourced fails instead of being absorbed.
LOOP_INTERNAL: tuple[Exempt, ...] = (
    Exempt(LOOP, "_mark_for", "self._marks[pair]",
           "the pass stores its Binance mark under the loop's own pair (moved from _tick_symbol by B428b (ii)'s mark chain)"),
    Exempt(LOOP, "_mark", "self._marks.get(pair, 0.0)", "read back under the same loop pair"),
    Exempt(LOOP, "_price_source", "self._marks.get(pair, 0.0)", "the prop-rules price source reads the loop pair's mark"),
)


def _dump(sites: list[Site]) -> str:
    return "\n".join(f"  {s}" for s in sites) or "  (none)"


# ---- controls -----------------------------------------------------------------------------------------------------
#: (label, the shape it must be reported as, source). Each is scanned as its own module so plants cannot feed each other.
POSITIVE = (
    ("s1 venue position == loop pair", "s1",
     "async def _has_position(self, pair):\n    return any(p.pair == pair for p in await self.paper.get_positions())\n"),
    ("s2 in a comprehension", "s2",
     "def untracked(pos, trades):\n    return pos.pair in {t.pair for t in trades}\n"),
    ("s2 in a dict comprehension", "s2",
     "def untracked(pos, trades):\n    return pos.symbol not in {t.pair: t for t in trades}\n"),
    ("s2 in a literal", "s2", "def f(p, pair, other_pair):\n    return p.pair in (pair, other_pair)\n"),
    ("s2 in a derived local (pre-B461 reconciler)", "s2",
     "def still_live(pair, live_positions):\n    live = {pos.pair for pos in live_positions}\n    return pair in live\n"),
    ("s2 in a pair-keyed container", "s2",
     "class L:\n    def tick(self, pair, price):\n        self._marks[pair] = price\n"
     "    def held(self, pos):\n        return pos.pair in self._marks\n"),
    ("s3 SQL predicate", "s3",
     "def q(pos):\n    return select(DecisionRecord).where(DecisionRecord.symbol == pos.symbol)\n"),
    ("s4 subscript key", "s4", "def mark(self, pos):\n    return self._marks[pos.pair]\n"),
    ("s4 .pop key", "s4", "def resolve(self, ev):\n    return self._open_decision.pop(ev['pair'], None)\n"),
    ("s5 attribute compare", "s5", "def same(a, b):\n    return a.symbol != b.pair\n"),
    ("s1 a home-grown normaliser is not canonical", "s1",
     "def f(p, pair):\n    norm = lambda v: v.replace('/', '').upper()\n    return norm(p.pair) == norm(pair)\n"),
    ("s1 one side canonical is still two spellings", "s1",
     "def f(a, pair):\n    return canonical_pair(a.symbol) == pair\n"),
    ("s1 venue read through a local (getattr)", "s1",
     "def f(asset, symbol):\n    got = getattr(asset, 'symbol', None)\n    return got != symbol\n"),
    ("s1 a helper comparing its parameters (the pre-B461 _same_symbol)", "s1",
     "class A:\n    def check(self, found, order):\n"
     "        return self._same(getattr(found, 'symbol', None), str(getattr(order, 'symbol', '')))\n"
     "    @staticmethod\n    def _same(a, b):\n        norm = lambda v: str(v or '').replace('/', '').upper()\n"
     "        return norm(a) == norm(b)\n"),
    ("s1 a venue-derived field (alpaca's position_id)", "s1",
     "def sweep(raw, pair):\n    row = {'position_id': str(getattr(raw, 'symbol', '') or '')}\n"
     "    return row['position_id'] == pair\n"),
)
NEGATIVE = (
    ("unrelated compare", "def f(price, stop):\n    return price == stop\n", dict(sites=0, compares=1, calls=0)),
    ("same_pair", "def f(p, pair):\n    return same_pair(p.pair, pair)\n", dict(sites=0, compares=0, calls=1)),
    ("both sides canonical", "def f(a, pair):\n    return canonical_pair(a.symbol) == canonical_pair(pair)\n",
     dict(sites=1, compares=1, calls=2)),
    ("canonical membership", "def f(pos, trades):\n"
     "    return canonical_pair(pos.symbol) in {canonical_pair(t.pair): t for t in trades}\n",
     dict(sites=1, compares=1, calls=2)),
    ("a helper comparing two LOOP pairs",
     "class L:\n    def tick(self, pair, bsym):\n        return self._eq(pair, bsym)\n"
     "    def _eq(self, a, b):\n        return a == b\n", dict(sites=1, compares=1, calls=0)),
    ("loop key, loop pair", "def f(self, pair, price):\n    self._marks[pair] = price\n", dict(sites=1, compares=0, calls=0)),
    ("position_id NOT written from a symbol here", "def f(res, pid):\n    return res.get('position_id') == pid\n",
     dict(sites=0, compares=1, calls=0)),
)


def test_the_scan_sees_every_R15_shape():
    """P-5: a plant per R15 shape is REPORTED AS THAT SHAPE, and the negatives are parsed (their site/compare/call
    counts are asserted, so a blind scanner cannot pass them) but not reported. Then each shape is ablated from the
    registry and its plants must go unseen: a plant another shape would also catch proves nothing about its own."""
    for label, shape, src in POSITIVE:
        result = scan_sources([(f"plant_{shape}.py", src)])
        assert [s.shape for s in result.violations] == [shape], (
            f"plant {label!r} must be exactly one {shape} violation; got:\n{_dump(result.sites)}\n"
            f"vocabulary:\n{result.vocabulary_text()}")
    for label, src, want in NEGATIVE:
        result = scan_sources([("negative.py", src)])
        got = dict(sites=len(result.sites), compares=result.compares_seen, calls=result.canonical_calls["negative.py"])
        assert result.violations == [] and got == want, (
            f"negative {label!r}: expected no violation and {want}, got {got}; sites:\n{_dump(result.sites)}")
    for dropped in SHAPES:
        ablated = {k: v for k, v in SHAPES.items() if k != dropped}
        for label, shape, src in POSITIVE:
            if shape == dropped:
                result = scan_sources([(f"plant_{shape}.py", src)], ablated)
                assert result.violations == [], (
                    f"with {dropped} removed, plant {label!r} is still reported, so it does not control {dropped}:\n"
                    f"{_dump(result.violations)}")


def test_the_scan_of_the_targets_is_not_vacuous():
    """An empty parse must not read as clean: floors on what the scan saw, per file and in total."""
    result = _scan_targets()
    per_file = {rel: sum(1 for s in result.sites if s.file == rel) for rel in TARGETS}
    assert len(result.sites) >= 15, f"only {len(result.sites)} pair sites in the four files: {per_file}"
    assert len(result.vocabulary["identifiers"]) >= 10, result.vocabulary_text()
    assert sum(result.canonical_calls.values()) >= 5, f"same_pair/canonical_pair calls: {result.canonical_calls}"
    # Per file: the reconcilers have NO raw pair compare left (all went through same_pair), so their sites are 0 and
    # only their canonical calls prove the scan read them. DESIGN §6: every one of the four files meets two spellings.
    assert all(result.canonical_calls[rel] >= 1 for rel in TARGETS), (
        f"a target with no same_pair/canonical_pair call was either not read or bypasses it: {result.canonical_calls}")
    for rel, src in _read_targets():
        tree = ast.parse(src)
        assert any(_vocab(n.id) for n in ast.walk(tree) if isinstance(n, ast.Name)), f"{rel}: no pair vocabulary at all"
        defined = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        assert not (defined & CANONICAL), f"{rel} defines its own {defined & CANONICAL}: a shadow is not canonical"
        if result.canonical_calls[rel]:
            imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
                        and n.module == CANONICAL_MODULE for a in n.names}
            assert imported & CANONICAL, f"{rel} calls a canonical name it does not import from {CANONICAL_MODULE}"


def test_no_two_spelling_comparison_bypasses_the_canonical_pair():
    result = _scan_targets()
    unexcused = [s for s in result.violations if not any(e.matches(s) for e in EXEMPT)]
    assert unexcused == [], (
        f"{len(unexcused)} comparison(s) meet a VENUE spelling and another pair without same_pair/canonical_pair "
        f"(app.services.broker.symbols) and are not in EXEMPT:\n{_dump(unexcused)}\n"
        f"all {len(result.sites)} sites:\n{_dump(result.sites)}\nvocabulary:\n{result.vocabulary_text()}")
    for entry in EXEMPT:
        matched = [s for s in result.violations if entry.matches(s)]
        assert len(matched) == 1, (
            f"EXEMPT entry {entry.file} [{entry.function}] `{entry.expr}` matches {len(matched)} violations "
            f"(must be exactly 1 — a stale exemption is how a scan rots):\n{_dump(matched)}\n"
            f"violations:\n{_dump(result.violations)}")
    for entry in LOOP_INTERNAL:
        matched = [s for s in result.sites if entry.matches(s)]
        assert len(matched) == 1 and not matched[0].violation, (
            f"LOOP_INTERNAL {entry.file} [{entry.function}] `{entry.expr}` must be exactly one NON-violating site; "
            f"got:\n{_dump(matched)}")


def test_a_new_bypass_in_crypto_loop_is_caught():
    """P-5's second kill: a new two-spelling compare added to crypto_loop.py without canonical_pair fails the scan."""
    rel, src = next(item for item in _read_targets() if item[0] == LOOP)
    tree = ast.parse(src)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "LiveCryptoLoop")
    anchor = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_has_position")
    lines = src.splitlines(keepends=True)
    plant = ("\n    async def _planted_bypass(self, pair: str, positions) -> bool:\n"
             "        return any(p.pair == pair for p in positions)\n")
    planted = "".join(lines[:anchor.end_lineno]) + plant + "".join(lines[anchor.end_lineno:])
    planted_cls = next(n for n in ast.parse(planted).body if isinstance(n, ast.ClassDef) and n.name == "LiveCryptoLoop")
    assert "_planted_bypass" in {n.name for n in planted_cls.body if isinstance(n, ast.AsyncFunctionDef)}, (
        "the plant did not land inside LiveCryptoLoop — the arm would test nothing")
    baseline = {(s.function, s.expr) for s in scan_sources([(rel, src)]).violations}
    after = scan_sources([(rel, planted)]).violations
    new = [s for s in after if (s.function, s.expr) not in baseline]
    assert [(s.function, s.shape, s.expr) for s in new] == [("_planted_bypass", "s1", "p.pair == pair")], (
        f"the planted bypass was not reported as exactly one new s1 violation:\n{_dump(new)}")
