import re
import time
import config
from playwright.sync_api import Playwright, sync_playwright, expect


def run(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto("https://diario.imprensaoficial.al.gov.br/")
    page.get_by_role("textbox", name="Buscar por: (Qualquer palavra").click()
    page.get_by_role("textbox", name="Buscar por: (Qualquer palavra").fill("vistoria veicular")
    page.get_by_role("textbox", name="Período inicial:").fill(config.DATE)
    page.get_by_role("textbox", name="Período final:").fill(config.DATE)
    page.locator("#selectBuscaTipo").get_by_role("searchbox", name="Search for option").click()
    page.get_by_text("Qualquer palavra").click()
    page.get_by_role("button", name="Buscar").click()
    with page.expect_download() as download_info:
        page.get_by_role("link", name="Download").first.click()
    download = download_info.value
    page.locator("li").filter(has_text="Próximo").click()
    time.sleep(3)

    # ---------------------
    context.close()
    browser.close()


with sync_playwright() as playwright:
    run(playwright)