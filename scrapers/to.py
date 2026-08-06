import re
import time
import config
from playwright.sync_api import Playwright, sync_playwright, expect


def run(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto("https://diariooficial.to.gov.br/")
    page.get_by_role("button", name="search busca").click()
    page.get_by_role("searchbox", name="Texto exato").click()
    page.get_by_role("searchbox", name="Texto exato").fill("vistoria veicular")
    page.get_by_role("textbox", name="Data inicial").fill(config.DATE)
    page.get_by_role("textbox", name="Data final").fill(config.DATE)
    page.get_by_role("button", name="search Buscar texto").click()
    with page.expect_popup() as page1_info:
        page.get_by_role("link", name="Baixar edição 7100").click()
    page1 = page1_info.value
    with page1.expect_download() as download_info:
        page1.locator("iframe[name=\"93310AABA02F4C272FB15C8C2895C2A8\"]").content_frame.get_by_role("button", name="Baixar").click()
    download = download_info.value
    time.sleep(3)
    # ---------------------
    context.close()
    browser.close()


with sync_playwright() as playwright:
    run(playwright)