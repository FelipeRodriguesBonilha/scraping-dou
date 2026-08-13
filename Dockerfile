FROM python:3.12-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PYTHONIOENCODING=utf-8 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

COPY requirements.txt ./

RUN pip install --no-cache-dir -r requirements.txt \
    && python -m playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 10001 scraper \
    && useradd --uid 10001 --gid scraper --create-home --shell /usr/sbin/nologin scraper

COPY docker/entrypoint.sh /usr/local/bin/scraping-dou-entrypoint
RUN chmod 755 /usr/local/bin/scraping-dou-entrypoint

COPY --chown=scraper:scraper . .
RUN mkdir -p /app/downloads \
    && chown scraper:scraper /app/downloads \
    && chmod -R a+rX /ms-playwright

EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/scraping-dou-entrypoint"]
CMD ["python", "-u", "web/server.py", "--host", "0.0.0.0", "--port", "8000"]
