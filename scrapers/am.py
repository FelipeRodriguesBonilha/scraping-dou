import re
import time
import config
from playwright.sync_api import Playwright, sync_playwright, expect


def run(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto("https://diario.imprensaoficial.am.gov.br/")
    page.locator("#input2").click()
    page.locator("#input2").fill("hospital")
    page.locator("#dataBuscaInicial").fill(config.DATE)
    page.locator("#dataBuscaFinal").fill(config.DATE)
    page.get_by_role("button", name="OK").nth(2).click()
    page.get_by_role("button").nth(3).click()
    with page.expect_download() as download_info:
        with page.expect_popup() as page1_info:
            page.get_by_role("link", name="Baixar diário completo").click()
        page1 = page1_info.value
    download = download_info.value
    page1.close()
    page.get_by_label("Próxima página").first.click()
    time.sleep(3)
    
    # ---------------------
    context.close()
    browser.close()


with sync_playwright() as playwright:
    run(playwright)