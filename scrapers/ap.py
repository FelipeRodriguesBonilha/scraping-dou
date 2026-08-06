import re
import time
import config
from playwright.sync_api import Playwright, sync_playwright, expect


def run(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto("https://diofe.portal.ap.gov.br/")
    page.locator("#input2").click()
    page.locator("#input2").fill("vistoria veicular")
    page.locator("#dataBuscaInicial").fill(config.DATE)
    page.locator("#dataBuscaFinal").fill(config.DATE)
    page.get_by_role("button", name="OK").nth(2).click()
    page.get_by_role("checkbox").uncheck()
    page.get_by_role("button").filter(has_text=re.compile(r"^$")).nth(2).click()
    page.get_by_role("button", name="   Download").first.click()
    with page.expect_download() as download_info:
        page.get_by_role("link", name=" Baixar Diário completo").click()
    download = download_info.value
    page.get_by_role("link", name="»").click()
    time.sleep(3)
    # ---------------------
    context.close()
    browser.close()


with sync_playwright() as playwright:
    run(playwright)