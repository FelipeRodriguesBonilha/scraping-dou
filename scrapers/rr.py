import re
from playwright.sync_api import Playwright, sync_playwright, expect


def run(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto("https://www.imprensaoficial.rr.gov.br/app/_visualizar-mes/")
    page.get_by_role("link", name=" - PESQUISAR POR PALAVRA").click()
    page.get_by_role("textbox", name="pesquisar").click()
    page.get_by_role("textbox", name="pesquisar").fill("vistoria veicular")
    page.get_by_role("textbox", name="pesquisar").press("Enter")
    page.get_by_role("link", name="D.O.E. Nº 855.pmd - Diário").click()
    with page.expect_download() as download_info:
        page.locator("iframe[name=\"1B78F05A3B3BDC3B32FAA5347A7EC94B\"]").content_frame.get_by_role("button", name="Baixar").click()
    download = download_info.value

    # ---------------------
    context.close()
    browser.close()


with sync_playwright() as playwright:
    run(playwright)