import re
import time
import config
from playwright.sync_api import Playwright, sync_playwright, expect


def run(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto("https://diariooficial.ma.gov.br/index.php")
    page.get_by_role("searchbox", name="Digite um termo para busca").click()
    page.get_by_role("searchbox", name="Digite um termo para busca").fill("vistoria veicular")
    page.get_by_role("textbox", name="Data inicial").fill(config.DATE)
    page.get_by_role("textbox", name="Data final").fill(config.DATE)
    page.locator("#call-to-action-search").get_by_role("button").click()
    page.get_by_text("👁 Ver mais").first.click()
    with page.expect_popup() as page1_info:
        page.get_by_role("button", name="  Baixar PDF").click()
    page1 = page1_info.value
    with page1.expect_download() as download_info:
        page1.locator("iframe[name=\"F3F40B6512CB916B3679101C42E4D6AC\"]").content_frame.get_by_role("button", name="Baixar").click()
    download = download_info.value
    page.get_by_role("button", name="Carregar mais").click()
    time.sleep(3)
    # ---------------------
    context.close()
    browser.close()


with sync_playwright() as playwright:
    run(playwright)