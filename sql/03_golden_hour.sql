-- Suivi du marché post-annonce : prix/volume/VWAP seconde par seconde pendant
-- les 60 minutes suivant le tir (Phase 4), pour backtester si l'action a
-- continué de monter ou s'est effondrée. Hypertable TimescaleDB pour
-- l'insertion à haute fréquence.

CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE SCHEMA IF NOT EXISTS sniper;

CREATE TABLE IF NOT EXISTS sniper.golden_hour_ticks (
    symbol         TEXT NOT NULL,
    "timestamp"    TIMESTAMPTZ NOT NULL,
    price          NUMERIC(12, 4) NOT NULL,
    volume         BIGINT NOT NULL DEFAULT 0,
    vwap           NUMERIC(12, 4),
    trade_audit_id BIGINT REFERENCES sniper.trade_audits (id),
    PRIMARY KEY (symbol, "timestamp")
);

SELECT create_hypertable('sniper.golden_hour_ticks', 'timestamp', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_golden_hour_symbol_time ON sniper.golden_hour_ticks (symbol, "timestamp" DESC);
