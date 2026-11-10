# Python 3.12 is included in the project's Linux CI matrix.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

WORKDIR /app

# libgomp1 supports native libraries used by some Chroma dependencies.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 edicola \
    && useradd --system --uid 10001 --gid 10001 --create-home --home-dir /home/edicola edicola

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

# Copy application sources only: no PDFs, databases, or secrets.
COPY --chown=edicola:edicola app.py ./app.py
COPY --chown=edicola:edicola edicola/ ./edicola/
COPY --chown=edicola:edicola .streamlit/config.toml ./.streamlit/config.toml
RUN mkdir -p /app/data/incoming /home/edicola/.streamlit \
    && chown -R edicola:edicola /app/data /home/edicola

USER edicola
EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3)" || exit 1

CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
