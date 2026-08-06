import re
import time
import config
from playwright.sync_api import Playwright, sync_playwright, expect


def run(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto("https://www.ioepa.com.br/pesquisa/")
    page.get_by_role("textbox", name="Texto da pesquisa").click()
    page.get_by_role("textbox", name="Texto da pesquisa").fill("hospital")
    page.locator("#InputDataInicial").fill(config.DATE)
    page.locator("#InputDataFinal").fill(config.DATE)
    page.get_by_role("button", name="Pesquisar").click()
    page.get_by_role("link", name="Download").first.click()
    with page.expect_popup() as page1_info:
        page.get_by_role("menuitem", name="Diário Completo").click()
    page1 = page1_info.value
    page.get_by_role("link", name="»").first.click()
    time.sleep(3)
    # ---------------------
    context.close()
    browser.close()


with sync_playwright() as playwright:
    run(playwright)