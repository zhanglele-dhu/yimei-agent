FROM python:3.13-slim
WORKDIR /app
COPY requirements-studio.lock.txt /app/requirements-studio.lock.txt
RUN pip install --no-cache-dir -r requirements-studio.lock.txt
COPY studio /app/studio
RUN useradd --create-home appuser && mkdir -p /data && chown appuser:appuser /data
USER appuser
ENV STUDIO_DATA_DIR=/data STUDIO_CARD_SETTINGS_FILE=/data/card-model.env PYTHONUNBUFFERED=1
EXPOSE 8010
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8010/healthz')"
CMD ["python", "-m", "waitress", "--listen=0.0.0.0:8010", "studio.webapp:app"]
