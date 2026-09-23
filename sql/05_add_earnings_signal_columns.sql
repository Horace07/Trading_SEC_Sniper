-- Ajoute la comparaison réel (Regex) vs consensus analystes à l'audit de
-- chaque trade : sans ça, `regex_eps`/`regex_revenue` étaient enregistrés
-- mais jamais confrontés au consensus de `sniper.assets`, et le Sniper
-- achetait sur n'importe quel 8-K (voir src/core/signal.py).

ALTER TABLE sniper.trade_audits
    ADD COLUMN IF NOT EXISTS consensus_eps        NUMERIC(12, 4),
    ADD COLUMN IF NOT EXISTS consensus_revenue     NUMERIC(18, 2),
    ADD COLUMN IF NOT EXISTS eps_surprise_pct      NUMERIC(8, 3),
    ADD COLUMN IF NOT EXISTS revenue_surprise_pct  NUMERIC(8, 3),
    ADD COLUMN IF NOT EXISTS decision_reason       TEXT;

COMMENT ON COLUMN sniper.trade_audits.consensus_eps IS
    'Consensus analystes du BPA pour ce symbole (copié depuis sniper.assets '
    'au moment de la décision), utilisé pour calculer eps_surprise_pct.';
COMMENT ON COLUMN sniper.trade_audits.consensus_revenue IS
    'Consensus analystes du chiffre d''affaires pour ce symbole (copié '
    'depuis sniper.assets au moment de la décision).';
COMMENT ON COLUMN sniper.trade_audits.eps_surprise_pct IS
    'Écart en % entre regex_eps et consensus_eps : (regex_eps - consensus_eps) '
    '/ ABS(consensus_eps) * 100. Positif = beat, négatif = miss. NULL si '
    'l''EPS ou le consensus est manquant.';
COMMENT ON COLUMN sniper.trade_audits.revenue_surprise_pct IS
    'Écart en % entre regex_revenue et consensus_revenue, même formule que '
    'eps_surprise_pct. Informatif uniquement : ne bloque pas le trade.';
COMMENT ON COLUMN sniper.trade_audits.decision_reason IS
    'Raison de la décision du signal réel-vs-consensus (src/core/signal.py) : '
    '''eps_beat'' (achat déclenché), ''eps_miss_or_inline'', ''missing_eps'', '
    '''no_consensus'', ou ''low_regex_confidence''.';
