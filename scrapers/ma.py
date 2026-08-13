from __future__ import annotations

import html
from pathlib import Path
import re
from typing import Iterable
from urllib.parse import urlencode

from playwright.sync_api import Page, Playwright

from scrapers.common import (
    date_as_br,
    is_enabled,
    run_for_keywords,
    save_download,
    save_occurrence_metadata,
    scrape_with_playwright,
)


STATE = "MA"
URL = "https://diariooficial.ma.gov.br/index.php"
PDF_DOWNLOAD_URL = "https://diariooficial.ma.gov.br/download.php"
MAX_LOAD_MORE = 10_000
DOWNLOAD_TIMEOUT_MS = 120_000
ISSUE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


class _ResponseDownload:
    def __init__(self, content: bytes, filename: str) -> None:
        self._content = content
        self.suggested_filename = filename

    def save_as(self, target: str | Path) -> None:
        Path(target).write_bytes(self._content)


def _issue_id(result) -> str | None:
    values = re.findall(r"'([^']*)'", result.get_attribute("onclick") or "")
    if len(values) < 3:
        return None
    candidate = values[2].strip()
    return candidate if ISSUE_ID_PATTERN.fullmatch(candidate) else None


def _result_occurrence(result, keyword: str, date_value: str) -> tuple[str, dict[str, str]] | None:
    values = re.findall(r"'([^']*)'", result.get_attribute("onclick") or "")
    issue_id = _issue_id(result)
    if issue_id is None or len(values) < 5:
        return None

    page = values[4].strip()
    if page.isdigit():
        page = str(int(page))
    else:
        page = ""
    return issue_id, {
        "date": date_as_br(date_value),
        "section": html.unescape(values[0]).strip(),
        "page": page,
        "term": keyword,
    }


def _result_key(result, index: int) -> str:
    return _issue_id(result) or result.get_attribute("href") or f"resultado-{index}"


def _pdf_content(response, issue_id: str) -> bytes:
    content = response.body()
    if response.status != 200:
        raise RuntimeError(f"PDF da edição {issue_id} indisponível (HTTP {response.status})")
    if not content.startswith(b"%PDF"):
        raise RuntimeError(f"resposta da edição {issue_id} não é um PDF")
    return content


def _download_result(page: Page, issue_id: str, keyword: str, date_value: str) -> Path:
    response = page.context.request.get(
        f"{PDF_DOWNLOAD_URL}?{urlencode({'arq': issue_id})}",
        headers={"Referer": URL},
        timeout=DOWNLOAD_TIMEOUT_MS,
    )
    return save_download(
        _ResponseDownload(_pdf_content(response, issue_id), f"DOEMA-{issue_id}.pdf"),
        STATE,
        keyword,
        date_value=date_value,
        extract_occurrences=False,
        deduplicate_identical=True,
    )


def _wait_for_first_batch(page: Page) -> None:
    page.wait_for_function(
        """() => document.querySelectorAll('a.btnVermais').length > 0
            || document.body.innerText.includes('Nada encontrado')""",
        timeout=30_000,
    )


def search(page: Page, keyword: str, date_value: str) -> None:
    query = urlencode(
        {
            "page": "busca",
            "termo": keyword,
            "tipo": "",
            "dti": date_value,
            "dtf": date_value,
        }
    )
    page.goto(f"{URL}?{query}", wait_until="domcontentloaded")
    _wait_for_first_batch(page)

    occurrences_by_issue: dict[str, list[dict[str, str]]] = {}
    failed_issues: list[str] = []
    processed = 0
    for _ in range(MAX_LOAD_MORE):
        results = page.locator("a.btnVermais")
        total = results.count()
        for index in range(processed, total):
            result = results.nth(index)
            issue_key = _result_key(result, index)
            try:
                occurrence = _result_occurrence(result, keyword, date_value)
                if occurrence is None:
                    raise RuntimeError("dados da ocorrência não encontrados")
                issue_id, record = occurrence
                occurrences_by_issue.setdefault(issue_id, []).append(record)
            except Exception as error:
                failed_issues.append(issue_key)
                print(f"[{STATE}] falha ao ler ocorrência {index + 1}: {error}")
        processed = total

        load_more = page.locator("#btnList")
        if not is_enabled(load_more):
            break
        load_more.click()
        page.wait_for_function(
            """previous => {
                const button = document.querySelector('#btnList');
                return document.querySelectorAll('a.btnVermais').length > previous
                    || !button || button.disabled;
            }""",
            arg=processed,
            timeout=30_000,
        )

    for index, (issue_id, records) in enumerate(occurrences_by_issue.items(), start=1):
        try:
            pdf_path = _download_result(page, issue_id, keyword, date_value)
            save_occurrence_metadata(
                STATE,
                keyword,
                pdf_path.name,
                records,
                date_value=date_value,
            )
        except Exception as error:
            failed_issues.append(issue_id)
            print(f"[{STATE}] falha ao baixar edição {index}: {error}")

    if failed_issues:
        raise RuntimeError(
            f"{len(failed_issues)} edição(ões) não puderam ser baixadas para '{keyword}'"
        )


def scrape(
    playwright: Playwright | None = None,
    keywords: Iterable[str] | None = None,
    date_value: object | None = None,
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
