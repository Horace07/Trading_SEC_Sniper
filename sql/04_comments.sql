-- Documentation du modèle de données, directement dans PostgreSQL : ces
-- commentaires sont visibles via `\d+ sniper.<table>` en psql, ou dans
-- l'onglet "Properties" / au survol de chaque table et colonne dans DBeaver.
--
-- Idempotent : peut être rejoué sans danger à tout moment (ex: après avoir
-- déjà exécuté 01/02/03 sur une base existante), COMMENT ON écrase
-- simplement le commentaire précédent.

-- ============================================================================
-- sniper.assets
-- ============================================================================
COMMENT ON TABLE sniper.assets IS
    'Watchlist du jour : tickers sous surveillance et leur consensus EPS/Revenue, '
    'chargés en Phase 1 (Pre-Market) avant l''ouverture du marché.';

COMMENT ON COLUMN sniper.assets.symbol IS
    'Ticker boursier (ex: AAPL). Clé primaire.';
COMMENT ON COLUMN sniper.assets.cik IS
    'Central Index Key : identifiant de la société auprès de la SEC, utilisé '
    'pour interroger l''API EDGAR (data.sec.gov).';
COMMENT ON COLUMN sniper.assets.company_name IS
    'Raison sociale de la société.';
COMMENT ON COLUMN sniper.assets.consensus_eps IS
    'Consensus analystes du BPA (Bénéfice Par Action, en USD) attendu pour '
    'la publication de résultats du jour.';
COMMENT ON COLUMN sniper.assets.consensus_revenue IS
    'Consensus analystes du chiffre d''affaires attendu (en USD).';
COMMENT ON COLUMN sniper.assets.earnings_date IS
    'Date prévue de publication des résultats (earnings).';
COMMENT ON COLUMN sniper.assets.earnings_time IS
    'Moment de la publication : BMO (Before Market Open), AMC (After Market '
    'Close), ou DMT (During Market Trading).';
COMMENT ON COLUMN sniper.assets.is_active IS
    'TRUE si ce ticker est actuellement sous surveillance active. Permet de '
    'désactiver un ticker sans supprimer son historique.';
COMMENT ON COLUMN sniper.assets.created_at IS
    'Horodatage d''insertion de la ligne (chargement Pre-Market).';

-- ============================================================================
-- sniper.trade_audits
-- ============================================================================
COMMENT ON TABLE sniper.trade_audits IS
    'Empreinte digitale de chaque tentative de trade sur annonce de résultats : '
    'chronomètres de latence de bout en bout, résultats de l''extraction Regex, '
    'microstructure de marché au moment de la décision, et cycle de vie de '
    'l''ordre. Écrite exclusivement par TelemetryWorker (src/data/db_worker.py), '
    'de façon asynchrone et fire-and-forget depuis le Sniper — jamais sur son '
    'chemin d''exécution critique.';

COMMENT ON COLUMN sniper.trade_audits.id IS
    'Identifiant auto-incrémenté de la ligne d''audit.';
COMMENT ON COLUMN sniper.trade_audits.symbol IS
    'Ticker concerné par cette tentative de trade.';
COMMENT ON COLUMN sniper.trade_audits.filing_accession_number IS
    'Numéro d''accession SEC EDGAR du dépôt (8-K) ayant déclenché l''analyse.';
COMMENT ON COLUMN sniper.trade_audits.timestamp_sec_publish IS
    'Horodatage de publication du dépôt SEC détecté — point de départ du '
    'chronométrage de latence (Phase 2).';
COMMENT ON COLUMN sniper.trade_audits.timestamp_regex_done IS
    'Horodatage de fin de l''extraction Regex (EPS/Revenue) du texte du filing.';
COMMENT ON COLUMN sniper.trade_audits.timestamp_spread_checked IS
    'Horodatage de la vérification du spread bid/ask auprès d''Alpaca '
    '(Circuit Breaker Liquidité).';
COMMENT ON COLUMN sniper.trade_audits.timestamp_order_sent IS
    'Horodatage d''envoi effectif de l''ordre à Alpaca. NULL si le trade a été '
    'annulé par un circuit breaker avant l''envoi.';
COMMENT ON COLUMN sniper.trade_audits.raw_text_snippet IS
    'Extrait du texte brut du filing autour des valeurs extraites (contexte '
    '±20 caractères), pour audit et débogage de la Regex.';
COMMENT ON COLUMN sniper.trade_audits.regex_eps IS
    'BPA extrait par la Regex depuis le texte du filing (NULL si non trouvé).';
COMMENT ON COLUMN sniper.trade_audits.regex_revenue IS
    'Chiffre d''affaires extrait par la Regex depuis le texte du filing '
    '(NULL si non trouvé).';
COMMENT ON COLUMN sniper.trade_audits.regex_confidence IS
    'Score de confiance de l''extraction : proportion des deux champs '
    '(EPS, Revenue) effectivement trouvés — 0, 0.5 ou 1.';
COMMENT ON COLUMN sniper.trade_audits.alpaca_bid_price IS
    'Prix bid (meilleur prix d''achat) Alpaca au moment de la vérification '
    'de liquidité.';
COMMENT ON COLUMN sniper.trade_audits.alpaca_ask_price IS
    'Prix ask (meilleur prix de vente) Alpaca au moment de la vérification '
    'de liquidité.';
COMMENT ON COLUMN sniper.trade_audits.alpaca_bid_ask_spread_at_execution IS
    'Écart bid/ask en pourcentage du prix médian, calculé au moment de la '
    'décision. Seuil du Circuit Breaker Liquidité : MAX_SPREAD_PCT (1.5 % '
    'par défaut).';
COMMENT ON COLUMN sniper.trade_audits.alpaca_book_volume IS
    'Volume cumulé (bid_size + ask_size) du carnet d''ordres Alpaca au '
    'moment de la décision. Seuil du Circuit Breaker Liquidité : '
    'MIN_BOOK_VOLUME (100 par défaut).';
COMMENT ON COLUMN sniper.trade_audits.order_id IS
    'Identifiant de l''ordre côté Alpaca. NULL si aucun ordre n''a été envoyé.';
COMMENT ON COLUMN sniper.trade_audits.order_side IS
    'Sens de l''ordre : ''buy'' ou ''sell''.';
COMMENT ON COLUMN sniper.trade_audits.order_type IS
    'Type d''ordre. Toujours ''limit'' dans ce projet — jamais ''market'', '
    'pour ne jamais s''exposer à un prix d''exécution non borné sur un gap.';
COMMENT ON COLUMN sniper.trade_audits.order_qty IS
    'Quantité d''actions de l''ordre (dimensionnée par '
    'core/risk_manager.position_size selon MAX_POSITION_NOTIONAL_USD).';
COMMENT ON COLUMN sniper.trade_audits.order_limit_price IS
    'Prix limite de l''ordre envoyé.';
COMMENT ON COLUMN sniper.trade_audits.order_status IS
    'Statut du trade : ''pending'' (défaut), ''submitted'' (ordre envoyé), '
    'ou ''cancelled'' (bloqué par un circuit breaker ou taille de position nulle).';
COMMENT ON COLUMN sniper.trade_audits.circuit_breaker_triggered IS
    'TRUE si un circuit breaker a bloqué ce trade avant l''envoi de l''ordre.';
COMMENT ON COLUMN sniper.trade_audits.circuit_breaker_reason IS
    'Raison du blocage si circuit_breaker_triggered=TRUE : ''spread_too_wide'', '
    '''book_empty'', ou ''position_size_zero''. NULL si l''ordre est parti.';
COMMENT ON COLUMN sniper.trade_audits.created_at IS
    'Horodatage d''insertion de la ligne par TelemetryWorker — peut être '
    'légèrement postérieur à timestamp_sec_publish du fait de l''écriture '
    'asynchrone par lots (fire-and-forget).';

-- ============================================================================
-- sniper.golden_hour_ticks
-- ============================================================================
COMMENT ON TABLE sniper.golden_hour_ticks IS
    'Suivi du marché minute par minute (ou seconde par seconde) pendant les '
    '60 minutes suivant un trade exécuté (Phase 4, Golden Hour). Hypertable '
    'TimescaleDB, optimisée pour l''insertion à haute fréquence et le '
    'backtesting a posteriori de la stratégie.';

COMMENT ON COLUMN sniper.golden_hour_ticks.symbol IS
    'Ticker suivi pendant la Golden Hour.';
COMMENT ON COLUMN sniper.golden_hour_ticks."timestamp" IS
    'Horodatage du tick / de la bougie. Colonne de partitionnement de '
    'l''hypertable TimescaleDB.';
COMMENT ON COLUMN sniper.golden_hour_ticks.price IS
    'Prix de clôture de la bougie à cet horodatage.';
COMMENT ON COLUMN sniper.golden_hour_ticks.volume IS
    'Volume échangé sur cette bougie.';
COMMENT ON COLUMN sniper.golden_hour_ticks.vwap IS
    'Volume Weighted Average Price de la bougie, si fourni par le flux Alpaca.';
COMMENT ON COLUMN sniper.golden_hour_ticks.trade_audit_id IS
    'Référence vers sniper.trade_audits(id) : le trade dont on suit '
    'l''évolution du marché post-exécution.';
