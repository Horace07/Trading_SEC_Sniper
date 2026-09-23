# Trading SEC Sniper

Système de trading automatisé sur annonces de résultats (Earnings) : détection
du dépôt SEC (8-K), extraction de l'EPS/Revenue par Regex, vérification de la
liquidité via Alpaca, exécution de l'ordre, et enregistrement exhaustif
(millisecondes du processus + évolution du marché sur 60 minutes) — sans
jamais ralentir la décision ni l'exécution.

## 1. Architecture : 3 moteurs découplés

Le problème central est la **latence** : écrire dans PostgreSQL pendant la
prise de décision coûterait des millisecondes critiques. La solution est une
architecture asynchrone où l'enregistrement ne touche jamais le chemin chaud.

```
┌──────────────────┐   Queue.put()   ┌──────────────────────┐   INSERT    ┌────────────┐
│   1. Le Sniper    │ ───(<0.1 ms)──▶ │  2. Le Message Broker │ ──(async)─▶ │ PostgreSQL │
│  (moteur hot-path)│                 │   (file en RAM)       │             │ /Timescale │
└──────────────────┘                 └──────────────────────┘             └────────────┘
                                                                                  ▲
                                                                                  │
                                                                    ┌──────────────────────┐
                                                                    │ 3. Worker Télémétrie  │
                                                                    │   (thread secondaire) │
                                                                    └──────────────────────┘
```

1. **L'Engine Principal (`src/main_sniper.py`, `src/core/`, `src/execution/`)**
   — écoute la SEC, lance la Regex, vérifie le carnet d'ordres Alpaca, envoie
   l'ordre. Thread prioritaire, aucune I/O base de données.
2. **Le Message Broker** — une `queue.Queue` Python interne (`src/data/db_worker.py`).
   `queue.put()` est un simple append en mémoire : le Sniper ne bloque jamais
   sur le réseau ou sur Postgres.
3. **Le Worker de Télémétrie (`TelemetryWorker`)** — thread secondaire qui
   draine la file en arrière-plan et insère les événements dans PostgreSQL,
   sans jamais impacter le chemin d'exécution.

Cette séparation stricte Sniper / Télémétrie est également une séparation de
sécurité : un bug ou un ralentissement de l'écriture DB ne peut jamais
retarder ou bloquer l'envoi d'un ordre.

## 2. Base de données (PostgreSQL + TimescaleDB)

Trois tables, toutes dans un schéma dédié **`sniper`** (voir `sql/`) — pas
`public` : ça permet de faire cohabiter ce projet avec d'autres bases de
travail existantes sur la même instance PostgreSQL (jointures SQL directes,
ex: `sniper.trade_audits JOIN public.assets`), sans collision de noms de
table avec un autre projet.

| Table | Rôle |
|---|---|
| `sniper.assets` | Watchlist du jour + consensus EPS/Revenue chargé en pre-market |
| `sniper.trade_audits` | Empreinte digitale du trade : chronomètres (SEC publish → regex → spread → ordre), résultats Regex, spread bid/ask à l'exécution, statut de l'ordre |
| `sniper.golden_hour_ticks` | Hypertable TimescaleDB : prix/volume/VWAP seconde par seconde pendant les 60 minutes suivant le tir, pour backtester la stratégie |

## 3. Déroulé fonctionnel (les 4 phases)

**Phase 1 — Pre-Market (`Sniper.start`)**
Chargement du consensus EPS depuis la DB, ouverture de connexions
persistantes (Keep-Alive) vers Alpaca pour éliminer le coût de handshake TCP/TLS
au moment critique.

**Phase 2 — L'Événement (`Sniper.handle_filing`)**
Détection du 8-K (`SECClient.poll_new_filings`), téléchargement du texte,
extraction Regex (`core/nlp_regex.py`), interrogation du spread Alpaca.
**Circuit Breaker Liquidité** (`core/risk_manager.check_liquidity`) : si le
spread bid/ask dépasse `MAX_SPREAD_PCT` (1.5 % par défaut) ou si le carnet est
vide, le trade est annulé.

**Phase 3 — Exécution & Fire-and-Forget**
Un ordre `LIMIT` (jamais `MARKET`) part chez Alpaca. Le Sniper construit un
`TradeAuditEvent` (JSON) avec tous les chronomètres et résultats Regex, et le
pousse dans la file d'attente — fire-and-forget, retour immédiat.

**Phase 4 — Golden Hour (`execution/golden_hour.py`)**
Un tracker dédié collecte le VWAP/les bougies via WebSocket Alpaca pendant
`GOLDEN_HOUR_MINUTES` (60 par défaut) et pousse chaque tick dans la même file
asynchrone. **Circuit Breaker Risque** : Stop-Loss, Take-Profit et Trailing
Stop dynamiques ferment la position si la volatilité se retourne.

## 4. Structure du repository

```
Trading_SEC_Sniper/
├── .env.example            # Modèle de configuration (copier en .env)
├── docker-compose.yml      # PostgreSQL + TimescaleDB
├── requirements.txt
├── sql/
│   ├── 01_init_assets.sql
│   ├── 02_create_audits.sql
│   └── 03_golden_hour.sql
├── src/
│   ├── config.py            # Chargement centralisé du .env
│   ├── core/
│   │   ├── nlp_regex.py     # Extraction EPS/Revenue
│   │   └── risk_manager.py  # Circuit breakers liquidité + risque
│   ├── data/
│   │   ├── sec_client.py    # Client SEC EDGAR
│   │   └── db_worker.py     # Worker télémétrie asynchrone
│   ├── execution/
│   │   ├── alpaca_router.py # Routage des ordres + spread
│   │   └── golden_hour.py   # Tracker WebSocket post-trade
│   └── main_sniper.py       # Orchestrateur
└── tests/
    ├── test_regex_parser.py
    └── test_circuit_breaker.py
```

## 5. Mise en route

### Option A — Tout-Docker (recommandé, "plug and play")

Aucune installation Python locale requise : l'application tourne dans un
conteneur Linux, aux côtés de PostgreSQL/TimescaleDB. Utile en particulier
sous Windows, où des outils comme *Smart App Control* bloquent parfois les
bibliothèques compilées (`pandas`, `numpy`) installées via `pip` en dehors
d'un conteneur.

```bash
cp .env.example .env               # renseigner les clés Alpaca + SEC_USER_AGENT (optionnel pour les tests)
docker compose up -d --build       # démarre PostgreSQL/TimescaleDB + construit l'image app
docker compose run --rm app pytest -v          # tests unitaires
docker compose run --rm app python -m src.main_sniper <CIK> <SYMBOL>
```

`docker compose run --rm app <commande>` exécute n'importe quelle commande
Python dans le même environnement (dépendances déjà installées, réseau
partagé avec `postgres`) sans laisser de conteneur derrière. Le dossier du
projet est monté dans le conteneur : toute modification du code est prise en
compte immédiatement, sans reconstruire l'image.

### Option B — Python local (venv)

```bash
cp .env.example .env               # renseigner les clés Alpaca + SEC_USER_AGENT
docker compose up -d               # démarre uniquement PostgreSQL/TimescaleDB + applique sql/
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

pytest                             # tests unitaires (regex + circuit breakers)

python -m src.main_sniper <CIK> <SYMBOL>
```

`SEC_USER_AGENT` doit contenir un contact réel (ex : `"MaFirme contact@mafirme.com"`) :
la SEC bloque les User-Agent génériques (voir la
[FAQ développeurs SEC EDGAR](https://www.sec.gov/os/webmaster-faq#developers)).

### Option C — Centraliser sur une instance PostgreSQL existante

Si une instance PostgreSQL tourne déjà localement pour un autre projet, on
peut la réutiliser au lieu de faire tourner une seconde instance Postgres
dédiée à ce projet — c'était d'ailleurs la contrainte d'infrastructure
d'origine du cahier des charges. Grâce au schéma dédié `sniper` (voir
section 2), **pas besoin de créer une base séparée** : on peut directement
réutiliser la base d'un autre projet, nos tables vivront dans leur propre
schéma isolé, à côté de son schéma `public`.

Connecté à la base existante (celle de l'autre projet), exécute le contenu de
`sql/01_init_assets.sql`, `sql/02_create_audits.sql` et `sql/03_golden_hour.sql`
dans l'ordre (l'auto-exécution Docker via `docker-entrypoint-initdb.d` ne
s'applique qu'à un volume Postgres fraîchement créé, pas à une instance
existante) — ils créent le schéma `sniper` s'il n'existe pas encore, puis nos
3 tables dedans.

Ajuste `.env` pour pointer vers cette instance :
```env
POSTGRES_PORT=<port publié par l'instance existante>
POSTGRES_DB=<nom de la base existante de l'autre projet>
```

Puis utilise `docker-compose.external-db.yml` (voir les commentaires du
fichier) pour rediriger le service `app` vers cette instance externe au lieu
du service `postgres` local :

```bash
docker compose -f docker-compose.yml -f docker-compose.external-db.yml \
  run --rm --no-deps app pytest -v
```

`--no-deps` est indispensable : sans lui, Compose démarrerait quand même le
service `postgres` local, faisant tourner deux instances Postgres pour rien.

## 6. Tests

- `tests/test_regex_parser.py` — faux textes SEC pour vérifier que la Regex
  extrait correctement EPS/Revenue, y compris les cas négatifs (parenthèses)
  et les valeurs manquantes, sans jamais lever d'exception.
- `tests/test_circuit_breaker.py` — simulation de spreads énormes et de
  carnets vides pour vérifier que le trade est bien annulé.
