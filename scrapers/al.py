from __future__ import annotations

import re
from datetime import date
from typing import Iterable
from urllib.parse import unquote
from urllib.request import Request, urlopen

import config
from scrapers.common import normalize_date
from scrapers.public_api import get_bytes, get_json
from scrapers.public_pdf import save_matching_pdf


STATE = "AL"
PLAYWRIGHT_REQUIRED = False
API_URL = "https://diario.imprensaoficial.al.gov.br/apinova/api/editions"


def _editions_for_date(date_value: str) -> list[dict]:
    selected = date.fromisoformat(date_value)
    editions: list[dict] = []

    for page_number in range(1, 10_001):
        response = get_json(f"{API_URL}/published?page={page_number}")
        if response.get("status") != "success" or not isinstance(
            response.get("editions"), list
        ):
            raise RuntimeError("o catálogo de edições de AL retornou dados inválidos")

        page_editions = response["editions"]
        if not page_editions:
            break

        reached_older_date = False
        for edition in page_editions:
            publication_date = date.fromisoformat(edition["publication_date"][:10])
            if publication_date == selected:
                editions.append(edition)
            elif publication_date < selected:
                reached_older_date = True
        if reached_older_date:
            break
    else:
        raise RuntimeError("o catálogo de edições de AL excedeu o limite de páginas")

    return editions


def _remote_filename(url: str, edition_id: int) -> str:
    try:
        request = Request(url, headers={"User-Agent": "Mozilla/5.0"}, method="HEAD")
        with urlopen(request, timeout=30) as response:
            disposition = response.headers.get("Content-Disposition", "")
        match = re.search(r'filename\s*=\s*"?([^";]+)', disposition, re.I)
        if match:
            return unquote(match.group(1).strip())
    except Exception:
        pass
    return f"DOEAL-{edition_id}.pdf"


def scrape(
    playwright=None,
    keywords: Iterable[str] | None = None,
    date_value: object | None = None,
    headless: bool = True,
) -> None:
    del playwright, headless
    selected_keywords = [
        keyword.strip()
        for keyword in (config.KEYWORDS if keywords is None else keywords)
        if keyword and keyword.strip()
    ]
    if not selected_keywords:
        return

    selected_date = normalize_date(date_value)
    editions = _editions_for_date(selected_date)
    print(f"[{STATE}] {len(editions)} edição(ões) publicada(s) em {selected_date}")

    for edition in editions:
        edition_id = edition["id"]
        url = f"{API_URL}/downloadPdf/{edition_id}"
        content = get_bytes(url)
        filename = _remote_filename(url, edition_id)
        saved = save_matching_pdf(
            content, STATE, selected_keywords, filename, selected_date
        )
        for path in saved:
            print(f"[{STATE}] salvo: {path}")


if __name__ == "__main__":
    scrape()
