"""Faux textes SEC pour vérifier que le moteur Regex extrait correctement
EPS/Revenue et ne plante jamais, même sans chiffres trouvables."""

from decimal import Decimal

from src.core.nlp_regex import extract_financials


def test_extracts_positive_eps():
    text = "The Company reported diluted earnings per share of $2.35 for the quarter."
    result = extract_financials(text)
    assert result.eps == Decimal("2.35")


def test_extracts_negative_eps_in_parentheses():
    text = "Diluted EPS was $(0.42), compared to $0.10 in the prior year."
    result = extract_financials(text)
    assert result.eps == Decimal("-0.42")


def test_extracts_revenue_in_millions():
    text = "Total revenues of $512.3 million increased 12% year over year."
    result = extract_financials(text)
    assert result.revenue == Decimal("512.3") * Decimal("1e6")


def test_extracts_plain_revenue_with_commas():
    text = "Revenue was $1,200,000 for the period."
    result = extract_financials(text)
    assert result.revenue == Decimal("1200000")
    assert result.eps is None


def test_missing_figures_return_none_without_raising():
    text = "This press release contains forward-looking statements only."
    result = extract_financials(text)
    assert result.eps is None
    assert result.revenue is None
    assert result.confidence == 0.0


def test_confidence_reflects_partial_extraction():
    text = "Revenue was $1,200,000 for the period."
    result = extract_financials(text)
    assert result.confidence == 0.5


def test_confidence_is_full_when_both_found():
    text = "Diluted earnings per share of $1.10 on total revenues of $200 million."
    result = extract_financials(text)
    assert result.eps == Decimal("1.10")
    assert result.revenue == Decimal("200") * Decimal("1e6")
    assert result.confidence == 1.0


def test_malformed_input_never_raises():
    # Chaîne vide, binaire tronqué, texte sans structure : ne doit jamais lever.
    for garbage in ["", "   ", "\x00\x01$$$", "EPS EPS EPS $"]:
        result = extract_financials(garbage)
        assert result.confidence in (0.0, 0.5, 1.0)
