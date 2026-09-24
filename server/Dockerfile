FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY server/app ./app
COPY server/run.py ./run.py
COPY VERSION ./VERSION
COPY CHANGELOG.md ./CHANGELOG.md

# Version: the repo VERSION file is the default; a build arg (e.g. a git tag)
# overrides it. The app reads /app/VERSION, so Settings shows the deployed build.
ARG DOC_VERSION=""
RUN if [ -n "$DOC_VERSION" ]; then printf '%s' "$DOC_VERSION" | sed 's/^v//' > /app/VERSION; fi
# The same number on the image itself, so a server checking for an update can
# say which version is waiting without starting it first.
LABEL org.opencontainers.image.version="${DOC_VERSION}"
LABEL org.opencontainers.image.source="https://github.com/Mischa323/LeuffenDoc"

# The database, uploaded files and the vault's master key live on this volume.
ENV DOC_DB_PATH=/data/leuffendoc.db
VOLUME ["/data"]
EXPOSE 8000

# Whether the app actually answers, not just whether the process exists. Docker
# and Synology show it, and an update from the settings page waits for it
# before it throws the previous version away.
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3   CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)" || exit 1

CMD ["python", "run.py"]
