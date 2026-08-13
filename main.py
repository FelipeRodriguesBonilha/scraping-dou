from __future__ import annotations

import argparse
from collections.abc import Iterable

from scrapers import ac, al, am, ap, ba, df, ma, mt, pa, pe, pi, pr, rj, rr, rs, se, to


SCRAPERS = [ac, al, am, ap, ba, df, ma, mt, pa, pe, pi, pr, rj, rr, rs, se, to]


def main(
    *,
    keywords: Iterable[str] | None = None,
    date_value: str | None = None,
    headless: bool = True,
    states: Iterable[str] | None = None,
) -> int:
    selected_states = {state.upper() for state in states} if states else None
    selected_scrapers = [
        scraper
        for scraper in SCRAPERS
        if selected_states is None or scraper.STATE in selected_states
    ]
    if not selected_scrapers:
        print("Nenhum scraper corresponde às UFs informadas.")
        return 2

    print(f"[sistema] {len(selected_scrapers)} UF(s) selecionada(s).")

    login_only = [
        scraper for scraper in selected_scrapers if getattr(scraper, "LOGIN_REQUIRED", False)
    ]
    browser_scrapers = [scraper for scraper in selected_scrapers if scraper not in login_only]
    failures = 0

    for scraper in login_only:
        print(f"[{scraper.STATE}] iniciando...")
        try:
            scraper.scrape(
                keywords=keywords,
                date_value=date_value,
                headless=headless,
            )
        except Exception as error:
            failures += 1
            print(f"[{scraper.STATE}] falhou: {error}")
        else:
            print(f"[{scraper.STATE}] concluído.")

    if not browser_scrapers:
        print(
            f"[sistema] execução concluída: {len(selected_scrapers)} UF(s), "
            f"{failures} falha(s)."
        )
        return 1 if failures else 0

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright não está instalado. Execute: pip install -r requirements.txt")
        print("Depois instale o navegador: playwright install chromium")
        return 2

    with sync_playwright() as playwright:
        for scraper in browser_scrapers:
            print(f"[{scraper.STATE}] iniciando...")
            try:
                scraper.scrape(
                    playwright,
                    keywords=keywords,
                    date_value=date_value,
                    headless=headless,
                )
            except Exception as error:
                failures += 1
                print(f"[{scraper.STATE}] falhou: {error}")
            else:
                print(f"[{scraper.STATE}] concluído.")

    print(
        f"[sistema] execução concluída: {len(selected_scrapers)} UF(s), "
        f"{failures} falha(s)."
    )
    return 1 if failures else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Baixa os diários oficiais pesquisados.")
    parser.add_argument(
        "--date",
        dest="date_value",
        help="Data da pesquisa, em YYYY-MM-DD ou DD/MM/YYYY (padrão: hoje).",
    )
    parser.add_argument(
        "--keyword",
        action="append",
        dest="keywords",
        help="Pesquisa apenas esta palavra-chave; pode ser repetido.",
    )
    parser.add_argument(
        "--state",
        action="append",
        dest="states",
        help="Executa apenas a UF indicada; pode ser repetido.",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Mostra a janela do navegador durante a execução.",
    )
    return parser.parse_args()

if __name__ == "__main__":
    arguments = parse_args()
    raise SystemExit(
        main(
            keywords=arguments.keywords,
            date_value=arguments.date_value,
            states=arguments.states,
            headless=not arguments.headed,
        )
    )
