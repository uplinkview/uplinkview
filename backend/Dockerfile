# Kontekst budowania: katalog główny repozytorium (patrz deploy/docker-compose.yml)

# --- 1. Panel (Node tylko do zbudowania; w obrazie końcowym go nie ma) ---
FROM node:24-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend ./
RUN npm run build

# --- 2. API i kolektor (Python) ---
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Czcionka z polskimi znakami do raportu PDF (netpulse/report.py)
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Najpierw zależności (lepsze cache warstw przy aktualizacjach). Od 0.68.0 z pliku blokady: dokładne wersje ze skrótami
# (pip odrzuca paczkę o innym skrócie), więc obraz zbudowany dziś i za miesiąc ma te same biblioteki.
# Nowa albo podniesiona zależność w pyproject.toml = odświeżyć plik (polecenie w docs/04-instalacja-i-aktualizacja.md).
COPY backend/requirements.lock ./
RUN pip install --require-hashes -r requirements.lock

COPY backend/pyproject.toml ./
COPY backend/netpulse ./netpulse
# hatchling (budowanie paczki) jest w pliku blokady – bez pobierania go osobno w nieprzypiętej wersji
RUN pip install --no-deps --no-build-isolation . \
    && useradd --system --uid 10001 --no-create-home netpulse \
    && install -d -o netpulse -g netpulse -m 700 /var/lib/netpulse

# Zbudowany panel – serwuje go API (NETPULSE_WEB_DIR)
COPY --from=web /web/dist /app/web
# Licencja AGPL-3.0 w obrazie (udostępniany program ma mieć jej tekst)
COPY LICENSE /app/LICENSE
ENV NETPULSE_WEB_DIR=/app/web

USER netpulse
EXPOSE 8000
CMD ["netpulse", "api"]
