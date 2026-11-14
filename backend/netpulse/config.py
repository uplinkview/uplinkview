"""Konfiguracja z zmiennych środowiskowych (prefiks NETPULSE_)."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env(name: str, default: str) -> str:
    return os.environ.get(f"NETPULSE_{name}", default)


@dataclass(frozen=True)
class Settings:
    database_url: str = _env(
        "DATABASE_URL", "postgresql+asyncpg://netpulse:netpulse@localhost:5432/netpulse"
    )
    # Co ile sekund odpytywać urządzenia
    poll_interval: int = int(_env("POLL_INTERVAL", "30"))
    # Ile urządzeń odpytywać równolegle
    poll_concurrency: int = int(_env("POLL_CONCURRENCY", "16"))
    # Co ile sekund czytać liczniki portów WAN do wykresu prawdziwej prędkości co 5 s (wanrate.py, od 0.85.0); 0 = bez pomiaru
    wan_sample_interval: float = float(_env("WAN_SAMPLE_INTERVAL", "0.5"))
    snmp_timeout: float = float(_env("SNMP_TIMEOUT", "2"))
    snmp_retries: int = int(_env("SNMP_RETRIES", "1"))
    # Limit czasu całego odczytu jednego urządzenia w s (od 0.77.0); puste = max(20, interwał − 5), 0 = bez limitu
    poll_timeout: float | None = float(_env("POLL_TIMEOUT", "")) if _env("POLL_TIMEOUT", "") else None

    @property
    def effective_poll_timeout(self) -> float:
        """Limit czasu odczytu urządzenia w s (0 = bez limitu)."""
        if self.poll_timeout is not None:
            return max(self.poll_timeout, 0.0)
        return float(max(20, self.poll_interval - 5))
    # Ile dni trzymać surowe metryki (TimescaleDB retention policy)
    retention_days: int = int(_env("RETENTION_DAYS", "30"))
    # Ile dni trzymać agregaty godzinowe (wykresy z całego roku i dostępność; aggregates.py)
    aggregate_retention_days: int = int(_env("AGGREGATE_RETENTION_DAYS", "730"))
    # Po ilu dniach TimescaleDB kompresuje surowe metryki (compression.py); 0 = bez kompresji
    compress_after_days: int = int(_env("COMPRESS_AFTER_DAYS", "7"))
    api_host: str = _env("API_HOST", "0.0.0.0")
    api_port: int = int(_env("API_PORT", "8000"))
    log_level: str = _env("LOG_LEVEL", "INFO")
    # Strefa czasowa do wyświetlania dat (zmienna TZ z .env, np. Europe/Warsaw)
    timezone: str = os.environ.get("TZ", "UTC")
    # Katalog ze zbudowanym panelem (puste = API bez panelu, np. development)
    web_dir: str = _env("WEB_DIR", "")
    # Ważność sesji logowania (dni)
    session_days: int = int(_env("SESSION_DAYS", "30"))
    # Ile sekund API pamięta sprawdzoną sesję (bez pytania bazy przy każdym żądaniu); 0 = zawsze pytaj bazę
    session_cache_s: float = float(_env("SESSION_CACHE_S", "10"))
    # Dodatkowe dozwolone adresy panelu (np. za reverse proxy), oddzielone przecinkami:
    # https://netpulse.example.lan
    trusted_origins: str = _env("TRUSTED_ORIGINS", "")
    # HTTPS (od 0.62.0): katalog certyfikatów kontenera proxy i port HTTPS na serwerze (do linków w panelu)
    tls_dir: str = _env("TLS_DIR", "")
    https_port: str = _env("HTTPS_PORT", "")
    # Adresy proxy, którym API wierzy w X-Forwarded-For/-Proto (w Dockerze API jest dostępne tylko przez proxy: "*")
    forwarded_allow_ips: str = _env("FORWARDED_ALLOW_IPS", "127.0.0.1")
    # Usługa aktualizacji (osobny kontener z dostępem do Dockera); bez tokenu aktualizacja z panelu jest wyłączona
    updater_url: str = _env("UPDATER_URL", "")
    # Token: z pliku we wspólnym wolumenie (tworzy go usługa aktualizacji) albo wprost ze zmiennej
    updater_token: str = _env("UPDATER_TOKEN", "")
    updater_token_file: str = _env("UPDATER_TOKEN_FILE", "")
    # Dysk, którego zajętość pokazuje stan serwera (w kontenerze „/” to dysk z danymi Dockera)
    system_disk_path: str = _env("SYSTEM_DISK_PATH", "/")
    # Bez puli połączeń (testy, jednorazowe polecenia CLI)
    db_nullpool: bool = _env("DB_NULLPOOL", "0") == "1"
    # Klucz szyfrowania sekretów w bazie (crypto.py): zmienna albo plik tworzony przy pierwszym starcie
    secret_key: str = _env("SECRET_KEY", "")
    secret_key_file: str = _env("SECRET_KEY_FILE", "/var/lib/netpulse/secret.key")


settings = Settings()
