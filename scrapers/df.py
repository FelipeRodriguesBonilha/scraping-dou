import re
import time
import config
from playwright.sync_api import Playwright, sync_playwright, expect


def run(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto("https://dodf.df.gov.br/")
    page.get_by_role("searchbox", name="O que você quer buscar?").click()
    page.get_by_role("searchbox", name="O que você quer buscar?").fill("vistoria veicular")
    page.locator("section").filter(has_text="Pesquisas Recentes Limpar").locator("#btnFilter").click()
    page.get_by_role("textbox", name="Data Inicial").fill(config.DATE)
    page.get_by_role("textbox", name="Data Final").fill(config.DATE)
    page.locator("#formBuscaAcessoDiv").get_by_text("Busca Contextual").click()
    page.get_by_role("button", name=" Pesquisar").click()
    with page.expect_popup() as page1_info:
        page.get_by_role("link", name="DODF Nº 137 de 28 de Julho de").click()
    page1 = page1_info.value
    with page1.expect_download() as download_info:
        page1.locator("iframe[name=\"7D92B9E3B4214A79B3EDB624E6C6C6BD\"]").content_frame.get_by_role("button", name="Baixar").click()
    download = download_info.value
    page.get_by_role("link", name="»").click()
    time.sleep(3)
    # ---------------------
    context.close()
    browser.close()


with sync_playwright() as playwright:
    run(playwright)