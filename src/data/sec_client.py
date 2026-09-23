"""Client SEC EDGAR : détection des dépôts 8-K et récupération de leur texte.

La SEC exige un User-Agent nominatif (nom + contact) sur `data.sec.gov` et
`www.sec.gov`, sous peine de rate-limit voire de blocage définitif de l'IP :
https://www.sec.gov/os/webmaster-faq#developers
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Iterator, Optional

import requests

from src.config import SECConfig

_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:0>10}.json"
_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"


@dataclass(frozen=True)
class FilingEvent:
    symbol: str
    cik: str
    accession_number: str
    form_type: str
    filed_at: str
    primary_document: str

    @property
    def document_url(self) -> str:
        accession_no_dashes = self.accession_number.replace("-", "")
        return f"{_ARCHIVES_BASE}/{int(self.cik)}/{accession_no_dashes}/{self.primary_document}"


class SECClient:
    def __init__(self, config: SECConfig, session: Optional[requests.Session] = None):
        config.require_user_agent()
        self._config = config
        self._session = session or requests.Session()
        self._session.headers.update({"User-Agent": config.user_agent})
        self._seen_accessions: set[str] = set()

    def fetch_latest_filings(self, cik: str, symbol: str, form_type: str = "8-K") -> list[FilingEvent]:
        response = self._session.get(_SUBMISSIONS_URL.format(cik=int(cik)), timeout=5)
        response.raise_for_status()
        recent = response.json().get("filings", {}).get("recent", {})

        events: list[FilingEvent] = []
        for form, accession, filed_at, primary_doc in zip(
            recent.get("form", []),
            recent.get("accessionNumber", []),
            recent.get("filingDate", []),
            recent.get("primaryDocument", []),
        ):
            if form != form_type:
                continue
            events.append(
                FilingEvent(
                    symbol=symbol,
                    cik=cik,
                    accession_number=accession,
                    form_type=form,
                    filed_at=filed_at,
                    primary_document=primary_doc,
                )
            )
        return events

    def poll_new_filings(self, cik: str, symbol: str, form_type: str = "8-K") -> Iterator[FilingEvent]:
        """Générateur bloquant : émet chaque nouveau dépôt dès qu'il apparaît."""
        while True:
            for event in self.fetch_latest_filings(cik, symbol, form_type):
                if event.accession_number not in self._seen_accessions:
                    self._seen_accessions.add(event.accession_number)
                    yield event
            time.sleep(self._config.polling_interval_seconds)

    def download_document_text(self, filing: FilingEvent) -> str:
        response = self._session.get(filing.document_url, timeout=5)
        response.raise_for_status()
        return _strip_html(response.text)


def _strip_html(html: str) -> str:
    from bs4 import BeautifulSoup

    return BeautifulSoup(html, "lxml").get_text(separator=" ", strip=True)
