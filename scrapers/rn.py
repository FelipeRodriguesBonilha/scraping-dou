from __future__ import annotations

from urllib.parse import urlencode

from .common import date_as_br, normalize_date, run_for_keywords, scrape_with_playwright
from .public_pdf import save_matching_pdf

STATE = "RN"
DIARY_CODE = 121
BASE_URL = "https://deirn.sdoe.com.br/diariooficial"
REPOSITORY_URL = "https://cepebr-prod.s3.sa-east-1.amazonaws.com"


def _get_json(request, url: str):
    response = request.get(url, timeout=60_000)
    if not response.ok:
        raise RuntimeError(f"portal indisponível (HTTP {response.status})")
    try:
        return response.json()
    except Exception as error:
        raise RuntimeError("resposta inválida do portal") from error


def _edition_exists(request, date_br: str, *, extra: bool) -> bool:
    endpoint = "existeDiarioExtra" if extra else "existeDiario"
    params = urlencode({"codigoDiario": DIARY_CODE, "dataPublicacao": date_br})
    result = _get_json(request, f"{BASE_URL}/public/home/{endpoint}?{params}")
    if not isinstance(result, bool):
        raise RuntimeError("o portal retornou um indicador de edição inválido")
    return result


def _validate_edition(request, date_hyphen: str, *, extra: bool) -> None:
    endpoint = "buscarJornalExtra" if extra else "buscarJornal"
    params = urlencode(
        {"codigoDiario": DIARY_CODE, "dataPublicacao": date_hyphen}
    )
    result = _get_json(
        request, f"{BASE_URL}/public/visualizar-jornal/{endpoint}?{params}"
    )
    if not isinstance(result, dict) or not result.get("id"):
        raise RuntimeError("o portal não informou os metadados da edição")
    if str(result.get("name", "")).lower().rsplit(".", 1)[-1] != "pdf":
        raise RuntimeError("a edição informada pelo portal não é um PDF")


def _edition_filename(date_value: str, *, extra: bool) -> str:
    suffix = "E" if extra else ""
    return f"{date_value}{suffix}.pdf"


def search(page, keyword: str, date_value: str) -> None:
    date_value = normalize_date(date_value)
    date_br = date_as_br(date_value)
    date_hyphen = date_br.replace("/", "-")
    request = page.context.request

    saved = 0
    found = 0
    for extra in (False, True):
        if not _edition_exists(request, date_br, extra=extra):
            continue

        found += 1
        _validate_edition(request, date_hyphen, extra=extra)
        filename = _edition_filename(date_value, extra=extra)
        url = (
            f"{REPOSITORY_URL}/{DIARY_CODE}/arquivos/resumoDiario/"
            f"{date_value}/{filename}"
        )
        response = request.get(url, timeout=120_000)
        if not response.ok:
            raise RuntimeError(f"diário indisponível (HTTP {response.status})")
        saved += len(
            save_matching_pdf(
                response.body(), STATE, [keyword], filename, date_value
            )
        )

    if not found:
        print(f"[{STATE}] nenhuma edição publicada em {date_value}")
        return
    print(
        f"[{STATE}] {saved} edição(ões) completa(s) "
        f"com ocorrência exata em {date_value}"
    )


def scrape(playwright=None, *, keywords=None, date_value=None, headless=True) -> None:
    if playwright is None:
        scrape_with_playwright(
            STATE,
            search,
            keywords=keywords,
            date_value=date_value,
            headless=headless,
        )
    else:
        run_for_keywords(
            playwright,
            STATE,
            search,
            keywords=keywords,
            date_value=date_value,
            headless=headless,
        )


if __name__ == "__main__":
    scrape()
