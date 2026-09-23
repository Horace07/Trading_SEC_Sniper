"""Simulation de spreads énormes et de carnets vides pour vérifier que le
Circuit Breaker Liquidité annule bien le trade, ainsi que les circuits de
risque (stop-loss / take-profit / trailing stop) de la Golden Hour."""

from decimal import Decimal

from src.config import RiskConfig
from src.core.risk_manager import (
    CircuitBreakerReason,
    check_liquidity,
    init_trailing_stop,
    position_size,
    should_exit_position,
    update_trailing_stop,
)


def _risk_config(**overrides) -> RiskConfig:
    base = dict(
        max_spread_pct=1.5,
        min_book_volume=100,
        max_position_notional_usd=5000,
        stop_loss_pct=3.0,
        take_profit_pct=5.0,
        trailing_stop_pct=2.0,
        golden_hour_minutes=60,
    )
    base.update(overrides)
    return RiskConfig(**base)


def test_normal_spread_passes():
    result = check_liquidity(Decimal("100.00"), Decimal("100.10"), book_volume=500, risk_config=_risk_config())
    assert result.passed is True
    assert result.reason == CircuitBreakerReason.NONE


def test_huge_spread_cancels_the_trade():
    # Spread énorme (10 %) simulant un carnet qui n'a pas encore digéré l'annonce.
    result = check_liquidity(Decimal("100.00"), Decimal("110.00"), book_volume=500, risk_config=_risk_config())
    assert result.passed is False
    assert result.reason == CircuitBreakerReason.SPREAD_TOO_WIDE


def test_empty_book_cancels_the_trade():
    result = check_liquidity(Decimal("100.00"), Decimal("100.10"), book_volume=0, risk_config=_risk_config())
    assert result.passed is False
    assert result.reason == CircuitBreakerReason.BOOK_EMPTY


def test_thin_book_below_minimum_cancels_the_trade():
    result = check_liquidity(Decimal("100.00"), Decimal("100.10"), book_volume=10, risk_config=_risk_config())
    assert result.passed is False
    assert result.reason == CircuitBreakerReason.BOOK_EMPTY


def test_zero_or_negative_quotes_never_raise():
    result = check_liquidity(Decimal("0"), Decimal("0"), book_volume=0, risk_config=_risk_config())
    assert result.passed is False


def test_position_size_respects_notional_cap():
    qty = position_size(account_equity=Decimal("100000"), entry_price=Decimal("50"), risk_config=_risk_config())
    # Plafonné à 5000 USD, pas aux 100000 USD d'equity.
    assert qty == 100


def test_position_size_zero_when_price_is_zero():
    assert position_size(Decimal("10000"), Decimal("0"), _risk_config()) == 0


def test_stop_loss_triggers_below_entry():
    config = _risk_config()
    state = init_trailing_stop(Decimal("100.00"), config)
    assert should_exit_position(state, Decimal("96.00"), config) == "stop_loss"


def test_take_profit_triggers_above_entry():
    config = _risk_config()
    state = init_trailing_stop(Decimal("100.00"), config)
    assert should_exit_position(state, Decimal("106.00"), config) == "take_profit"


def test_trailing_stop_follows_the_high_water_mark():
    # take_profit_pct désactivé (999%) pour isoler le comportement du trailing stop.
    config = _risk_config(take_profit_pct=999.0)
    state = init_trailing_stop(Decimal("100.00"), config)

    # Le prix monte : le stop doit suivre à la hausse.
    state = update_trailing_stop(state, Decimal("120.00"), config)
    assert state.high_water_mark == Decimal("120.00")
    assert state.stop_price == Decimal("120.00") * Decimal("0.98")

    # Repli sous le nouveau trailing stop (mais au-dessus du stop-loss dur et
    # sous le take-profit) : doit déclencher 'trailing_stop'.
    reason = should_exit_position(state, Decimal("117.00"), config)
    assert reason == "trailing_stop"


def test_trailing_stop_never_retreats():
    config = _risk_config()
    state = init_trailing_stop(Decimal("100.00"), config)
    state = update_trailing_stop(state, Decimal("120.00"), config)
    # Un prix inférieur au plus haut ne doit jamais faire reculer le stop.
    state_after = update_trailing_stop(state, Decimal("110.00"), config)
    assert state_after.stop_price == state.stop_price
