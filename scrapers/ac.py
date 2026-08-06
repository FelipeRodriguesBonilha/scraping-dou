import re
import time
from playwright.sync_api import Playwright, sync_playwright, expect


def run(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto("https://diario.ac.gov.br/")
    page.get_by_role("textbox", name="Palavra-Chave").click()
    page.get_by_role("textbox", name="Palavra-Chave").fill("vistoria veicular")
    page.locator("#buscaPorPalavra").get_by_role("button").click()
    page.get_by_role("radio", name="Contém o texto").check()
    
    with page.expect_download() as download_info:
        page.get_by_role("link", name="Diário Oficial N° 14323 -").click()
    download = download_info.value
    page.get_by_text("›").click()
    time.sleep(3)

    # ---------------------
    context.close()
    browser.close()


with sync_playwright() as playwright:
    run(playwright)