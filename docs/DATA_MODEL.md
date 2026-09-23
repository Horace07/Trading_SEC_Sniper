# Modèle de données

Les 3 tables du projet vivent dans le schéma dédié **`sniper`** (voir
[README.md §2](../README.md#2-base-de-données-postgresql--timescaledb) pour
le pourquoi de ce choix). Les mêmes commentaires sont aussi disponibles
directement dans PostgreSQL (`sql/04_comments.sql`, visibles via `\d+
sniper.<table>` en psql, ou dans l'onglet "Properties" de chaque
table/colonne dans DBeaver).

## `sniper.assets`

Watchlist du jour : tickers sous surveillance et leur consensus EPS/Revenue,
chargés en **Phase 1 (Pre-Market)** avant l'ouverture du marché.

| Colonne | Type | Description |
|---|---|---|
| `symbol` | `TEXT` (PK) | Ticker boursier (ex: `AAPL`). |
| `cik` | `TEXT` | Central Index Key : identifiant de la société auprès de la SEC, utilisé pour interroger l'API EDGAR (`data.sec.gov`). |
| `company_name` | `TEXT` | Raison sociale de la société. |
| `consensus_eps` | `NUMERIC(12,4)` | Consensus analystes du BPA (Bénéfice Par Action, USD) attendu pour la publication du jour. |
| `consensus_revenue` | `NUMERIC(18,2)` | Consensus analystes du chiffre d'affaires attendu (USD). |
| `earnings_date` | `DATE` | Date prévue de publication des résultats. |
| `earnings_time` | `TEXT` | `BMO` (Before Market Open), `AMC` (After Market Close), ou `DMT` (During Market Trading). |
| `is_active` | `BOOLEAN` | `TRUE` si ce ticker est sous surveillance active — permet de le désactiver sans supprimer son historique. |
| `created_at` | `TIMESTAMPTZ` | Horodatage d'insertion de la ligne. |

## `sniper.trade_audits`

L'empreinte digitale de chaque **tentative** de trade sur annonce de
résultats : chronomètres de latence de bout en bout, résultats de
l'extraction Regex, microstructure de marché au moment de la décision, et
cycle de vie de l'ordre. Écrite **exclusivement** par `TelemetryWorker`
(`src/data/db_worker.py`), de façon asynchrone et fire-and-forget depuis le
Sniper — jamais sur son chemin d'exécution critique. Une ligne est créée que
le trade parte réellement ou soit annulé par un circuit breaker.

| Colonne | Type | Description |
|---|---|---|
| `id` | `BIGSERIAL` (PK) | Identifiant auto-incrémenté. |
| `symbol` | `TEXT` | Ticker concerné. |
| `filing_accession_number` | `TEXT` | Numéro d'accession SEC EDGAR du dépôt (8-K) ayant déclenché l'analyse. |
| `timestamp_sec_publish` | `TIMESTAMPTZ` | Publication du dépôt SEC détecté — point de départ du chronométrage (Phase 2). |
| `timestamp_regex_done` | `TIMESTAMPTZ` | Fin de l'extraction Regex (EPS/Revenue). |
| `timestamp_spread_checked` | `TIMESTAMPTZ` | Vérification du spread bid/ask Alpaca (Circuit Breaker Liquidité). |
| `timestamp_order_sent` | `TIMESTAMPTZ` | Envoi effectif de l'ordre à Alpaca. `NULL` si annulé avant envoi. |
| `raw_text_snippet` | `TEXT` | Extrait du texte du filing autour des valeurs extraites (±20 caractères), pour audit/debug de la Regex. |
| `regex_eps` | `NUMERIC(12,4)` | BPA extrait par la Regex (`NULL` si non trouvé). |
| `regex_revenue` | `NUMERIC(18,2)` | Chiffre d'affaires extrait par la Regex (`NULL` si non trouvé). |
| `regex_confidence` | `NUMERIC(4,3)` | Proportion des deux champs (EPS, Revenue) effectivement trouvés : `0`, `0.5` ou `1`. |
| `consensus_eps` | `NUMERIC(12,4)` | Consensus EPS de `sniper.assets` copié au moment de la décision (`core/signal.py`). |
| `consensus_revenue` | `NUMERIC(18,2)` | Consensus Revenue de `sniper.assets` copié au moment de la décision. |
| `eps_surprise_pct` | `NUMERIC(8,3)` | `(regex_eps - consensus_eps) / ABS(consensus_eps) * 100`. Positif = beat, négatif = miss. `NULL` si EPS ou consensus manquant. |
| `revenue_surprise_pct` | `NUMERIC(8,3)` | Même formule pour le revenue. Informatif uniquement, ne bloque jamais le trade. |
| `decision_reason` | `TEXT` | Raison du signal réel-vs-consensus : `eps_beat` (achat), `eps_miss_or_inline`, `missing_eps`, `no_consensus`, ou `low_regex_confidence`. |
| `alpaca_bid_price` | `NUMERIC(12,4)` | Prix bid Alpaca au moment de la vérification de liquidité. |
| `alpaca_ask_price` | `NUMERIC(12,4)` | Prix ask Alpaca au moment de la vérification de liquidité. |
| `alpaca_bid_ask_spread_at_execution` | `NUMERIC(8,5)` | Écart bid/ask en % du prix médian. Seuil du Circuit Breaker Liquidité : `MAX_SPREAD_PCT` (1.5 % par défaut). |
| `alpaca_book_volume` | `BIGINT` | Volume cumulé (`bid_size + ask_size`) du carnet. Seuil : `MIN_BOOK_VOLUME` (100 par défaut). |
| `order_id` | `TEXT` | Identifiant de l'ordre côté Alpaca. `NULL` si aucun ordre envoyé. |
| `order_side` | `TEXT` | `buy` ou `sell`. |
| `order_type` | `TEXT` | Toujours `limit` dans ce projet — jamais `market`, pour ne jamais s'exposer à un prix d'exécution non borné sur un gap. |
| `order_qty` | `NUMERIC(14,4)` | Quantité d'actions (dimensionnée par `core/risk_manager.position_size` selon `MAX_POSITION_NOTIONAL_USD`). |
| `order_limit_price` | `NUMERIC(12,4)` | Prix limite de l'ordre envoyé. |
| `order_status` | `TEXT` | `pending` (défaut), `submitted`, ou `cancelled`. |
| `circuit_breaker_triggered` | `BOOLEAN` | `TRUE` si un circuit breaker a bloqué ce trade avant l'envoi. |
| `circuit_breaker_reason` | `TEXT` | `spread_too_wide`, `book_empty`, `position_size_zero`, ou `NULL` si l'ordre est parti. |
| `created_at` | `TIMESTAMPTZ` | Insertion par `TelemetryWorker` — peut légèrement suivre `timestamp_sec_publish` du fait de l'écriture asynchrone par lots. |

## `sniper.golden_hour_ticks`

Suivi du marché minute par minute (ou seconde par seconde) pendant les
**60 minutes suivant un trade exécuté** (Phase 4, Golden Hour). Hypertable
TimescaleDB, optimisée pour l'insertion à haute fréquence et le backtesting
a posteriori de la stratégie (l'action a-t-elle continué de monter, ou
s'est-elle effondrée ?).

| Colonne | Type | Description |
|---|---|---|
| `symbol` | `TEXT` | Ticker suivi pendant la Golden Hour. |
| `"timestamp"` | `TIMESTAMPTZ` | Horodatage du tick/de la bougie. Colonne de partitionnement de l'hypertable. |
| `price` | `NUMERIC(12,4)` | Prix de clôture de la bougie. |
| `volume` | `BIGINT` | Volume échangé sur cette bougie. |
| `vwap` | `NUMERIC(12,4)` | Volume Weighted Average Price, si fourni par le flux Alpaca. |
| `trade_audit_id` | `BIGINT` (FK → `sniper.trade_audits.id`) | Le trade dont on suit l'évolution post-exécution. |

Clé primaire composite `(symbol, "timestamp")`.

## Exemple de jointure inter-schémas

Puisque `sniper.*` et `public.*` (ou tout autre schéma d'un autre projet
partageant la même base) vivent dans la même base PostgreSQL, une jointure
SQL classique fonctionne directement :

```sql
SELECT t.symbol, t.order_status, t.circuit_breaker_reason, a.company_name
FROM sniper.trade_audits t
LEFT JOIN sniper.assets a ON a.symbol = t.symbol
ORDER BY t.created_at DESC;
```
