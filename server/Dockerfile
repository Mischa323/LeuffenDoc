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

# The database, uploaded files and the vault's master key live on this volume.
ENV DOC_DB_PATH=/data/leuffendoc.db
VOLUME ["/data"]
EXPOSE 8000

CMD ["python", "run.py"]
