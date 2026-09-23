"""Chargement du consensus EPS/Revenue depuis `sniper.assets`.

Appelé une seule fois en Phase 1 (Pre-Market), jamais sur le chemin chaud du
Sniper : `psycopg2` n'est donc importé ici que pour ce chargement initial,
pas pour `main_sniper.py` lui-même.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

import psycopg2

from src.config import DatabaseConfig

_SELECT_ACTIVE_WATCHLIST_SQL = """
SELECT symbol, consensus_eps, consensus_revenue
FROM sniper.assets
WHERE is_active = TRUE
"""


@dataclass(frozen=True)
class AssetConsensus:
    symbol: str
    consensus_eps: Optional[Decimal]
    consensus_revenue: Optional[Decimal]


def load_watchlist_consensus(db_config: DatabaseConfig) -> dict[str, AssetConsensus]:
    """Retourne le consensus EPS/Revenue de chaque ticker actif de la watchlist."""
    conn = psycopg2.connect(db_config.dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(_SELECT_ACTIVE_WATCHLIST_SQL)
            rows = cur.fetchall()
    finally:
        conn.close()

    return {
        symbol: AssetConsensus(symbol=symbol, consensus_eps=consensus_eps, consensus_revenue=consensus_revenue)
        for symbol, consensus_eps, consensus_revenue in rows
    }
