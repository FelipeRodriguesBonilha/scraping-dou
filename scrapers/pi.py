import re
import time
from playwright.sync_api import Playwright, sync_playwright, expect


def run(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto("https://www.diario.pi.gov.br/doe/")
    page.get_by_role("link", name="Buscar por palavras").click()
    page.get_by_role("textbox", name="palavras-chave").click()
    page.get_by_role("textbox", name="palavras-chave").fill("vistoria veicular")
    page.locator("#submit").click()
    with page.expect_popup() as page1_info:
        page.get_by_role("link", name="baixar pdf baixar edição").first.click()
    page1 = page1_info.value
    with page1.expect_download() as download_info:
        page1.locator("iframe[name=\"AC6CA24F7940149D53B7AE9CBC6EDB60\"]").content_frame.get_by_role("button", name="Baixar").click()
    download = download_info.value
    time.sleep(3)
    # ---------------------
    context.close()
    browser.close()


with sync_playwright() as playwright:
    run(playwright)