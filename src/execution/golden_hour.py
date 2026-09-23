"""Phase 4 — Golden Hour : suivi du marché sur les 60 minutes suivant le tir.

Tourne sur son propre thread, indépendant du Sniper et du TelemetryWorker :
un callback WebSocket lent ne doit jamais ralentir l'exécution des ordres, et
les écritures de télémétrie restent fire-and-forget via la file d'attente.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from alpaca.data.live import StockDataStream

from src.config import AlpacaConfig, RiskConfig
from src.core.risk_manager import (
    TrailingStopState,
    init_trailing_stop,
    should_exit_position,
    update_trailing_stop,
)
from src.data.db_worker import GoldenHourTick, TelemetryWorker
from src.execution.alpaca_router import AlpacaRouter

logger = logging.getLogger(__name__)


class GoldenHourTracker:
    """Collecte VWAP/bougies pendant `risk_config.golden_hour_minutes` et
    applique le Circuit Breaker Risque (Stop-Loss / Take-Profit / Trailing
    Stop dynamique)."""

    def __init__(
        self,
        symbol: str,
        entry_price: Decimal,
        trade_audit_id: Optional[int],
        alpaca_config: AlpacaConfig,
        risk_config: RiskConfig,
        router: AlpacaRouter,
        telemetry: TelemetryWorker,
    ):
        self._symbol = symbol
        self._trade_audit_id = trade_audit_id
        self._risk_config = risk_config
        self._router = router
        self._telemetry = telemetry
        self._deadline = datetime.now(timezone.utc) + timedelta(minutes=risk_config.golden_hour_minutes)
        self._stop_state: TrailingStopState = init_trailing_stop(entry_price, risk_config)
        self._stream = StockDataStream(alpaca_config.api_key, alpaca_config.api_secret, feed=alpaca_config.data_feed)
        self._position_closed = threading.Event()

    def start(self) -> None:
        self._stream.subscribe_bars(self._on_bar, self._symbol)
        threading.Thread(target=self._run_stream, name=f"golden-hour-{self._symbol}", daemon=True).start()

    def _run_stream(self) -> None:
        try:
            self._stream.run()
        except Exception:
            logger.exception("Golden Hour stream crashed for %s", self._symbol)

    async def _on_bar(self, bar) -> None:
        if self._position_closed.is_set():
            return

        price = Decimal(str(bar.close))
        self._telemetry.record_tick(
            GoldenHourTick(
                symbol=self._symbol,
                timestamp=bar.timestamp,
                price=price,
                volume=int(bar.volume),
                vwap=Decimal(str(bar.vwap)) if getattr(bar, "vwap", None) is not None else None,
                trade_audit_id=self._trade_audit_id,
            )
        )

        self._stop_state = update_trailing_stop(self._stop_state, price, self._risk_config)
        exit_reason = should_exit_position(self._stop_state, price, self._risk_config)

        if exit_reason is not None:
            self._exit_position(exit_reason)
        elif datetime.now(timezone.utc) >= self._deadline:
            self._exit_position("golden_hour_expired")

    def _exit_position(self, reason: str) -> None:
        if self._position_closed.is_set():
            return
        self._position_closed.set()
        logger.info("Closing %s position: %s", self._symbol, reason)
        try:
            self._router.close_position(self._symbol)
        finally:
            self._stream.stop()
