import re
import time
import config
from playwright.sync_api import Playwright, sync_playwright, expect


def run(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto("https://www.ioerj.com.br/portal/modules/conteudoonline/busca_do.php")
    page.get_by_role("searchbox", name="Preencha uma ou mais palavras").click()
    page.get_by_role("searchbox", name="Preencha uma ou mais palavras").fill("vistoria veicular")
    page.locator("input[name=\"datapublicacao[dia]\"]").fill(config.DATE.split("/")[0])
    page.locator("input[name=\"datapublicacao[mes]\"]").fill(config.DATE.split("/")[1])
    page.locator("input[name=\"datapublicacao[ano]\"]").fill(config.DATE.split("/")[2])
    page.get_by_role("button", name="Buscar").click()
    with page.expect_popup() as page1_info:
        page.get_by_role("row", name="04/08/2026 página 6 - Matéria Id: 2753846", exact=True).get_by_role("link").click()
    page1 = page1_info.value
    page1.once("dialog", lambda dialog: dialog.dismiss())
    with page1.expect_popup() as page2_info:
        page1.get_by_role("button", name="Download").click()
    page2 = page2_info.value
    with page2.expect_download() as download_info:
        page2.locator("iframe[name=\"ContDo\"]").content_frame.locator("iframe[name=\"BF75F0840BBC797390543F9E3FFFA921\"]").content_frame.get_by_role("button", name="Baixar").click()
    download = download_info.value
    time.sleep(3)
    # ---------------------
    context.close()
    browser.close()


with sync_playwright() as playwright:
    run(playwright)