-- Données de référence : tickers sous surveillance et leur consensus EPS/Revenue
-- chargé en Phase 1 (Pre-Market).

CREATE TABLE IF NOT EXISTS assets (
    symbol             TEXT PRIMARY KEY,
    cik                TEXT NOT NULL,
    company_name       TEXT NOT NULL,
    consensus_eps      NUMERIC(12, 4),
    consensus_revenue  NUMERIC(18, 2),
    earnings_date      DATE NOT NULL,
    earnings_time      TEXT CHECK (earnings_time IN ('BMO', 'AMC', 'DMT')),
    is_active          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_assets_earnings_date ON assets (earnings_date);
CREATE INDEX IF NOT EXISTS idx_assets_active ON assets (is_active) WHERE is_active;
