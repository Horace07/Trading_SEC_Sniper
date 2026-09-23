"""Vérifie que le Sniper ne trade que sur un vrai beat vs consensus, et
jamais sur un miss, un consensus manquant ou une extraction Regex peu fiable."""

from decimal import Decimal

from src.config import RiskConfig
from src.core.nlp_regex import ExtractionResult
from src.core.signal import SignalReason, evaluate_earnings_surprise


def _risk_config(**overrides) -> RiskConfig:
    base = dict(
        max_spread_pct=1.5,
        min_book_volume=100,
        max_position_notional_usd=5000,
        stop_loss_pct=3.0,
        take_profit_pct=5.0,
        trailing_stop_pct=2.0,
        golden_hour_minutes=60,
        min_eps_surprise_pct=0.0,
        min_regex_confidence=0.5,
    )
    base.update(overrides)
    return RiskConfig(**base)


def _extraction(eps=None, revenue=None, confidence=1.0) -> ExtractionResult:
    return ExtractionResult(eps=eps, revenue=revenue, raw_snippet="", confidence=confidence)


def test_eps_beat_triggers_buy():
    extraction = _extraction(eps=Decimal("2.35"), revenue=Decimal("500000000"))
    signal = evaluate_earnings_surprise(extraction, Decimal("2.00"), Decimal("480000000"), _risk_config())
    assert signal.side == "buy"
    assert signal.reason == SignalReason.EPS_BEAT
    assert signal.eps_surprise_pct == (Decimal("0.35") / Decimal("2.00")) * 100


def test_eps_miss_does_not_trade():
    extraction = _extraction(eps=Decimal("1.80"), revenue=Decimal("500000000"))
    signal = evaluate_earnings_surprise(extraction, Decimal("2.00"), Decimal("480000000"), _risk_config())
    assert signal.side is None
    assert signal.reason == SignalReason.EPS_MISS_OR_INLINE
    assert signal.eps_surprise_pct < 0


def test_eps_exactly_in_line_does_not_trade():
    extraction = _extraction(eps=Decimal("2.00"))
    signal = evaluate_earnings_surprise(extraction, Decimal("2.00"), None, _risk_config())
    assert signal.side is None
    assert signal.reason == SignalReason.EPS_MISS_OR_INLINE


def test_missing_regex_eps_does_not_trade():
    extraction = _extraction(eps=None, revenue=Decimal("500000000"))
    signal = evaluate_earnings_surprise(extraction, Decimal("2.00"), Decimal("480000000"), _risk_config())
    assert signal.side is None
    assert signal.reason == SignalReason.MISSING_EPS


def test_missing_consensus_does_not_trade():
    extraction = _extraction(eps=Decimal("2.35"))
    signal = evaluate_earnings_surprise(extraction, None, None, _risk_config())
    assert signal.side is None
    assert signal.reason == SignalReason.NO_CONSENSUS


def test_low_regex_confidence_does_not_trade_even_on_a_beat():
    # Confiance 0.5 (un seul des deux champs trouvé) sous le seuil par défaut (0.5 exclu ? non, 0.5 == seuil).
    extraction = _extraction(eps=Decimal("2.35"), confidence=0.4)
    signal = evaluate_earnings_surprise(extraction, Decimal("2.00"), None, _risk_config(min_regex_confidence=0.5))
    assert signal.side is None
    assert signal.reason == SignalReason.LOW_REGEX_CONFIDENCE


def test_custom_min_surprise_threshold_filters_small_beats():
    extraction = _extraction(eps=Decimal("2.01"))
    signal = evaluate_earnings_surprise(
        extraction, Decimal("2.00"), None, _risk_config(min_eps_surprise_pct=1.0)
    )
    assert signal.side is None
    assert signal.reason == SignalReason.EPS_MISS_OR_INLINE


def test_revenue_surprise_is_informative_but_never_blocks():
    # Revenue miss malgré un EPS beat : le trade part quand même (pas de gate sur revenue).
    extraction = _extraction(eps=Decimal("2.35"), revenue=Decimal("400000000"))
    signal = evaluate_earnings_surprise(extraction, Decimal("2.00"), Decimal("500000000"), _risk_config())
    assert signal.side == "buy"
    assert signal.revenue_surprise_pct < 0
