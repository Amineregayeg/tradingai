"""CONTRACT 5 — the output-understanding (feedback) loop.

Consumes closed :class:`~app.models.decision_record.DecisionRecord` rows (as plain
``dict``s) and produces *structured, bounded* parameter corrections for the crypto
ICT engine.  The whole point is to close the loop between what the engine *expected*
(the signal RR geometry it committed to) and what it *actually realized* (fills,
R multiples, win rate) — and to translate any gap into a small, defensible nudge on
one of the engine's **independent** knobs.

Design rules baked in (see the CONTRACT):

* ``analyze()`` is **pure / deterministic** — no I/O, no clock, no RNG, no DB. It is a
  function of ``(records, params, min_evidence)`` only.
* Corrections may ONLY target the independent knobs in :data:`INDEPENDENT_KNOBS`.
* It MUST NEVER propose tuning ``risk_pct``. ``risk_pct`` is pre-registered FIXED at
  ``0.01``. Because ``ROI_simple = risk_pct * n * avgR`` is an *exact algebraic
  identity* (the engine computes ``pnl_pct = r_multiple * risk_pct``,
  ``engine.py:387``), ``risk_pct`` carries **zero independent information** about the
  strategy's edge — tuning it would just re-scale the account curve while emitting a
  confident-sounding rationale for a change that teaches the model nothing. Any caller
  that explicitly asks to tune ``risk_pct`` is refused with a reason
  (:func:`propose_correction`), and the internal builders raise if handed it.
* On thin evidence (``n < min_evidence``) the engine ABSTAINS: no corrections, an
  ``abstain_reason`` is set. No confident correction on a handful of trades.
* Every correction is bounded to at most ±:data:`MAX_DELTA_FRAC` of the current value
  per round and carries ``evidence_n`` and a plain-English ``rationale``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

# ---------------------------------------------------------------------------
# Knob vocabulary — the single source of truth for what may (and may NOT) be tuned.
# ---------------------------------------------------------------------------

#: The engine's INDEPENDENT knobs — the only parameters a correction may target.
#: (Mirrors the tunable fields of ``backtest.engine.Params``.)
INDEPENDENT_KNOBS: tuple[str, ...] = (
    "sl_buffer_atr",
    "rr_partial",
    "require_ltf_bos",
    "min_fvg_atr",
    "max_hold_bars",
    "runner_trail_atr",
)

#: Pre-registered FIXED parameters — never tunable. ``risk_pct`` is fixed at 0.01
#: because ROI is an exact algebraic function of it (see module docstring).
FIXED_KNOBS: tuple[str, ...] = ("risk_pct",)

#: Fallback current values (mirror ``backtest.engine.Params`` defaults) used only when
#: the caller's ``params`` dict omits a knob we want to nudge.
_KNOB_DEFAULTS: dict[str, Any] = {
    "sl_buffer_atr": 0.25,
    "rr_partial": 2.0,
    "require_ltf_bos": True,
    "min_fvg_atr": 0.05,
    "max_hold_bars": 10,
    "runner_trail_atr": 2.5,
}

#: Maximum fractional change to any numeric knob, per analysis round.
MAX_DELTA_FRAC: float = 0.25

#: The exact reason returned whenever a caller tries to tune ``risk_pct``.
RISK_PCT_REFUSAL: str = (
    "risk_pct is pre-registered FIXED at 0.01 and is NOT an independent knob. "
    "ROI_simple = risk_pct * n * avgR is an exact algebraic identity "
    "(engine computes pnl_pct = r_multiple * risk_pct), so tuning risk_pct only "
    "re-scales the equity curve — it carries zero information about the edge. "
    "Refused: emitting a correction here would be a confident rationale for a "
    "zero-information change."
)


# ---------------------------------------------------------------------------
# Outcome vocabulary — tolerant of both the DecisionRecord vocab (WIN/LOSS/BE/OPEN/
# ABSTAINED) and the backtest engine vocab (win/loss/scratch/open), case-insensitive.
# ---------------------------------------------------------------------------

_WIN_TOKENS = {"win"}
_LOSS_TOKENS = {"loss", "lose"}
_BREAKEVEN_TOKENS = {"be", "breakeven", "break_even", "scratch"}
_OPEN_TOKENS = {"open", ""}
_ABSTAIN_TOKENS = {"abstained", "abstain"}
#: The position existed; the process holding it died before it closed. Excluded
#: from the learning population for a different reason than "open" — not "not yet"
#: but "never observed". Folding it into breakeven would feed the loop a zero that
#: nobody measured (KNOWN_ISSUES A11).
_ABANDONED_TOKENS = {"abandoned"}


class RiskPctTuningRefused(ValueError):
    """Raised by internal builders if ``risk_pct`` (or any FIXED knob) is targeted."""


@dataclass(frozen=True)
class Correction:
    """A single, bounded, evidence-backed nudge to ONE independent knob.

    ``current`` / ``proposed`` may be numeric (float) or, for boolean/categorical
    knobs, a ``bool``/``str``. ``delta`` is the signed numeric change for numeric
    knobs and ``None`` for non-numeric ones.
    """

    target_param: str
    current: float | str | bool
    proposed: float | str | bool
    delta: float | None
    rationale: str
    evidence_n: int
    confidence: float


# ---------------------------------------------------------------------------
# Small, NaN-safe numeric helpers.
# ---------------------------------------------------------------------------

def _to_float(value: Any) -> float | None:
    """Coerce a record value (float / int / Decimal / str / None) to a finite float.

    Returns ``None`` for missing / non-numeric / non-finite (NaN, ±inf) values so
    callers can cleanly skip them rather than propagating NaN through a mean.
    """
    if value is None or isinstance(value, bool):
        # NB: bool is a subclass of int — never treat True/False as a number here.
        return None
    if isinstance(value, Decimal):
        try:
            value = float(value)
        except (ValueError, ArithmeticError):
            return None
    if isinstance(value, (int, float)):
        f = float(value)
        return f if math.isfinite(f) else None
    if isinstance(value, str):
        try:
            f = float(value.strip())
        except ValueError:
            return None
        return f if math.isfinite(f) else None
    return None


def _mean(xs: list[float]) -> float | None:
    """Arithmetic mean of a list of finite floats, or ``None`` if empty."""
    return (sum(xs) / len(xs)) if xs else None


def _clamp(x: float, lo: float, hi: float) -> float:
    """Clamp ``x`` to ``[lo, hi]`` without any bare min/max on possibly-NaN input."""
    if not math.isfinite(x):
        return lo
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def _first(rec: dict, *keys: str) -> Any:
    """First present, non-None value among ``keys`` in ``rec``."""
    for k in keys:
        if k in rec and rec[k] is not None:
            return rec[k]
    return None


# ---------------------------------------------------------------------------
# Per-record derivations.
# ---------------------------------------------------------------------------

def _classify_outcome(rec: dict, realized_r: float | None) -> str:
    """Return one of 'win' | 'loss' | 'be' | 'open' | 'abstained' | 'abandoned'.

    Prefers an explicit ``outcome`` token (case-insensitive, both vocabularies);
    falls back to the sign of ``realized_r`` when no token is present.
    """
    raw = _first(rec, "outcome")
    if raw is not None:
        tok = str(raw).strip().lower()
        if tok in _WIN_TOKENS:
            return "win"
        if tok in _LOSS_TOKENS:
            return "loss"
        if tok in _BREAKEVEN_TOKENS:
            return "be"
        if tok in _ABSTAIN_TOKENS:
            return "abstained"
        if tok in _OPEN_TOKENS:
            return "open"
        if tok in _ABANDONED_TOKENS:
            return "abandoned"
    # An explicit abstained flag also means "no trade".
    if bool(rec.get("abstained")):
        return "abstained"
    if realized_r is None:
        return "open"
    if realized_r > 1e-9:
        return "win"
    if realized_r < -1e-9:
        return "loss"
    return "be"


def _expected_r_from_geometry(entry: float | None, sl: float | None, tp: float | None) -> float | None:
    """Targeted reward-to-risk multiple implied by the signal geometry.

    ``expected_r = |tp - entry| / |entry - sl|`` — the R the trade is *committed* to
    if it reaches its take-profit. Direction-agnostic (works for LONG and SHORT).
    ``None`` when any leg is missing or the risk leg is degenerate.
    """
    if entry is None or sl is None or tp is None:
        return None
    risk = abs(entry - sl)
    if risk <= 1e-12:
        return None
    reward = abs(tp - entry)
    return reward / risk


def _slippage_r(rec: dict, direction: str | None, entry: float | None, sl: float | None) -> float | None:
    """Adverse fill slippage in R: (signal_entry vs actual fill) / risk_per_unit.

    Positive => filled WORSE than the signal (paid up on a long / sold down on a
    short). Requires an actual fill price on the record — decision rows don't store
    one, so this is computed only when a fill key is present; otherwise ``None``.
    """
    fill = _to_float(_first(rec, "fill_price", "actual_fill", "actual_entry", "filled_price", "fill_entry"))
    if fill is None or entry is None or sl is None:
        return None
    risk = abs(entry - sl)
    if risk <= 1e-12:
        return None
    d = (direction or "").strip().upper()
    if d.startswith("L"):  # LONG: paying more than signal is adverse
        return (fill - entry) / risk
    if d.startswith("S"):  # SHORT: selling for less than signal is adverse
        return (entry - fill) / risk
    return None


@dataclass
class _RecordView:
    """The subset of a closed record the feedback maths needs."""

    direction: str | None
    entry: float | None
    sl: float | None
    tp: float | None
    expected_r: float | None
    realized_r: float | None
    slippage_r: float | None
    outcome: str  # win|loss|be


def _closed_views(records: list[dict]) -> list[_RecordView]:
    """Project the closed (resolved) records into the fields the analysis uses.

    A record is *closed* when its outcome resolves to win/loss/be (or a realized_r
    is present without an OPEN/ABSTAINED marker). OPEN and ABSTAINED rows carry no
    realized information and are excluded from the evidence count.
    """
    views: list[_RecordView] = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        direction = _first(rec, "signal_dir", "direction", "dir")
        direction = str(direction).strip() if direction is not None else None
        entry = _to_float(_first(rec, "signal_entry", "entry"))
        sl = _to_float(_first(rec, "signal_sl", "sl", "stop"))
        tp = _to_float(_first(rec, "signal_tp", "tp", "target"))
        realized_r = _to_float(_first(rec, "realized_r", "r_multiple", "r"))

        outcome = _classify_outcome(rec, realized_r)
        if outcome in ("open", "abstained", "abandoned"):
            continue
        if realized_r is None:
            # Resolved but no numeric R to learn from — nothing to measure.
            continue

        expected_r = _to_float(_first(rec, "expected_r"))
        if expected_r is None:
            expected_r = _expected_r_from_geometry(entry, sl, tp)

        views.append(
            _RecordView(
                direction=direction,
                entry=entry,
                sl=sl,
                tp=tp,
                expected_r=expected_r,
                realized_r=realized_r,
                slippage_r=_slippage_r(rec, direction, entry, sl),
                outcome=outcome,
            )
        )
    return views


# ---------------------------------------------------------------------------
# Correction builders — the ONLY place corrections are minted. Every path here
# runs through ``_guard_param`` so a FIXED knob can never escape into the output.
# ---------------------------------------------------------------------------

def _guard_param(target_param: str) -> None:
    """Raise if ``target_param`` is not a tunable independent knob."""
    if target_param in FIXED_KNOBS or target_param == "risk_pct":
        raise RiskPctTuningRefused(RISK_PCT_REFUSAL)
    if target_param not in INDEPENDENT_KNOBS:
        raise ValueError(f"{target_param!r} is not an independent, tunable knob.")


def _confidence(magnitude_norm: float, n: int, min_evidence: int) -> float:
    """Deterministic confidence in [0.1, 0.9] from effect size and sample size."""
    denom = 2 * max(min_evidence, 1)
    evidence_factor = _clamp(n / denom, 0.0, 1.0)
    mag = _clamp(magnitude_norm, 0.0, 1.0)
    return round(_clamp(0.9 * mag * evidence_factor, 0.1, 0.9), 3)


def _numeric_correction(
    target_param: str,
    current: Any,
    frac_change: float,
    rationale: str,
    n: int,
    confidence: float,
) -> Correction | None:
    """Build a bounded numeric correction (proposed = current * (1 + frac_change)).

    ``frac_change`` is clamped to ±:data:`MAX_DELTA_FRAC`. Returns ``None`` if the
    current value is unusable (missing / non-finite / zero, so a multiplicative
    nudge would be meaningless).
    """
    _guard_param(target_param)
    cur = _to_float(current)
    if cur is None or cur == 0.0:
        return None
    frac = _clamp(frac_change, -MAX_DELTA_FRAC, MAX_DELTA_FRAC)
    if abs(frac) < 1e-9:
        return None
    proposed = cur * (1.0 + frac)
    delta = proposed - cur
    return Correction(
        target_param=target_param,
        current=round(cur, 6),
        proposed=round(proposed, 6),
        delta=round(delta, 6),
        rationale=rationale,
        evidence_n=n,
        confidence=confidence,
    )


def _bool_correction(
    target_param: str,
    current: bool,
    proposed: bool,
    rationale: str,
    n: int,
    confidence: float,
) -> Correction | None:
    """Build a boolean flip correction (delta is ``None`` for non-numeric knobs)."""
    _guard_param(target_param)
    if bool(current) == bool(proposed):
        return None
    return Correction(
        target_param=target_param,
        current=bool(current),
        proposed=bool(proposed),
        delta=None,
        rationale=rationale,
        evidence_n=n,
        confidence=confidence,
    )


def propose_correction(
    target_param: str,
    current: Any,
    frac_change: float = 0.0,
    *,
    rationale: str = "",
    evidence_n: int = 0,
    confidence: float = 0.0,
) -> dict:
    """Caller-facing single-correction builder that REFUSES ``risk_pct``.

    Returns ``{"refused": True, "reason": ...}`` if asked to tune ``risk_pct`` (or any
    FIXED knob), rather than raising, so a UI can surface the reason. For a legitimate
    independent knob it returns ``{"refused": False, "correction": Correction|None}``.
    """
    if target_param in FIXED_KNOBS or target_param == "risk_pct":
        return {"refused": True, "target_param": target_param, "reason": RISK_PCT_REFUSAL}
    corr = _numeric_correction(
        target_param, current, frac_change, rationale, evidence_n, confidence
    )
    return {"refused": False, "target_param": target_param, "correction": corr}


# ---------------------------------------------------------------------------
# The pure core.
# ---------------------------------------------------------------------------

def analyze(records: list[dict], params: dict, min_evidence: int = 30) -> dict:
    """Compare expected-vs-actual across closed decisions and emit bounded corrections.

    Pure and deterministic — a function of ``(records, params, min_evidence)`` only.

    Parameters
    ----------
    records:
        Closed decision rows as dicts (see ``DecisionRecord``). OPEN/ABSTAINED rows
        are ignored for the evidence count.
    params:
        Current knob values, e.g. the engine's ``Params`` as a dict. Missing knobs
        fall back to :data:`_KNOB_DEFAULTS`. ``risk_pct`` here is read-only context —
        it is never a correction target.
    min_evidence:
        Minimum number of closed records required before any correction is emitted.

    Returns
    -------
    dict with keys: ``n``, ``expected_vs_actual``, ``gaps``, ``corrections`` (list of
    :class:`Correction`), ``abstained`` (bool), ``abstain_reason`` (str|None).
    """
    params = params or {}
    views = _closed_views(records or [])
    n = len(views)

    # --- expected vs actual (computed over whatever closed evidence exists) ------
    expected_rs = [v.expected_r for v in views if v.expected_r is not None]
    realized_rs = [v.realized_r for v in views if v.realized_r is not None]
    slippages = [v.slippage_r for v in views if v.slippage_r is not None]

    mean_expected_r = _mean(expected_rs)
    mean_realized_r = _mean(realized_rs)
    mean_slippage_r = _mean(slippages)

    wins = sum(1 for v in views if v.outcome == "win")
    actual_win_rate = (wins / n) if n else None

    # WINNER-CONDITIONAL realized-vs-target (the ONLY like-for-like basis for
    # judging rr_partial). Comparing the mean realized R over ALL trades (which
    # includes losers at ~-1R) to the planned RR (which only winners can reach)
    # is a category error: the difference is structurally negative for any real
    # strategy and would ratchet rr_partial down forever. We instead ask, among
    # trades that WON, did they reach / overshoot the RR they targeted?
    winner_views = [
        v for v in views
        if v.outcome == "win" and v.realized_r is not None and v.expected_r is not None
    ]
    loser_views = [v for v in views if v.outcome == "loss" and v.realized_r is not None]
    n_winners = len(winner_views)
    mean_winner_realized_r = _mean([v.realized_r for v in winner_views])
    mean_winner_target_r = _mean([v.expected_r for v in winner_views])
    mean_loser_realized_r = _mean([v.realized_r for v in loser_views])
    winner_realized_minus_target_r = (
        (mean_winner_realized_r - mean_winner_target_r)
        if (mean_winner_realized_r is not None and mean_winner_target_r is not None)
        else None
    )

    # Break-even win rate from REALIZED geometry, not the target RR. Winners can
    # realize far MORE than the target (runners), so 1/(1+target_RR) understates
    # the true break-even and would flag a profitable runner strategy as
    # sub-break-even (the same category error as the old Rule A). Correct form:
    #   be = |avg_loss| / (avg_win + |avg_loss|)   using realized R.
    expected_win_rate = None
    if (
        mean_winner_realized_r is not None
        and mean_loser_realized_r is not None
        and n_winners > 0
        and len(loser_views) > 0
    ):
        avg_win = mean_winner_realized_r
        avg_loss = abs(mean_loser_realized_r)
        denom = avg_win + avg_loss
        if denom > 1e-9:
            expected_win_rate = avg_loss / denom

    expected_vs_actual = {
        "n_closed": n,
        "n_with_expected_r": len(expected_rs),
        "n_with_slippage": len(slippages),
        "mean_expected_r": mean_expected_r,
        "mean_realized_r": mean_realized_r,
        "mean_slippage_r": mean_slippage_r,
        "actual_win_rate": actual_win_rate,
        "expected_win_rate": expected_win_rate,  # break-even from REALIZED geometry
        "n_winners": n_winners,
        "mean_winner_realized_r": mean_winner_realized_r,
        "mean_winner_target_r": mean_winner_target_r,
        "mean_loser_realized_r": mean_loser_realized_r,
    }

    # --- structured gaps ---------------------------------------------------------
    win_rate_gap = (
        (actual_win_rate - expected_win_rate)
        if (actual_win_rate is not None and expected_win_rate is not None)
        else None
    )
    gaps = {
        # like-for-like: winners' realized R vs the RR they targeted
        "winner_realized_minus_target_r": winner_realized_minus_target_r,
        "mean_slippage_r": mean_slippage_r,
        "win_rate_gap": win_rate_gap,
    }

    # --- thin-evidence abstain ---------------------------------------------------
    if n < min_evidence:
        return {
            "n": n,
            "expected_vs_actual": expected_vs_actual,
            "gaps": gaps,
            "corrections": [],
            "abstained": True,
            "abstain_reason": (
                f"insufficient evidence: {n} closed record(s) < min_evidence={min_evidence}; "
                "no confident correction on thin data."
            ),
        }

    corrections: list[Correction] = []

    def _cur(knob: str) -> Any:
        return params.get(knob, _KNOB_DEFAULTS.get(knob))

    # Rule A — WINNERS' realized R vs the RR they targeted (rr_partial).
    # Like-for-like (winner-conditional both sides), so it is NOT the one-way
    # ratchet the all-trades mean gap would be. Requires enough winners to matter.
    _MIN_WINNERS = 10
    if (
        winner_realized_minus_target_r is not None
        and n_winners >= _MIN_WINNERS
        and mean_winner_target_r not in (None, 0.0)
    ):
        gap = winner_realized_minus_target_r
        if gap < -0.25:
            # Winners systematically fall SHORT of their target (reverse before it):
            # the partial is too greedy — bank it sooner.
            frac = -_clamp(abs(gap) / abs(mean_winner_target_r), 0.0, MAX_DELTA_FRAC)
            mag = _clamp(abs(gap) / 1.0, 0.0, 1.0)
            corr = _numeric_correction(
                "rr_partial",
                _cur("rr_partial"),
                frac,
                rationale=(
                    f"Winning trades realize {mean_winner_realized_r:.2f}R vs the "
                    f"{mean_winner_target_r:.2f}R they targeted ({gap:.2f}R short) over "
                    f"{n_winners} winners; the partial target is too greedy — bank it sooner."
                ),
                n=n_winners,
                confidence=_confidence(mag, n_winners, min_evidence),
            )
            if corr is not None:
                corrections.append(corr)
        elif gap > 0.25:
            # Winners overshoot the target (runners keep extending): raise it.
            frac = _clamp(abs(gap) / abs(mean_winner_target_r), 0.0, MAX_DELTA_FRAC)
            mag = _clamp(abs(gap) / 1.0, 0.0, 1.0)
            corr = _numeric_correction(
                "rr_partial",
                _cur("rr_partial"),
                frac,
                rationale=(
                    f"Winning trades realize {mean_winner_realized_r:.2f}R vs the "
                    f"{mean_winner_target_r:.2f}R they targeted ({gap:+.2f}R over) across "
                    f"{n_winners} winners; the target is left on the table — raise it."
                ),
                n=n_winners,
                confidence=_confidence(mag, n_winners, min_evidence),
            )
            if corr is not None:
                corrections.append(corr)

    # Rule B — adverse fill slippage (min_fvg_atr).
    # Chronic adverse fills => demand a larger, cleaner imbalance before entering.
    if mean_slippage_r is not None and mean_slippage_r > 0.05:
        frac = _clamp(mean_slippage_r / 0.20, 0.0, MAX_DELTA_FRAC)
        mag = _clamp(mean_slippage_r / 0.20, 0.0, 1.0)
        corr = _numeric_correction(
            "min_fvg_atr",
            _cur("min_fvg_atr"),
            frac,
            rationale=(
                f"Mean adverse fill slippage is {mean_slippage_r:.3f}R across "
                f"{len(slippages)} filled trades; require a larger min FVG size so "
                "entries sit in cleaner imbalances that fill nearer the signal."
            ),
            n=n,
            confidence=_confidence(mag, n, min_evidence),
        )
        if corr is not None:
            corrections.append(corr)

    # Rule C — win rate below break-even (sl_buffer_atr).
    # Getting stopped more often than the geometry can afford => give trades room.
    if win_rate_gap is not None and win_rate_gap < -0.05:
        frac = _clamp(abs(win_rate_gap) / 0.30, 0.0, MAX_DELTA_FRAC)
        mag = _clamp(abs(win_rate_gap) / 0.30, 0.0, 1.0)
        corr = _numeric_correction(
            "sl_buffer_atr",
            _cur("sl_buffer_atr"),
            frac,
            rationale=(
                f"Actual win rate ({actual_win_rate:.0%}) is below the break-even rate "
                f"({expected_win_rate:.0%}) implied by the REALIZED win/loss geometry "
                f"(avg win {mean_winner_realized_r:.2f}R vs avg loss {mean_loser_realized_r:.2f}R; "
                f"gap {win_rate_gap:+.0%}, n={n}); widen the SL buffer to cut premature "
                "stop-outs before the setup resolves."
            ),
            n=n,
            confidence=_confidence(mag, n, min_evidence),
        )
        if corr is not None:
            corrections.append(corr)

    # Rule D — badly negative edge with entry filter off (require_ltf_bos).
    # A materially sub-break-even hit rate with the LTF-BOS confirmation disabled
    # points at low-quality entries — turn the confirmation on.
    if (
        win_rate_gap is not None
        and win_rate_gap < -0.10
        and bool(_cur("require_ltf_bos")) is False
    ):
        mag = _clamp(abs(win_rate_gap) / 0.30, 0.0, 1.0)
        corr = _bool_correction(
            "require_ltf_bos",
            current=False,
            proposed=True,
            rationale=(
                f"Win rate ({actual_win_rate:.0%}) sits {win_rate_gap:+.0%} under "
                f"break-even over {n} trades with LTF-BOS confirmation OFF; require a "
                "same-direction LTF break before entry to raise setup quality."
            ),
            n=n,
            confidence=_confidence(mag, n, min_evidence),
        )
        if corr is not None:
            corrections.append(corr)

    # Deterministic order: strongest evidence first, then knob name for stable ties.
    corrections.sort(key=lambda c: (-c.confidence, c.target_param))

    return {
        "n": n,
        "expected_vs_actual": expected_vs_actual,
        "gaps": gaps,
        "corrections": corrections,
        "abstained": False,
        "abstain_reason": None,
    }
