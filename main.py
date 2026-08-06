from scrapers import ac, al, am, ap, ba, df, ma, mt, pa, pe, pi, pr, rj, rr, rs, se, to

SCRAPERS = []

for scraper in SCRAPERS:
    print(f"[{scraper.STATE}] iniciando...")
    scraper.scrape()
    print(f"[{scraper.STATE}] concluído.")