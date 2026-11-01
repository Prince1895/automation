FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libharfbuzz0b \
        libffi8 \
        libcairo2 \
        libgdk-pixbuf-2.0-0 \
        libjpeg62-turbo \
        libopenjp2-7 \
        shared-mime-info \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

RUN useradd --create-home --uid 10001 instantlead \
    && mkdir -p /app/.tmp /app/logs \
    && chown -R instantlead:instantlead /app

USER instantlead

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import json,urllib.request; d=json.load(urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=4)); raise SystemExit(0 if d.get('ok') else 1)"

CMD ["sh", "-c", "python tools/init_db.py && exec uvicorn service.main:app --host 0.0.0.0 --port 8080"]
