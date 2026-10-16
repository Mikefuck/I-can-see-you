FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 focus \
    && useradd --uid 10001 --gid focus --no-create-home focus \
    && mkdir /data && chown focus:focus /data
COPY --chown=focus:focus app ./app
USER focus
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz',timeout=3)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--timeout-graceful-shutdown", "5", "--no-access-log"]
