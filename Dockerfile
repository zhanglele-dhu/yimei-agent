FROM python:3.13-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends fonts-noto-cjk && rm -rf /var/lib/apt/lists/*
COPY requirements-studio.lock.txt /app/requirements-studio.lock.txt
RUN pip install --no-cache-dir -r requirements-studio.lock.txt
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright
RUN python -m playwright install --with-deps chromium && chmod -R a+rX /opt/playwright
COPY studio /app/studio
COPY knowledge/procedures.md knowledge/shooting_guide.json /app/knowledge/
RUN useradd --create-home appuser && mkdir -p /data && chown appuser:appuser /data
USER appuser
ENV STUDIO_DATA_DIR=/data STUDIO_CARD_SETTINGS_FILE=/data/card-model.env PYTHONUNBUFFERED=1
EXPOSE 8010
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8010/healthz')"
CMD ["uvicorn", "studio.api:app", "--host", "0.0.0.0", "--port", "8010", "--workers", "1"]
