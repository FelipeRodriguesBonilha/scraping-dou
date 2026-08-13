from __future__ import annotations

import re
import time
from base64 import b64decode
from io import BytesIO
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, urljoin, urlparse

from .common import (
    click_next,
    date_parts_br,
    paginate,
    run_for_keywords,
    save_download,
    scrape_with_playwright,
)


STATE = "RJ"
SEARCH_URL = "https://www.ioerj.com.br/portal/modules/conteudoonline/busca_do.php"


class _ResponseDownload:
    def __init__(self, content: bytes, filename: str) -> None:
        self._content = content
        self.suggested_filename = filename

    def save_as(self, target: str | Path) -> None:
        Path(target).write_bytes(self._content)


def _complete_pdf_content(content: bytes) -> bytes:
    if not content.startswith(b"%PDF"):
        raise RuntimeError("PDF do IOERJ não começa com a assinatura esperada")

    eof_at = content.rfind(b"%%EOF")
    if eof_at < 0:
        raise RuntimeError("PDF do IOERJ não possui o marcador final %%EOF")
    complete = content[: eof_at + len(b"%%EOF")]

    try:
        from pypdf import PdfReader

        PdfReader(BytesIO(complete), strict=True)
    except Exception as error:
        raise RuntimeError(f"PDF do IOERJ inválido: {error}") from error
    return complete


def _result_filename(result_link, date_value: str) -> str:
    encoded_id = parse_qs(urlparse(result_link.get_attribute("href") or "").query).get(
        "i", [""]
    )[0]
    try:
        publication_id = b64decode(encoded_id).decode("ascii")
    except Exception:
        publication_id = "resultado"
    return f"IOERJ-{date_value}-materia-{publication_id}.pdf"


def _new_page(context, existing_pages, timeout_ms: int = 5_000):
    deadline = time.monotonic() + timeout_ms / 1_000
    while time.monotonic() < deadline:
        for candidate in context.pages:
            if candidate not in existing_pages:
                return candidate

        context.pages[0].wait_for_timeout(100)
    raise TimeoutError("nova janela de download do IOERJ não foi aberta")


def _viewer_page_after_download_click(context, detail_page, existing_pages):
    try:
        return _new_page(context, existing_pages)
    except TimeoutError:
        try:
            detail_page.locator("iframe#ContDo").wait_for(
                state="attached", timeout=5_000
            )
            return detail_page
        except Exception as error:
            raise TimeoutError(
                "o visualizador do IOERJ não abriu uma nova aba nem carregou na aba atual"
            ) from error


def _download_result(
    page,
    result_link,
    keyword: str,
    date_value: str,
    seen_issues: set[str],
) -> bool:
    detail_page = None
    download_page = None
    try:
        with page.expect_popup(timeout=30_000) as detail_info:
            result_link.click()
        detail_page = detail_info.value
        detail_page.once("dialog", lambda dialog: dialog.dismiss())

        viewer_download = detail_page.get_by_role("button", name="Download").first
        viewer_download.wait_for(state="visible", timeout=30_000)
        detail_page.wait_for_timeout(1_500)

        existing_pages = set(page.context.pages)
        viewer_download.click(no_wait_after=True)
        download_page = _viewer_page_after_download_click(
            page.context, detail_page, existing_pages
        )
        pdf_frame = download_page.locator("iframe#ContDo")
        pdf_frame.wait_for(state="attached", timeout=30_000)
        pdf_url = urljoin(download_page.url, pdf_frame.get_attribute("src") or "")
        if not pdf_url:
            raise RuntimeError("visualizador do IOERJ não informou a URL do PDF")
        issue_key = pdf_url.split("#", 1)[0]
        if issue_key in seen_issues:
            return False

        response = page.context.request.get(pdf_url, timeout=60_000)
        if response.status != 200:
            raise RuntimeError(f"PDF do IOERJ indisponível (HTTP {response.status})")
        content = _complete_pdf_content(response.body())
        save_download(
            _ResponseDownload(content, _result_filename(result_link, date_value)),
            STATE,
            keyword,
            date_value=date_value,
        )
        seen_issues.add(issue_key)
        return True
    except Exception as error:
        print(f"[{STATE}] falha ao baixar edição para '{keyword}': {error}")
        return False
    finally:
        for popup in (download_page, detail_page):
            if popup is not None:
                try:
                    popup.close()
                except Exception:
                    pass


def _process_results(
    page,
    keyword: str,
    date_value: str,
    seen_issues: set[str],
) -> int:
    result_links = page.locator('a[href*="view_publicacao.php"]')
    total = result_links.count()
    saved = 0
    for index in range(total):
        if _download_result(
            page, result_links.nth(index), keyword, date_value, seen_issues
        ):
            saved += 1
    return saved


def _go_to_next_page(page) -> bool:
    next_link = page.get_by_role("link", name=re.compile(r"^(>|\u00bb|pr\u00f3xima)$", re.I))
    return click_next(next_link)


def search(page, keyword: str, date_value: str) -> None:
    day, month, year = date_parts_br(date_value)
    page.goto(SEARCH_URL, wait_until="domcontentloaded")

    phrase = keyword.strip().strip('"')
    page.locator('input[name="textobusca"]').fill(f'"{phrase}"' if phrase else keyword)
    page.locator('select[name="tipobusca"]').select_option("texto")
    page.locator('input[name="datapublicacao[dia]"]').fill(day)
    page.locator('input[name="datapublicacao[mes]"]').fill(month)
    page.locator('input[name="datapublicacao[ano]"]').fill(year)

    with page.expect_navigation(wait_until="domcontentloaded"):
        page.locator('input[name="buscar"]').click()

    seen_issues: set[str] = set()
    paginate(
        lambda _first_result: _process_results(
            page, keyword, date_value, seen_issues
        ),
        lambda: _go_to_next_page(page),
    )


def scrape(
    playwright=None,
    keywords: Iterable[str] | None = None,
    date_value=None,
    headless: bool = True,
) -> None:
    if playwright is None:
        scrape_with_playwright(
            STATE,
            search,
            keywords=keywords,
            date_value=date_value,
            headless=headless,
        )
        return
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
