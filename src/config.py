"""Chargement centralisé de la configuration depuis les variables d'environnement.

Toute lecture de `.env` passe par ce module : aucun autre fichier du projet
ne doit appeler `os.getenv` directement. Les champs sensibles (clés API) sont
laissés vides par défaut plutôt que déclarés `required` à l'import, pour ne
pas faire échouer les tests ou les imports qui n'en ont pas besoin — c'est
`AlpacaRouter` / `SECClient` qui lèvent une erreur explicite s'ils sont
instanciés sans les identifiants nécessaires.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=_ENV_PATH, override=False)


def _get(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def _get_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw else default


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw else default


@dataclass(frozen=True)
class AlpacaConfig:
    api_key: str = field(default_factory=lambda: _get("ALPACA_API_KEY"))
    api_secret: str = field(default_factory=lambda: _get("ALPACA_API_SECRET"))
    base_url: str = field(default_factory=lambda: _get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets"))
    data_feed: str = field(default_factory=lambda: _get("ALPACA_DATA_FEED", "iex"))

    def require_credentials(self) -> None:
        if not self.api_key or not self.api_secret:
            raise RuntimeError("ALPACA_API_KEY / ALPACA_API_SECRET are not set (see .env.example)")


@dataclass(frozen=True)
class DatabaseConfig:
    host: str = field(default_factory=lambda: _get("POSTGRES_HOST", "localhost"))
    port: int = field(default_factory=lambda: _get_int("POSTGRES_PORT", 5432))
    user: str = field(default_factory=lambda: _get("POSTGRES_USER", "sniper"))
    password: str = field(default_factory=lambda: _get("POSTGRES_PASSWORD", "sniper"))
    dbname: str = field(default_factory=lambda: _get("POSTGRES_DB", "trading_sec_sniper"))

    @property
    def dsn(self) -> str:
        return (
            f"host={self.host} port={self.port} dbname={self.dbname} "
            f"user={self.user} password={self.password}"
        )


@dataclass(frozen=True)
class SECConfig:
    # La SEC exige un User-Agent nominatif (nom + contact), sous peine de
    # rate-limit / blocage (https://www.sec.gov/os/webmaster-faq#developers).
    user_agent: str = field(default_factory=lambda: _get("SEC_USER_AGENT"))
    polling_interval_seconds: float = field(default_factory=lambda: _get_float("SEC_POLL_INTERVAL_SECONDS", 0.5))

    def require_user_agent(self) -> None:
        if not self.user_agent:
            raise RuntimeError("SEC_USER_AGENT is not set (see .env.example)")


@dataclass(frozen=True)
class RiskConfig:
    max_spread_pct: float = field(default_factory=lambda: _get_float("MAX_SPREAD_PCT", 1.5))
    min_book_volume: int = field(default_factory=lambda: _get_int("MIN_BOOK_VOLUME", 100))
    max_position_notional_usd: float = field(default_factory=lambda: _get_float("MAX_POSITION_NOTIONAL_USD", 5000))
    stop_loss_pct: float = field(default_factory=lambda: _get_float("STOP_LOSS_PCT", 3.0))
    take_profit_pct: float = field(default_factory=lambda: _get_float("TAKE_PROFIT_PCT", 5.0))
    trailing_stop_pct: float = field(default_factory=lambda: _get_float("TRAILING_STOP_PCT", 2.0))
    golden_hour_minutes: int = field(default_factory=lambda: _get_int("GOLDEN_HOUR_MINUTES", 60))
    min_eps_surprise_pct: float = field(default_factory=lambda: _get_float("MIN_EPS_SURPRISE_PCT", 0.0))
    min_regex_confidence: float = field(default_factory=lambda: _get_float("MIN_REGEX_CONFIDENCE", 0.5))


@dataclass(frozen=True)
class Settings:
    alpaca: AlpacaConfig = field(default_factory=AlpacaConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    sec: SECConfig = field(default_factory=SECConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)


settings = Settings()
