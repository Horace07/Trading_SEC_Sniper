"""Chef d'orchestre : enchaîne les Phases 1 à 4.

Toute la mesure de latence est faite ici, sous forme de timestamps passés
directement dans un `TradeAuditEvent` remis au TelemetryWorker — le Sniper
lui-même n'importe jamais `psycopg2` et ne fait aucune I/O base de données.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal

from src.config import settings
from src.core.nlp_regex import extract_financials
from src.core.risk_manager import position_size
from src.data.db_worker import TelemetryWorker, TradeAuditEvent
from src.data.sec_client import FilingEvent, SECClient
from src.execution.alpaca_router import AlpacaRouter
from src.execution.golden_hour import GoldenHourTracker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("main_sniper")


class Sniper:
    def __init__(self) -> None:
        self.sec_client = SECClient(settings.sec)
        self.router = AlpacaRouter(settings.alpaca, settings.risk)
        self.telemetry = TelemetryWorker(settings.database)

    def start(self) -> None:
        """Phase 1 — Pre-Market : connexions persistantes + archiviste en marche."""
        self.telemetry.start()
        logger.info("Sniper armé. Connexions Keep-Alive ouvertes, worker télémétrie actif.")

    def handle_filing(self, filing: FilingEvent) -> None:
        """Phase 2 + 3 : détection, extraction, vérification liquidité, tir, log."""
        t_publish = datetime.now(timezone.utc)

        raw_text = self.sec_client.download_document_text(filing)
        extraction = extract_financials(raw_text)
        t_regex_done = datetime.now(timezone.utc)

        quote, liquidity = self.router.check_liquidity_circuit_breaker(filing.symbol)
        t_spread_checked = datetime.now(timezone.utc)

        event = TradeAuditEvent(
            symbol=filing.symbol,
            filing_accession_number=filing.accession_number,
            timestamp_sec_publish=t_publish,
            timestamp_regex_done=t_regex_done,
            timestamp_spread_checked=t_spread_checked,
            raw_text_snippet=extraction.raw_snippet,
            regex_eps=extraction.eps,
            regex_revenue=extraction.revenue,
            regex_confidence=extraction.confidence,
            alpaca_bid_price=quote.bid_price,
            alpaca_ask_price=quote.ask_price,
            alpaca_bid_ask_spread_at_execution=liquidity.spread_pct,
            alpaca_book_volume=quote.book_volume,
        )

        if not liquidity.passed:
            event.order_status = "cancelled"
            event.circuit_breaker_triggered = True
            event.circuit_breaker_reason = liquidity.reason.value
            self.telemetry.record_trade_audit(event)
            logger.warning("Circuit breaker liquidité déclenché pour %s: %s", filing.symbol, liquidity.reason.value)
            return

        qty = position_size(account_equity=Decimal("10000"), entry_price=quote.ask_price, risk_config=settings.risk)
        if qty <= 0:
            event.order_status = "cancelled"
            event.circuit_breaker_reason = "position_size_zero"
            self.telemetry.record_trade_audit(event)
            return

        order_id = self.router.send_limit_order(filing.symbol, qty, quote.ask_price)
        event.timestamp_order_sent = datetime.now(timezone.utc)
        event.order_id = order_id
        event.order_side = "buy"
        event.order_qty = Decimal(qty)
        event.order_limit_price = quote.ask_price
        event.order_status = "submitted"

        # Fire-and-forget : Queue.put(), pas une écriture DB.
        self.telemetry.record_trade_audit(event)

        # Phase 4 : bascule du suivi vers le Golden Hour Tracker.
        tracker = GoldenHourTracker(
            symbol=filing.symbol,
            entry_price=quote.ask_price,
            trade_audit_id=None,
            alpaca_config=settings.alpaca,
            risk_config=settings.risk,
            router=self.router,
            telemetry=self.telemetry,
        )
        tracker.start()

    def run_forever(self, cik: str, symbol: str) -> None:
        self.start()
        for filing in self.sec_client.poll_new_filings(cik, symbol):
            self.handle_filing(filing)

    def shutdown(self) -> None:
        self.telemetry.stop()


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 3:
        print("Usage: python -m src.main_sniper <CIK> <SYMBOL>")
        sys.exit(1)

    sniper = Sniper()
    try:
        sniper.run_forever(cik=sys.argv[1], symbol=sys.argv[2])
    except KeyboardInterrupt:
        sniper.shutdown()
