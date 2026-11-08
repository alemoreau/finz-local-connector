# Connecteur local de Finz, sans interface : serveur, NAS, Dokploy.
# Données (réglages, secrets chiffrés, sessions, journaux) dans le volume /data ; clé de
# chiffrement par FINZ_LOCAL_CONNECTOR_KEY ou FINZ_LOCAL_CONNECTOR_KEY_FILE (secret Docker).

FROM python:3.13-slim AS modules
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates patch \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY scripts/fetch-modules.sh scripts/
COPY patches/ patches/
RUN sh scripts/fetch-modules.sh /opt/woob-modules

FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FINZ_LOCAL_CONNECTOR_DATA=/data \
    FINZ_LOCAL_CONNECTOR_SECRETS=file \
    FINZ_WOOB_MODULES=/opt/woob-modules
COPY --from=modules /opt/woob-modules /opt/woob-modules
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir . \
 && useradd --system --uid 10001 --home-dir /data --shell /usr/sbin/nologin connector \
 && mkdir -p /data && chown connector /data
USER connector
VOLUME /data
HEALTHCHECK --interval=5m --timeout=30s CMD ["finz-local-connector", "status", "--local"]
ENTRYPOINT ["finz-local-connector"]
CMD ["run"]
