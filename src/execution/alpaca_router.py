"""Routage des ordres et lecture du spread bid/ask via Alpaca.

Les deux clients Alpaca (trading + data) sont instanciés une seule fois en
Phase 1 (Pre-Market) et réutilisés pour chaque symbole : le coût du handshake
TCP/TLS est payé avant l'annonce, jamais pendant.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import LimitOrderRequest

from src.config import AlpacaConfig, RiskConfig
from src.core.risk_manager import LiquidityCheck, check_liquidity

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QuoteSnapshot:
    bid_price: Decimal
    ask_price: Decimal
    bid_size: int
    ask_size: int

    @property
    def book_volume(self) -> int:
        return self.bid_size + self.ask_size


class AlpacaRouter:
    def __init__(self, config: AlpacaConfig, risk_config: RiskConfig, paper: bool = True):
        config.require_credentials()
        self._config = config
        self._risk_config = risk_config
        self.trading_client = TradingClient(
            config.api_key, config.api_secret, paper=paper, url_override=config.base_url
        )
        self.data_client = StockHistoricalDataClient(config.api_key, config.api_secret)

    def get_quote(self, symbol: str) -> QuoteSnapshot:
        request = StockLatestQuoteRequest(symbol_or_symbols=symbol, feed=self._config.data_feed)
        quote = self.data_client.get_stock_latest_quote(request)[symbol]
        return QuoteSnapshot(
            bid_price=Decimal(str(quote.bid_price)),
            ask_price=Decimal(str(quote.ask_price)),
            bid_size=int(quote.bid_size),
            ask_size=int(quote.ask_size),
        )

    def check_liquidity_circuit_breaker(self, symbol: str) -> tuple[QuoteSnapshot, LiquidityCheck]:
        quote = self.get_quote(symbol)
        return quote, check_liquidity(quote.bid_price, quote.ask_price, quote.book_volume, self._risk_config)

    def send_limit_order(
        self,
        symbol: str,
        qty: int,
        limit_price: Decimal,
        side: OrderSide = OrderSide.BUY,
        time_in_force: TimeInForce = TimeInForce.DAY,
    ) -> str:
        """Toujours un ordre LIMIT, jamais MARKET : un gap déclenché par un
        8-K est exactement la situation où un prix d'exécution non borné est
        dangereux."""
        request = LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=side,
            time_in_force=time_in_force,
            limit_price=float(limit_price),
        )
        order = self.trading_client.submit_order(request)
        logger.info("Order submitted: %s %s x%d @ %s -> id=%s", side, symbol, qty, limit_price, order.id)
        return str(order.id)

    def close_position(self, symbol: str) -> None:
        self.trading_client.close_position(symbol)
