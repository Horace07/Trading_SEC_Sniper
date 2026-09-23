-- L'empreinte digitale du trade : chronomètres, résultats Regex, spread à
-- l'exécution et cycle de vie de l'ordre. Écrite exclusivement par le
-- TelemetryWorker (src/data/db_worker.py), jamais par le Sniper lui-même.

CREATE TABLE IF NOT EXISTS trade_audits (
    id                       BIGSERIAL PRIMARY KEY,
    symbol                   TEXT NOT NULL,
    filing_accession_number  TEXT,

    -- Chronomètres (UTC)
    timestamp_sec_publish    TIMESTAMPTZ NOT NULL,
    timestamp_regex_done     TIMESTAMPTZ,
    timestamp_spread_checked TIMESTAMPTZ,
    timestamp_order_sent     TIMESTAMPTZ,

    -- Extraction NLP / Regex
    raw_text_snippet         TEXT,
    regex_eps                NUMERIC(12, 4),
    regex_revenue            NUMERIC(18, 2),
    regex_confidence         NUMERIC(4, 3),

    -- Microstructure de marché au moment de la décision
    alpaca_bid_price                    NUMERIC(12, 4),
    alpaca_ask_price                    NUMERIC(12, 4),
    alpaca_bid_ask_spread_at_execution  NUMERIC(8, 5),
    alpaca_book_volume                  BIGINT,

    -- Cycle de vie de l'ordre
    order_id                    TEXT,
    order_side                  TEXT CHECK (order_side IN ('buy', 'sell')),
    order_type                  TEXT NOT NULL DEFAULT 'limit',
    order_qty                   NUMERIC(14, 4),
    order_limit_price           NUMERIC(12, 4),
    order_status                TEXT NOT NULL DEFAULT 'pending',
    circuit_breaker_triggered   BOOLEAN NOT NULL DEFAULT FALSE,
    circuit_breaker_reason      TEXT,

    created_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_trade_audits_symbol ON trade_audits (symbol);
CREATE INDEX IF NOT EXISTS idx_trade_audits_created_at ON trade_audits (created_at);
CREATE INDEX IF NOT EXISTS idx_trade_audits_order_status ON trade_audits (order_status);
