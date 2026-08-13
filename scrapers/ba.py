from scrapers.common import skip_login_only


STATE = "BA"
LOGIN_REQUIRED = True


def scrape(playwright=None, keywords=None, date_value=None, headless: bool = True) -> None:
    del playwright, keywords, date_value, headless
    skip_login_only(STATE)
