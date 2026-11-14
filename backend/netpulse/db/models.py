"""Modele bazy danych (SQLAlchemy 2).

Tabele konfiguracyjne: devices, interfaces, wifi_networks.
Kontrolery UniFi: controllers, network_clients, known_clients, topology_links. Alerty: alert_rules, alerts. Konta: users, auth_sessions. Ustawienia konta: dashboards (układ pulpitu), user_preferences.
Agenci serwerów Linux: agents. Łącza WAN routera (dual WAN / failover): wan_links. Tabele metryk (TimescaleDB hypertables): interface_metrics, device_metrics,
wifi_metrics, poe_port_metrics, poe_budget_metrics, system_metrics, disk_metrics, server_metrics, wan_link_metrics, client_metrics oraz ogólna
tabela metrics (nazwa + klucz + wartość) na to, co nie mieści się w stałych kolumnach.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from ..crypto import EncryptedText
from ..freshness import is_stale, live_status
from ..verification import device_level


class Base(DeclarativeBase):
    pass


# Fabryczne community SNMP – panel ostrzega, że trzeba je zmienić (od 0.31.1)
DEFAULT_COMMUNITIES = frozenset({"public", "private"})
# Urządzenia bez SNMP: serwer z agentem, węzeł Proxmox, urządzenie UniFi z oficjalnego API (od 0.52.0).
# Kolektor SNMP ich nie odpytuje, a w panelu nie mają ustawień SNMP.
NON_SNMP_DRIVERS = ("agent", "proxmox", "unifi_api")


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    host: Mapped[str] = mapped_column(String(255), unique=True)
    port: Mapped[int] = mapped_column(Integer, default=161)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    driver: Mapped[str] = mapped_column(String(32), default="auto")

    # SNMP – v1/v2c
    snmp_version: Mapped[str] = mapped_column(String(4), default="2c")
    # Sekrety (community, klucze SNMPv3) są w bazie zaszyfrowane – crypto.py
    community: Mapped[str | None] = mapped_column(EncryptedText, default="public")
    # SNMP – v3
    v3_username: Mapped[str | None] = mapped_column(String(128))
    v3_auth_protocol: Mapped[str | None] = mapped_column(String(16))
    v3_auth_key: Mapped[str | None] = mapped_column(EncryptedText)
    v3_priv_protocol: Mapped[str | None] = mapped_column(String(16))
    v3_priv_key: Mapped[str | None] = mapped_column(EncryptedText)
    v3_context: Mapped[str | None] = mapped_column(String(128))

    # Wykryte przy odpytywaniu
    detected_driver: Mapped[str | None] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(16), default="other")
    vendor: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(64))
    firmware: Mapped[str | None] = mapped_column(String(64))
    sys_name: Mapped[str | None] = mapped_column(String(255))
    sys_descr: Mapped[str | None] = mapped_column(Text)
    sys_object_id: Mapped[str | None] = mapped_column(String(255))
    uptime_s: Mapped[float | None] = mapped_column(Float)

    status: Mapped[str] = mapped_column(String(16), default="unknown")  # up | down | unknown
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    interfaces: Mapped[list[Interface]] = relationship(
        back_populates="device", cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def stale(self) -> bool:
        """Zapisany status jest nieaktualny – kolektor dawno nie wydał werdyktu (freshness.py)."""
        return is_stale(self.last_polled_at)

    @property
    def live_status(self) -> str:
        """Status do pokazania: `unknown`, gdy dane są nieaktualne (awaria ≠ brak danych)."""
        return live_status(self.status, self.last_polled_at)

    @property
    def verification(self) -> str:
        """Czy dane tego drivera potwierdzono na prawdziwym sprzęcie: verified | partial | test (verification.py)."""
        return device_level(self.driver)

    @property
    def uses_default_community(self) -> bool:
        """SNMP v1/v2c z fabrycznym community („public”, „private”) – każdy w sieci może czytać urządzenie."""
        return (
            self.snmp_version in ("1", "2c")
            and self.driver not in NON_SNMP_DRIVERS
            and (self.community or "").strip().lower() in DEFAULT_COMMUNITIES
        )

    wifi_networks: Mapped[list[WifiNetwork]] = relationship(
        back_populates="device", cascade="all, delete-orphan", passive_deletes=True
    )


class Interface(Base):
    __tablename__ = "interfaces"
    __table_args__ = (UniqueConstraint("device_id", "if_index"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    if_index: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(128))
    descr: Mapped[str | None] = mapped_column(String(255))
    alias: Mapped[str | None] = mapped_column(String(255))
    label: Mapped[str] = mapped_column(String(128), default="")
    if_type: Mapped[int | None] = mapped_column(Integer)
    mac: Mapped[str | None] = mapped_column(String(17))
    role: Mapped[str] = mapped_column(String(16), default="port")
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    admin_up: Mapped[bool | None] = mapped_column(Boolean)
    oper_status: Mapped[str] = mapped_column(String(16), default="unknown")
    speed_mbps: Mapped[int | None] = mapped_column(Integer)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    device: Mapped[Device] = relationship(back_populates="interfaces")


class WifiNetwork(Base):
    __tablename__ = "wifi_networks"
    __table_args__ = (UniqueConstraint("device_id", "key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(64))
    ssid: Mapped[str] = mapped_column(String(64))
    radio: Mapped[str | None] = mapped_column(String(16))
    channel: Mapped[int | None] = mapped_column(Integer)
    bssid: Mapped[str | None] = mapped_column(String(17))
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    clients: Mapped[int | None] = mapped_column(Integer)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    device: Mapped[Device] = relationship(back_populates="wifi_networks")


# --- konta ------------------------------------------------------------------


# Role kont (od 0.61.0): administrator – wszystko; operator – podgląd, potwierdzanie alertów, okna serwisowe;
# podgląd – tylko odczyt (plus własne hasło, odświeżanie i własne pulpity). Uprawnienia: api/security.py (ROLE_RULES).
ROLES = ("admin", "operator", "viewer")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    # Zostaje dla zgodności ze starszymi bazami; zawsze równe `role == "admin"` (ustawia `set_role`)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=True)
    role: Mapped[str] = mapped_column(String(16), default="admin")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Logowanie dwuskładnikowe (od 0.63.0, totp.py): sekret (zaszyfrowany; zapisany już przy konfiguracji,
    # ale działa dopiero po potwierdzeniu kodem – totp_enabled), ostatni użyty krok czasu, skróty kodów zapasowych
    totp_secret: Mapped[str | None] = mapped_column(EncryptedText)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    totp_last_step: Mapped[int | None] = mapped_column(BigInteger)
    totp_recovery: Mapped[list | None] = mapped_column(JSONB)

    def set_role(self, role: str) -> None:
        if role not in ROLES:
            raise ValueError(f"Nieznana rola: {role}")
        self.role, self.is_admin = role, role == "admin"


class AuthSession(Base):
    """Sesja logowania. W bazie tylko skrót SHA-256 tokenu z ciasteczka."""

    __tablename__ = "auth_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))


class Dashboard(Base):
    """Pulpit: wersjonowany JSON z widgetami (schemat: api/layout_schemas.py). Użytkownik może mieć kilka pulpitów;
    domyślny (`is_default`) otwiera się pod „/”.

    Pulpit publiczny ma nieodgadywalny token w adresie `/p/<token>` (w bazie skrót do wyszukania i zaszyfrowana
    wartość, żeby panel mógł pokazać link ponownie), opcjonalną datę wygaśnięcia i PIN (skrót Argon2)."""

    __tablename__ = "dashboards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80), default="Mój pulpit")
    is_default: Mapped[bool] = mapped_column(Boolean, default=True)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    layout: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    public_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)  # None = pulpit prywatny
    public_token: Mapped[str | None] = mapped_column(EncryptedText)  # zaszyfrowany – crypto.py
    public_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    public_pin_hash: Mapped[str | None] = mapped_column(String(255))
    # Odświeżanie, zakres wykresów, ukrywanie adresów (api/public.py: PublicOptions)
    public_options: Mapped[dict | None] = mapped_column(JSONB)


class UserPreference(Base):
    """Drobne ustawienia konta (np. odświeżanie) jako JSON, jedna sekcja = jeden klucz."""

    __tablename__ = "user_preferences"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AppSetting(Base):
    """Ustawienia całej instalacji (nie konta), np. automatyczne sprawdzanie aktualizacji. Jeden klucz = jeden JSON."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# --- metryki (hypertables) --------------------------------------------------


class InterfaceMetric(Base):
    __tablename__ = "interface_metrics"
    # Wykres i ostatni odczyt jednego obiektu (od 0.65.4; klucz główny zaczyna się od czasu)
    __table_args__ = (Index("ix_interface_metrics_interface_time", "interface_id", "time"),)

    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    interface_id: Mapped[int] = mapped_column(
        ForeignKey("interfaces.id", ondelete="CASCADE"), primary_key=True
    )
    in_bps: Mapped[float | None] = mapped_column(Float)
    out_bps: Mapped[float | None] = mapped_column(Float)
    in_errors: Mapped[int | None] = mapped_column(BigInteger)
    out_errors: Mapped[int | None] = mapped_column(BigInteger)
    in_discards: Mapped[int | None] = mapped_column(BigInteger)
    out_discards: Mapped[int | None] = mapped_column(BigInteger)
    oper_up: Mapped[bool | None] = mapped_column(Boolean)


class DeviceMetric(Base):
    __tablename__ = "device_metrics"
    # Wykres i ostatni odczyt jednego obiektu (od 0.65.4; klucz główny zaczyna się od czasu)
    __table_args__ = (Index("ix_device_metrics_device_time", "device_id", "time"),)

    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    device_id: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True
    )
    reachable: Mapped[bool] = mapped_column(Boolean)
    poll_ms: Mapped[float | None] = mapped_column(Float)
    uptime_s: Mapped[float | None] = mapped_column(Float)
    cpu_percent: Mapped[float | None] = mapped_column(Float)
    mem_used_percent: Mapped[float | None] = mapped_column(Float)
    load1: Mapped[float | None] = mapped_column(Float)


class WifiMetric(Base):
    __tablename__ = "wifi_metrics"
    # Wykres i ostatni odczyt jednego obiektu (od 0.65.4; klucz główny zaczyna się od czasu)
    __table_args__ = (Index("ix_wifi_metrics_wifi_time", "wifi_id", "time"),)

    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    wifi_id: Mapped[int] = mapped_column(
        ForeignKey("wifi_networks.id", ondelete="CASCADE"), primary_key=True
    )
    clients: Mapped[int | None] = mapped_column(Integer)
    rx_bps: Mapped[float | None] = mapped_column(Float)
    tx_bps: Mapped[float | None] = mapped_column(Float)


class Controller(Base):
    """Kontroler UniFi Network (API z kluczem): PoE na portach i klienci sieci, których SNMP nie podaje."""

    __tablename__ = "controllers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    host: Mapped[str] = mapped_column(String(255), unique=True)
    port: Mapped[int] = mapped_column(Integer, default=443)
    api_key: Mapped[str] = mapped_column(EncryptedText)  # zaszyfrowany – crypto.py
    site: Mapped[str] = mapped_column(String(64), default="default")
    verify_tls: Mapped[bool] = mapped_column(Boolean, default=False)  # kontrolery mają zwykle certyfikat samopodpisany
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    app_version: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="unknown")  # up | down | unknown
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UnifiApiDevice(Base):
    """Urządzenie kontrolera UniFi spoza SNMP (np. USW Flex), czytane z oficjalnego API (od 0.52.0).

    `device_id` = urządzenie UplinkView z `driver = "unifi_api"`. Po usunięciu urządzenia w panelu (albo dodaniu go
    przez SNMP) zostaje wiersz z `device_id = NULL` – kolektor nie zakłada go wtedy ponownie."""

    __tablename__ = "unifi_api_devices"

    controller_id: Mapped[int] = mapped_column(ForeignKey("controllers.id", ondelete="CASCADE"), primary_key=True)
    mac: Mapped[str] = mapped_column(String(17), primary_key=True)
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id", ondelete="SET NULL"), unique=True)
    official_id: Mapped[str | None] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class NetworkClient(Base):
    """Klient sieci (WiFi albo po kablu) widziany przez kontroler; zdjęcie stanu z ostatniego odczytu."""

    __tablename__ = "network_clients"

    controller_id: Mapped[int] = mapped_column(ForeignKey("controllers.id", ondelete="CASCADE"), primary_key=True)
    mac: Mapped[str] = mapped_column(String(17), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(255))
    ip: Mapped[str | None] = mapped_column(String(45))
    is_wired: Mapped[bool] = mapped_column(Boolean, default=False)
    is_guest: Mapped[bool] = mapped_column(Boolean, default=False)
    essid: Mapped[str | None] = mapped_column(String(64))
    radio: Mapped[str | None] = mapped_column(String(8))
    signal_dbm: Mapped[int | None] = mapped_column(Integer)
    tx_rate_kbps: Mapped[int | None] = mapped_column(Integer)
    rx_rate_kbps: Mapped[int | None] = mapped_column(Integer)
    # Urządzenie UplinkView (AP albo switch), do którego klient jest podłączony, i jego port
    uplink_device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id", ondelete="SET NULL"), index=True)
    uplink_name: Mapped[str | None] = mapped_column(String(128))
    uplink_port: Mapped[int | None] = mapped_column(Integer)
    connected_s: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class KnownClient(Base):
    """Klient, którego kontroler kiedyś widział – zostaje po rozłączeniu (strona klienta, pierwsze i ostatnie widzenie)."""

    __tablename__ = "known_clients"

    mac: Mapped[str] = mapped_column(String(17), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(255))
    ip: Mapped[str | None] = mapped_column(String(45))
    is_wired: Mapped[bool] = mapped_column(Boolean, default=False)
    is_guest: Mapped[bool] = mapped_column(Boolean, default=False)
    essid: Mapped[str | None] = mapped_column(String(64))
    uplink_device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id", ondelete="SET NULL"))
    uplink_name: Mapped[str | None] = mapped_column(String(128))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ClientMetric(Base):
    """Stan klienta w cyklu kolektora UniFi: sygnał, prędkość łącza i miejsce podłączenia (historia, przejścia między AP)."""

    __tablename__ = "client_metrics"
    __table_args__ = (Index("ix_client_metrics_mac_time", "mac", "time"),)

    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    mac: Mapped[str] = mapped_column(String(17), primary_key=True)
    is_wired: Mapped[bool] = mapped_column(Boolean, default=False)
    signal_dbm: Mapped[int | None] = mapped_column(Integer)
    tx_rate_kbps: Mapped[int | None] = mapped_column(Integer)
    rx_rate_kbps: Mapped[int | None] = mapped_column(Integer)
    uplink_device_id: Mapped[int | None] = mapped_column(Integer)  # bez klucza obcego – historia zostaje po usunięciu urządzenia
    uplink_name: Mapped[str | None] = mapped_column(String(128))
    uplink_port: Mapped[int | None] = mapped_column(Integer)
    essid: Mapped[str | None] = mapped_column(String(64))
    radio: Mapped[str | None] = mapped_column(String(8))


class TopologyLink(Base):
    """Połączenie z tabeli LLDP urządzenia: port lokalny → sąsiad (zdjęcie stanu z ostatniego odczytu)."""

    __tablename__ = "topology_links"

    controller_id: Mapped[int] = mapped_column(ForeignKey("controllers.id", ondelete="CASCADE"), primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True)
    local_port_idx: Mapped[int] = mapped_column(Integer, primary_key=True)
    remote_mac: Mapped[str] = mapped_column(String(17), primary_key=True)
    local_mac: Mapped[str] = mapped_column(String(17))  # MAC urządzenia lokalnego (do rozpoznania sąsiada)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AlertRule(Base):
    """Reguła alertu: rodzaj (urządzenie offline, port down, próg metryki), próg, czas trwania i ważność."""

    __tablename__ = "alert_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    kind: Mapped[str] = mapped_column(String(24))  # device_offline | port_down | metric
    metric: Mapped[str | None] = mapped_column(String(32))  # tylko dla kind=metric
    op: Mapped[str | None] = mapped_column(String(2))  # > | <
    threshold: Mapped[float | None] = mapped_column(Float)
    duration_s: Mapped[int] = mapped_column(Integer, default=0)  # warunek musi trwać co najmniej tyle
    severity: Mapped[str] = mapped_column(String(10), default="warning")  # info | warning | critical
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)  # None = wszystkie
    # Reguły z agenta: nazwa kontenera, usługi albo dysku (wzorzec z * i ?); None = wszystkie
    match: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NotificationChannel(Base):
    """Kanał powiadomień o alertach poza panelem: webhook, ntfy albo e-mail (SMTP).
    Adres, token ntfy i hasło SMTP to sekrety, więc API ich nie zwraca."""

    __tablename__ = "notification_channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(16), default="webhook")  # webhook | ntfy | email
    url: Mapped[str | None] = mapped_column(EncryptedText)  # webhook i ntfy (adres tematu); zaszyfrowany – crypto.py
    secret: Mapped[str | None] = mapped_column(EncryptedText)  # token ntfy albo hasło SMTP
    config: Mapped[dict] = mapped_column(JSONB, default=dict)  # e-mail: host, port, security, username, sender, recipients
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    min_severity: Mapped[str] = mapped_column(String(10), default="warning")  # info | warning | critical
    notify_resolved: Mapped[bool] = mapped_column(Boolean, default=True)
    # Ciche godziny („22:00”–„07:00”, strefa TZ serwera): przechodzą tylko krytyczne (quiet_critical), reszta
    # czeka w quiet_backlog i po ciszy przychodzi jedną wiadomością zbiorczą
    quiet_from: Mapped[str | None] = mapped_column(String(5))
    quiet_to: Mapped[str | None] = mapped_column(String(5))
    quiet_critical: Mapped[bool] = mapped_column(Boolean, default=True)
    quiet_backlog: Mapped[list | None] = mapped_column(JSONB)
    last_status: Mapped[str | None] = mapped_column(String(8))  # ok | error
    last_error: Mapped[str | None] = mapped_column(Text)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Alert(Base):
    """Zdarzenie alertu: wyzwolone → (potwierdzone) → zakończone. Historia zostaje po usunięciu reguły."""

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("alert_rules.id", ondelete="SET NULL"), index=True)
    subject: Mapped[str] = mapped_column(String(64))  # "d3" urządzenie, "i15" interfejs, "wan" – o kogo chodzi
    state: Mapped[str] = mapped_column(String(10), default="firing", index=True)  # firing | resolved
    severity: Mapped[str] = mapped_column(String(10))
    title: Mapped[str] = mapped_column(String(255))
    message: Mapped[str | None] = mapped_column(Text)
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id", ondelete="SET NULL"), index=True)
    value: Mapped[float | None] = mapped_column(Float)  # ostatnia wartość
    peak: Mapped[float | None] = mapped_column(Float)  # skrajna wartość w trakcie alertu
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acked_by: Mapped[str | None] = mapped_column(String(64))
    # Bez powiadomienia, bo urządzenie wyżej w topologii też nie odpowiada (jedna wiadomość o przyczynie)
    muted: Mapped[bool] = mapped_column(Boolean, default=False)
    # Zaczął się w oknie serwisowym (od 0.60.0): bez powiadomienia; jeśli trwa po oknie – powiadomienie wtedy
    maintenance: Mapped[bool] = mapped_column(Boolean, default=False)


class DiskMetric(Base):
    """Zajętość partycji serwera (jedna próbka na punkt montowania i cykl)."""

    __tablename__ = "disk_metrics"
    # Wykres i ostatni odczyt jednego obiektu (od 0.65.4; klucz główny zaczyna się od czasu)
    __table_args__ = (Index("ix_disk_metrics_device_time", "device_id", "time"),)

    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True)
    mount: Mapped[str] = mapped_column(String(255), primary_key=True)
    total_bytes: Mapped[int] = mapped_column(BigInteger)
    used_bytes: Mapped[int] = mapped_column(BigInteger)


class ServerMetric(Base):
    """Dodatkowe metryki serwera Linux, których nie ma w `device_metrics` (swap, liczba procesów)."""

    __tablename__ = "server_metrics"
    # Wykres i ostatni odczyt jednego obiektu (od 0.65.4; klucz główny zaczyna się od czasu)
    __table_args__ = (Index("ix_server_metrics_device_time", "device_id", "time"),)

    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True)
    swap_used_percent: Mapped[float | None] = mapped_column(Float)
    processes: Mapped[int | None] = mapped_column(Integer)


class PoePortMetric(Base):
    """PoE na porcie switcha (moc w W). Tylko porty z PoE; port_idx jak w kontrolerze (1, 2, …)."""

    __tablename__ = "poe_port_metrics"
    # Wykres i ostatni odczyt jednego obiektu (od 0.65.4; klucz główny zaczyna się od czasu)
    __table_args__ = (Index("ix_poe_port_metrics_device_port_time", "device_id", "port_idx", "time"),)

    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True)
    port_idx: Mapped[int] = mapped_column(Integer, primary_key=True)
    power_w: Mapped[float | None] = mapped_column(Float)
    voltage_v: Mapped[float | None] = mapped_column(Float)
    current_ma: Mapped[float | None] = mapped_column(Float)
    poe_mode: Mapped[str | None] = mapped_column(String(16))  # auto | off | passthrough …
    poe_class: Mapped[str | None] = mapped_column(String(16))
    delivering: Mapped[bool | None] = mapped_column(Boolean)


class SystemMetric(Base):
    """Stan serwera, na którym działa UplinkView (jedna próbka na cykl kolektora)."""

    __tablename__ = "system_metrics"

    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    cpu_percent: Mapped[float | None] = mapped_column(Float)
    load1: Mapped[float | None] = mapped_column(Float)
    load5: Mapped[float | None] = mapped_column(Float)
    load15: Mapped[float | None] = mapped_column(Float)
    mem_used_percent: Mapped[float | None] = mapped_column(Float)
    mem_total_bytes: Mapped[int | None] = mapped_column(BigInteger)
    swap_used_percent: Mapped[float | None] = mapped_column(Float)
    disk_used_percent: Mapped[float | None] = mapped_column(Float)
    disk_free_bytes: Mapped[int | None] = mapped_column(BigInteger)
    disk_total_bytes: Mapped[int | None] = mapped_column(BigInteger)
    uptime_s: Mapped[float | None] = mapped_column(Float)
    temp_c: Mapped[float | None] = mapped_column(Float)
    db_size_bytes: Mapped[int | None] = mapped_column(BigInteger)


class PoeBudgetMetric(Base):
    """Zużycie i limit mocy PoE całego switcha."""

    __tablename__ = "poe_budget_metrics"

    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True)
    used_w: Mapped[float | None] = mapped_column(Float)
    max_w: Mapped[float | None] = mapped_column(Float)


class ProxmoxServer(Base):
    """Proxmox VE (pojedynczy węzeł albo klaster) z tokenem API tylko do odczytu. Sekret tokenu jest zaszyfrowany."""

    __tablename__ = "proxmox_servers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    host: Mapped[str] = mapped_column(String(255), unique=True)
    port: Mapped[int] = mapped_column(Integer, default=8006)
    token_id: Mapped[str] = mapped_column(String(255))  # np. netpulse@pve!monitor
    token_secret: Mapped[str] = mapped_column(EncryptedText)
    verify_tls: Mapped[bool] = mapped_column(Boolean, default=False)  # Proxmox ma zwykle certyfikat samopodpisany
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(16), default="unknown")  # up | down | unknown
    version: Mapped[str | None] = mapped_column(String(32))
    cluster_name: Mapped[str | None] = mapped_column(String(128))
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProxmoxNode(Base):
    """Węzeł Proxmox = urządzenie UplinkView (`devices.driver = "proxmox"`, rodzaj „Serwer”): karta, alerty, wykresy."""

    __tablename__ = "proxmox_nodes"

    server_id: Mapped[int] = mapped_column(ForeignKey("proxmox_servers.id", ondelete="CASCADE"), primary_key=True)
    node: Mapped[str] = mapped_column(String(64), primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), unique=True)
    ip: Mapped[str | None] = mapped_column(String(64))
    online: Mapped[bool] = mapped_column(Boolean, default=True)
    # Ostatnie zakończone zadanie kopii (vzdump) na węźle
    backup_status: Mapped[str | None] = mapped_column(String(255))  # "OK" albo opis błędu
    backup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProxmoxGuest(Base):
    """Maszyna wirtualna (qemu) albo kontener (lxc) – zdjęcie stanu z ostatniego odczytu."""

    __tablename__ = "proxmox_guests"

    server_id: Mapped[int] = mapped_column(ForeignKey("proxmox_servers.id", ondelete="CASCADE"), primary_key=True)
    vmid: Mapped[int] = mapped_column(Integer, primary_key=True)
    node: Mapped[str] = mapped_column(String(64))
    type: Mapped[str] = mapped_column(String(8))  # qemu | lxc
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16))
    template: Mapped[bool] = mapped_column(Boolean, default=False)
    tags: Mapped[str | None] = mapped_column(String(255))
    cpus: Mapped[int | None] = mapped_column(Integer)
    cpu_percent: Mapped[float | None] = mapped_column(Float)
    mem_used: Mapped[int | None] = mapped_column(BigInteger)
    mem_total: Mapped[int | None] = mapped_column(BigInteger)
    disk_used: Mapped[int | None] = mapped_column(BigInteger)
    disk_total: Mapped[int | None] = mapped_column(BigInteger)
    uptime_s: Mapped[int | None] = mapped_column(BigInteger)
    last_backup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProxmoxStorage(Base):
    """Magazyn (storage) na węźle; współdzielony (NFS, Ceph…) zapisujemy raz – przy pierwszym węźle."""

    __tablename__ = "proxmox_storages"

    server_id: Mapped[int] = mapped_column(ForeignKey("proxmox_servers.id", ondelete="CASCADE"), primary_key=True)
    node: Mapped[str] = mapped_column(String(64), primary_key=True)
    storage: Mapped[str] = mapped_column(String(128), primary_key=True)
    type: Mapped[str | None] = mapped_column(String(32))
    shared: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    content: Mapped[str | None] = mapped_column(String(255))
    used_bytes: Mapped[int | None] = mapped_column(BigInteger)
    total_bytes: Mapped[int | None] = mapped_column(BigInteger)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Agent(Base):
    """Agent UplinkView na serwerze Linux: wysyła metryki do API (push) z tokenem. Jeden agent = jedno urządzenie
    (`devices.driver = "agent"`), którego kolektor nie odpytuje przez SNMP. W bazie tylko skrót SHA-256 tokenu."""

    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), unique=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    token_hint: Mapped[str] = mapped_column(String(8))  # ostatnie znaki tokenu – do rozpoznania w panelu
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_ip: Mapped[str | None] = mapped_column(String(64))
    agent_version: Mapped[str | None] = mapped_column(String(32))
    hostname: Mapped[str | None] = mapped_column(String(255))
    # Zdjęcie stanu z ostatniego raportu: system, kontenery, usługi, temperatury, SMART (do panelu)
    inventory: Mapped[dict | None] = mapped_column(JSONB)


class OpnsenseApi(Base):
    """Klucz REST API OPNsense przy urządzeniu (od 0.81.0): bramy z pomiarem, wersja, usługi, DHCP i ARP.

    Urządzenie zostaje odpytywane przez SNMP (driver `opnsense`), API tylko dokłada dane. Adres = `devices.host`.
    Klucz i sekret są zaszyfrowane; `snapshot` = ostatni odczyt do panelu (opnsense.Snapshot.as_dict)."""

    __tablename__ = "opnsense_apis"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), unique=True)
    port: Mapped[int] = mapped_column(Integer, default=443)
    api_key: Mapped[str] = mapped_column(EncryptedText)
    api_secret: Mapped[str] = mapped_column(EncryptedText)
    verify_tls: Mapped[bool] = mapped_column(Boolean, default=False)  # OPNsense ma zwykle certyfikat samopodpisany
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(16), default="unknown")  # up | down | unknown
    version: Mapped[str | None] = mapped_column(String(32))
    latest_version: Mapped[str | None] = mapped_column(String(32))
    snapshot: Mapped[dict | None] = mapped_column(JSONB)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Metric(Base):
    """Ogólna metryka: nazwa (np. `container_up`), klucz (np. nazwa kontenera, "" gdy jedna wartość) i wartość."""

    __tablename__ = "metrics"
    __table_args__ = (Index("ix_metrics_device_name_time", "device_id", "name", "time"),)

    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    key: Mapped[str] = mapped_column(String(255), primary_key=True, default="")
    value: Mapped[float] = mapped_column(Float)


class WanLink(Base):
    """Łącze WAN routera: port (interfejs) z nazwą i kolejnością (1 = WAN 1, 2 = WAN 2 …) oraz bieżący stan.

    Stan liczy kolektor SNMP co cykl (wan.py); kolektor UniFi dopisuje, co o łączu wie kontroler (`ctrl_*`)."""

    __tablename__ = "wan_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    interface_id: Mapped[int] = mapped_column(ForeignKey("interfaces.id", ondelete="CASCADE"), unique=True)
    position: Mapped[int] = mapped_column(Integer, default=1)
    name: Mapped[str] = mapped_column(String(64))
    # Stan z ostatniego cyklu: active (ruch idzie tym łączem) | standby (sprawne, bez ruchu) | down | unknown
    state: Mapped[str] = mapped_column(String(10), default="unknown")
    state_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str | None] = mapped_column(String(10))  # controller | traffic – skąd wiadomo, które łącze jest aktywne
    # Co mówi kontroler UniFi (None = nie wie albo moduł wyłączony); ważne, gdy ctrl_at jest świeże
    ctrl_up: Mapped[bool | None] = mapped_column(Boolean)
    ctrl_active: Mapped[bool | None] = mapped_column(Boolean)
    ctrl_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WanLinkMetric(Base):
    """Stan łącza WAN w cyklu kolektora: sprawne (`up`), w użyciu (`active`) i ruch – podstawa wykresu i SLA."""

    __tablename__ = "wan_link_metrics"
    __table_args__ = (Index("ix_wan_link_metrics_link_time", "wan_link_id", "time"),)

    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    wan_link_id: Mapped[int] = mapped_column(ForeignKey("wan_links.id", ondelete="CASCADE"), primary_key=True)
    up: Mapped[bool] = mapped_column(Boolean)
    active: Mapped[bool] = mapped_column(Boolean)
    in_bps: Mapped[float | None] = mapped_column(Float)
    out_bps: Mapped[float | None] = mapped_column(Float)


class Check(Base):
    """Sprawdzenie dostępności (od 0.30.0): ping (opóźnienie, utrata pakietów, jitter), HTTP(S) (kod odpowiedzi,
    słowo w treści, ważność certyfikatu) albo port TCP. Wykonuje je checks_collector co `interval_s`."""

    __tablename__ = "checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(8))  # ping | http | tcp | dns
    target: Mapped[str] = mapped_column(String(512))  # host (ping, tcp) albo adres URL (http)
    port: Mapped[int | None] = mapped_column(Integer)  # tylko tcp
    interval_s: Mapped[int] = mapped_column(Integer, default=60)
    timeout_s: Mapped[float] = mapped_column(Float, default=5.0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    expect_status: Mapped[str | None] = mapped_column(String(32))  # http: np. „200-399” albo „200,204”; puste = 200–399
    keyword: Mapped[str | None] = mapped_column(String(255))  # http: tekst, który musi być w odpowiedzi
    verify_tls: Mapped[bool] = mapped_column(Boolean, default=True)
    # DNS (od 0.64.0): typ rekordu i serwer (puste = serwer systemu); `keyword` = oczekiwana odpowiedź
    dns_type: Mapped[str | None] = mapped_column(String(8))
    dns_server: Mapped[str | None] = mapped_column(String(255))
    # Stan z ostatniego sprawdzenia: up | down | unknown
    status: Mapped[str] = mapped_column(String(10), default="unknown")
    status_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(255))
    last_latency_ms: Mapped[float | None] = mapped_column(Float)
    last_answer: Mapped[str | None] = mapped_column(String(255))  # DNS: ostatnia odpowiedź
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def stale(self) -> bool:
        """Sprawdzenie dawno się nie wykonało (kolektor stoi) – zapisany stan jest nieaktualny (freshness.py)."""
        return self.enabled and self.status != "unknown" and is_stale(self.last_checked_at, interval_s=self.interval_s)

    @property
    def live_status(self) -> str:
        return "unknown" if self.stale else self.status


class CheckMetric(Base):
    """Wynik sprawdzenia: dostępne, opóźnienie (ping: średnia z serii), utrata pakietów i jitter (ping),
    kod HTTP i dni do wygaśnięcia certyfikatu (https)."""

    __tablename__ = "check_metrics"
    __table_args__ = (Index("ix_check_metrics_check_time", "check_id", "time"),)

    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    check_id: Mapped[int] = mapped_column(ForeignKey("checks.id", ondelete="CASCADE"), primary_key=True)
    up: Mapped[bool] = mapped_column(Boolean)
    latency_ms: Mapped[float | None] = mapped_column(Float)
    loss_percent: Mapped[float | None] = mapped_column(Float)
    jitter_ms: Mapped[float | None] = mapped_column(Float)
    status_code: Mapped[int | None] = mapped_column(Integer)
    cert_days: Mapped[float | None] = mapped_column(Float)


HYPERTABLES = ("interface_metrics", "device_metrics", "wifi_metrics", "poe_port_metrics", "poe_budget_metrics", "system_metrics", "disk_metrics", "server_metrics", "metrics", "wan_link_metrics", "client_metrics", "check_metrics")


class MaintenanceWindow(Base):
    """Okno serwisowe (od 0.60.0): planowane prace bez powiadomień, czas okna nie liczy się do dostępności.
    Jednorazowe (`once`: `starts_at`–`ends_at`) albo co tydzień (`weekly`: dni `days` 0 = pon. … 6 = niedz.,
    od `time_from` przez `duration_min`, strefa TZ serwera). `device_ids` puste = wszystkie urządzenia i sprawdzenia.
    Logika: maintenance.py."""

    __tablename__ = "maintenance_windows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    device_ids: Mapped[list | None] = mapped_column(JSONB)
    kind: Mapped[str] = mapped_column(String(8))  # once | weekly
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    days: Mapped[list | None] = mapped_column(JSONB)
    time_from: Mapped[str | None] = mapped_column(String(5))
    duration_min: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditEntry(Base):
    """Dziennik audytu (od 0.61.0): logowania, nieudane logowania, zmiany konfiguracji w API (metoda, trasa, kod
    odpowiedzi – bez treści żądania, więc bez sekretów), zarządzanie kontami. Bez klucza obcego do users – wpis zostaje
    po usunięciu konta. Zapis: netpulse/audit.py."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    user_id: Mapped[int | None] = mapped_column(Integer)
    username: Mapped[str | None] = mapped_column(String(64))
    ip: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(96))  # login | login_failed | logout | password | "PATCH /api/devices/{device_id}" …
    target: Mapped[str | None] = mapped_column(String(255))  # konkretna ścieżka, np. /api/devices/3
    status: Mapped[int | None] = mapped_column(Integer)  # kod odpowiedzi HTTP
    detail: Mapped[str | None] = mapped_column(String(255))
