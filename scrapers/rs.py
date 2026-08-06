import re
import time
import config
from playwright.sync_api import Playwright, sync_playwright, expect


def run(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto("https://www.diariooficial.rs.gov.br/resultado")
    page.get_by_role("textbox", name="Digite").click()
    page.get_by_role("textbox", name="Digite").fill("vistoria veicular")
    page.get_by_role("textbox", name="Data inicial").fill(config.DATE)
    page.get_by_role("textbox", name="Data final").fill(config.DATE)
    page.get_by_role("button", name="Buscar").click()
    page.get_by_role("link", name="Portarias - 16/06/").click()
    with page.expect_download() as download_info:
        page.get_by_role("button", name="Download PDF", exact=True).click()
    download = download_info.value
    time.sleep(3)
    # ---------------------
    context.close()
    browser.close()


with sync_playwright() as playwright:
    run(playwright)