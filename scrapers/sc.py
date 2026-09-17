"""DOE de Santa Catarina: public ordinary and extra editions by date."""
from __future__ import annotations

from urllib.parse import urlencode

import config
from scrapers.common import normalize_date
from scrapers.public_api import get_bytes, get_json
from scrapers.public_pdf import save_matching_pdf

STATE = "SC"
PLAYWRIGHT_REQUIRED = False
API = "https://portal.doe.sea.sc.gov.br/apis/jornal/"
REPOSITORY = "https://portal.doe.sea.sc.gov.br/repositorio"


def _pdf_url(record: dict, day: str) -> str:
    path = record.get("dsArquivo")
    if path:
        return REPOSITORY + "/" + str(path).lstrip("/")
    return ("https://sigio2.doe.sea.sc.gov.br/sigio/Materias/" +
            day.replace("-", "") + f"/Jornal/{record['cdJornal']}.pdf")


def _editions(day: str):
    seen = set()
    page = 1
    processed = 0
    expected_total = None
    while True:
        payload = get_json(API + "?" + urlencode({
            "page": page, "perPage": 12,
            "dtStart": day + " 00:00:00", "dtEnd": day + " 23:59:59",
        }))
        if not isinstance(payload, dict) or payload.get("error") or not isinstance(payload.get("records"), dict):
            raise RuntimeError("resposta inesperada do catálogo de SC")
        records = payload["records"]
        rows, meta = records.get("data"), records.get("meta")
        if not isinstance(rows, list) or not isinstance(meta, dict):
            raise RuntimeError("catálogo de SC não informou a paginação")
        try:
            total = int(meta["total"])
            per_page = int(meta["per_page"])
            last_page = int(meta["last_page"])
            current_page = int(meta["current_page"])
        except (KeyError, TypeError, ValueError) as error:
            raise RuntimeError("paginação do catálogo de SC inválida") from error
        calculated_last = (total + per_page - 1) // per_page if per_page > 0 else -1
        if (
            total < 0 or per_page < 1 or current_page != page
            or last_page != max(1, calculated_last)
            or (expected_total is not None and total != expected_total)
            or processed + len(rows) > total
        ):
            raise RuntimeError("paginação do catálogo de SC inconsistente")
        expected_total = total
        for record in rows:
            if normalize_date(str(record.get("dtPublicacao", ""))[:10]) != day:
                raise RuntimeError("SC retornou edição fora da data solicitada")
            if record.get("stCancelado") or record.get("stAprovado") is False:
                continue
            identifier = record["cdJornal"]
            if identifier in seen:
                raise RuntimeError("SC repetiu uma edição no catálogo")
            seen.add(identifier)
            yield record
        processed += len(rows)
        if page >= last_page:
            if processed != total:
                raise RuntimeError("catálogo de SC terminou antes de todas as edições")
            return
        if len(rows) != per_page:
            raise RuntimeError("SC interrompeu a paginação antes do fim")
        page += 1


def scrape(playwright=None, *, keywords=None, date_value=None, headless=True) -> None:
    selected = [
        keyword
        for keyword in (config.KEYWORDS if keywords is None else keywords)
        if keyword and keyword.strip()
    ]
    if not selected:
        print(f"[{STATE}] nenhuma palavra-chave informada")
        return
    day = normalize_date(date_value)
    editions = saved = 0
    for record in _editions(day):
        editions += 1
        data = get_bytes(_pdf_url(record, day))
        pages = record.get("vlNumeropaginas")
        saved += len(save_matching_pdf(data, STATE, selected,
                     f"SC-{day}-{record['vlNumero']}.pdf", day,
                     expected_pages=int(pages) if pages else None))
    print(f"[SC] {editions} edição(ões) consultada(s); {saved} arquivo(s) com ocorrências")


if __name__ == "__main__":
    scrape()
