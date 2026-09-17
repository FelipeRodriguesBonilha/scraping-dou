from __future__ import annotations

from urllib.parse import urlencode, urljoin

import config

from .common import DEFAULT_MAX_PAGES, normalize_date
from .public_pdf import save_matching_pdf

STATE = "MS"
BASE_URL = "https://www.diariooficial.ms.gov.br"
PAGE_SIZE = 500
NO_RESULTS = "Nenhum resultado encontrado."


def _editions(request, keyword: str, day: str) -> dict[str, str] | None:
    editions: dict[str, str] = {}
    seen: set[tuple[str, int]] = set()
    processed = 0
    for index in range(1, DEFAULT_MAX_PAGES + 1):
        params = urlencode({
            "tipo": 1,
            "texto": keyword,
            "dataInicial": day,
            "dataFinal": day,
            "pagina": index,
            "registrosPorPagina": PAGE_SIZE,
        })
        response = request.get(
            f"{BASE_URL}/api/diarios/busca-diarios?{params}", timeout=60_000
        )
        if response.status == 400:
            try:
                message = response.json()
            except Exception as error:
                raise RuntimeError("resposta de erro da busca de MS inválida") from error
            if message == NO_RESULTS and index == 1:
                return None
        if not response.ok:
            raise RuntimeError(f"busca indisponível (HTTP {response.status})")

        result = response.json()
        if not isinstance(result, dict) or not all(
            key in result
            for key in (
                "paginasDiario", "paginaAtual", "totalDePaginas", "totalDeRegistros"
            )
        ):
            raise RuntimeError("resposta de busca inválida")
        hits = result["paginasDiario"]
        if not isinstance(hits, list):
            raise RuntimeError("lista de resultados da busca de MS inválida")
        total = int(result["totalDeRegistros"])
        current_page = int(result["paginaAtual"])
        total_pages = int(result["totalDePaginas"])
        expected_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
        if current_page != index:
            raise RuntimeError("o portal repetiu ou pulou uma página de resultados")
        if total < 0 or total_pages < 0:
            raise RuntimeError("o portal informou totais de paginação inválidos")
        if total and total_pages != expected_pages:
            raise RuntimeError("o portal informou uma quantidade de páginas inconsistente")
        if not total and total_pages not in (0, 1):
            raise RuntimeError("o portal informou paginação para uma busca sem resultados")
        if processed + len(hits) > total:
            raise RuntimeError("o portal retornou resultados além do total informado")
        if not hits and processed < total:
            raise RuntimeError("paginação interrompida antes de todos os resultados")

        for hit in hits:
            if not isinstance(hit, dict):
                raise RuntimeError("o portal retornou uma página de edição inválida")
            if normalize_date(str(hit.get("dataPublicacao", ""))[:10]) != day:
                raise RuntimeError("o portal retornou uma edição fora da data solicitada")
            path = hit.get("caminhoArquivo")
            filename = hit.get("nomeArquivo")
            if not path or not filename:
                raise RuntimeError("resultado sem link do diário completo")
            url = urljoin(BASE_URL, path)
            page_number = int(hit["pagina"])
            if page_number < 1:
                raise RuntimeError("o portal retornou número de página inválido")
            key = (url, page_number)
            if key in seen:
                raise RuntimeError("o portal repetiu resultados durante a paginação")
            seen.add(key)
            if url in editions and editions[url] != filename:
                raise RuntimeError("o portal informou nomes diferentes para a mesma edição")
            editions[url] = filename

        processed += len(hits)
        if processed >= total:
            if total and index != total_pages:
                raise RuntimeError("a busca terminou antes da última página informada")
            break
        if index >= total_pages:
            raise RuntimeError("a busca não retornou todos os resultados informados")
    else:
        raise RuntimeError("a busca excedeu o limite de páginas de resultados")
    return editions


def _scan(request, keywords: list[str], day: str) -> None:
    # The indexed text search can omit newly published pages. An empty term
    # lists every page of the day's editions, including supplements.
    editions = _editions(request, "", day) or {}
    print(f"[{STATE}] {len(editions)} edição(ões) completa(s) encontrada(s) na data")
    saved = 0
    for url, filename in editions.items():
        response = request.get(url, timeout=120_000)
        if not response.ok:
            raise RuntimeError(f"diário indisponível (HTTP {response.status})")
        saved += len(save_matching_pdf(response.body(), STATE, keywords, filename, day))
    print(f"[{STATE}] {saved} arquivo(s) com ocorrência exata em {day}")


def search(page, keyword: str, date_value: str) -> None:
    _scan(page.context.request, [keyword], normalize_date(date_value))


def scrape(playwright=None, *, keywords=None, date_value=None, headless=True) -> None:
    if playwright is None:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as browser_tool:
            scrape(browser_tool, keywords=keywords, date_value=date_value, headless=headless)
        return
    selected = list(dict.fromkeys(
        keyword.strip()
        for keyword in (config.KEYWORDS if keywords is None else keywords)
        if keyword and keyword.strip()
    ))
    if not selected:
        print(f"[{STATE}] nenhuma palavra-chave informada")
        return
    day = normalize_date(date_value)
    for keyword in selected:
        print(f"[{STATE}] pesquisando: {keyword}")
    request = playwright.request.new_context()
    try:
        _scan(request, selected, day)
    finally:
        request.dispose()


if __name__ == "__main__":
    scrape()
