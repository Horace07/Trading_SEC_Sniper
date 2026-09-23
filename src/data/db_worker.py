"""Le Worker de Télémétrie ("l'Archiviste") : draine en arrière-plan la file
d'attente en RAM alimentée par le Sniper, et l'insère dans PostgreSQL.

C'est la pièce centrale de l'architecture anti-latence : `record_trade_audit`
/ `record_tick` sont de simples `Queue.put()` (< 0.1 ms, aucune I/O réseau),
appelés directement depuis le chemin chaud du Sniper. L'écriture PostgreSQL
elle-même n'a jamais lieu sur ce thread : elle est faite par `TelemetryWorker`
sur son propre thread, par lots, de façon totalement découplée.
"""

from __future__ import annotations

import logging
import queue
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

import psycopg2

from src.config import DatabaseConfig

logger = logging.getLogger(__name__)


@dataclass
class TradeAuditEvent:
    """Le "Trade Event" JSON que le Sniper construit et jette dans la file.

    Chaque champ est capturé de façon synchrone par le thread Sniper ; seule
    l'écriture en base est différée.
    """

    symbol: str
    timestamp_sec_publish: datetime
    filing_accession_number: Optional[str] = None
    timestamp_regex_done: Optional[datetime] = None
    timestamp_spread_checked: Optional[datetime] = None
    timestamp_order_sent: Optional[datetime] = None
    raw_text_snippet: Optional[str] = None
    regex_eps: Optional[Decimal] = None
    regex_revenue: Optional[Decimal] = None
    regex_confidence: Optional[float] = None
    consensus_eps: Optional[Decimal] = None
    consensus_revenue: Optional[Decimal] = None
    eps_surprise_pct: Optional[Decimal] = None
    revenue_surprise_pct: Optional[Decimal] = None
    decision_reason: Optional[str] = None
    alpaca_bid_price: Optional[Decimal] = None
    alpaca_ask_price: Optional[Decimal] = None
    alpaca_bid_ask_spread_at_execution: Optional[Decimal] = None
    alpaca_book_volume: Optional[int] = None
    order_id: Optional[str] = None
    order_side: Optional[str] = None
    order_type: str = "limit"
    order_qty: Optional[Decimal] = None
    order_limit_price: Optional[Decimal] = None
    order_status: str = "pending"
    circuit_breaker_triggered: bool = False
    circuit_breaker_reason: Optional[str] = None


@dataclass
class GoldenHourTick:
    symbol: str
    timestamp: datetime
    price: Decimal
    volume: int
    vwap: Optional[Decimal] = None
    trade_audit_id: Optional[int] = None


_INSERT_AUDIT_SQL = """
INSERT INTO sniper.trade_audits (
    symbol, filing_accession_number,
    timestamp_sec_publish, timestamp_regex_done, timestamp_spread_checked, timestamp_order_sent,
    raw_text_snippet, regex_eps, regex_revenue, regex_confidence,
    consensus_eps, consensus_revenue, eps_surprise_pct, revenue_surprise_pct, decision_reason,
    alpaca_bid_price, alpaca_ask_price, alpaca_bid_ask_spread_at_execution, alpaca_book_volume,
    order_id, order_side, order_type, order_qty, order_limit_price, order_status,
    circuit_breaker_triggered, circuit_breaker_reason
) VALUES (
    %(symbol)s, %(filing_accession_number)s,
    %(timestamp_sec_publish)s, %(timestamp_regex_done)s, %(timestamp_spread_checked)s, %(timestamp_order_sent)s,
    %(raw_text_snippet)s, %(regex_eps)s, %(regex_revenue)s, %(regex_confidence)s,
    %(consensus_eps)s, %(consensus_revenue)s, %(eps_surprise_pct)s, %(revenue_surprise_pct)s, %(decision_reason)s,
    %(alpaca_bid_price)s, %(alpaca_ask_price)s, %(alpaca_bid_ask_spread_at_execution)s, %(alpaca_book_volume)s,
    %(order_id)s, %(order_side)s, %(order_type)s, %(order_qty)s, %(order_limit_price)s, %(order_status)s,
    %(circuit_breaker_triggered)s, %(circuit_breaker_reason)s
)
"""

_INSERT_TICK_SQL = """
INSERT INTO sniper.golden_hour_ticks (symbol, "timestamp", price, volume, vwap, trade_audit_id)
VALUES (%(symbol)s, %(timestamp)s, %(price)s, %(volume)s, %(vwap)s, %(trade_audit_id)s)
ON CONFLICT (symbol, "timestamp") DO NOTHING
"""


class TelemetryWorker:
    """Thread secondaire : seule composante du projet qui écrit dans
    `sniper.trade_audits` / `sniper.golden_hour_ticks`. Le Sniper ne détient
    aucune connexion PostgreSQL."""

    def __init__(self, db_config: DatabaseConfig, batch_size: int = 20, flush_interval: float = 0.5):
        self._db_config = db_config
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._queue: "queue.Queue[tuple[str, Any]]" = queue.Queue()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="telemetry-worker", daemon=True)
        self._thread.start()
        logger.info("Telemetry worker started")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Telemetry worker stopped")

    def record_trade_audit(self, event: TradeAuditEvent) -> None:
        """Fire-and-forget : appelé depuis le chemin chaud du Sniper."""
        self._queue.put(("trade_audit", event))

    def record_tick(self, tick: GoldenHourTick) -> None:
        self._queue.put(("golden_hour_tick", tick))

    def _run(self) -> None:
        conn = psycopg2.connect(self._db_config.dsn)
        conn.autocommit = False
        try:
            while not self._stop_event.is_set() or not self._queue.empty():
                batch = self._drain_batch()
                if batch:
                    self._flush(conn, batch)
                else:
                    self._stop_event.wait(self._flush_interval)
        finally:
            conn.close()

    def _drain_batch(self) -> list[tuple[str, Any]]:
        batch: list[tuple[str, Any]] = []
        try:
            while len(batch) < self._batch_size:
                batch.append(self._queue.get_nowait())
        except queue.Empty:
            pass
        return batch

    def _flush(self, conn: "psycopg2.extensions.connection", batch: list[tuple[str, Any]]) -> None:
        try:
            with conn.cursor() as cur:
                for kind, payload in batch:
                    if kind == "trade_audit":
                        cur.execute(_INSERT_AUDIT_SQL, asdict(payload))
                    elif kind == "golden_hour_tick":
                        cur.execute(_INSERT_TICK_SQL, asdict(payload))
            conn.commit()
        except Exception:
            conn.rollback()
            logger.exception("Failed to flush %d telemetry event(s)", len(batch))
