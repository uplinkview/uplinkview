"""Schematy wejścia/wyjścia API (Pydantic v2)."""

from __future__ import annotations

import ipaddress
import re
from datetime import datetime
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

SnmpVersion = Literal["1", "2c", "3"]
AuthProto = Literal["MD5", "SHA", "SHA224", "SHA256", "SHA384", "SHA512"]
PrivProto = Literal["DES", "AES", "AES192", "AES256"]
DriverName = Literal["auto", "generic", "unifi", "linux", "mikrotik", "omada", "opnsense"]

_HOSTNAME_RE = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$")


def _check_host(value: str) -> str:
    value = value.strip()
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        pass
    if not _HOSTNAME_RE.match(value):
        raise ValueError("Podaj adres IP albo nazwę hosta")
    return value


def credential_error(
    snmp_version: str,
    community: str | None,
    v3_username: str | None,
    v3_auth_protocol: str | None,
    v3_auth_key: str | None,
    v3_priv_protocol: str | None,
    v3_priv_key: str | None,
) -> str | None:
    """Sprawdza spójność danych SNMP. Zwraca opis błędu albo None."""
    if snmp_version != "3":
        return None if community else "Dla SNMP v1/v2c podaj community"
    if not v3_username:
        return "Dla SNMPv3 podaj nazwę użytkownika (v3_username)"
    if bool(v3_auth_protocol) != bool(v3_auth_key):
        return "SNMPv3: protokół i klucz uwierzytelniania podaje się razem"
    if bool(v3_priv_protocol) != bool(v3_priv_key):
        return "SNMPv3: protokół i klucz szyfrowania podaje się razem"
    if v3_priv_protocol and not v3_auth_protocol:
        return "SNMPv3: szyfrowanie wymaga uwierzytelniania (authPriv)"
    for key in (v3_auth_key, v3_priv_key):
        if key is not None and len(key) < 8:
            return "SNMPv3: klucze muszą mieć co najmniej 8 znaków"
    return None


# --- urządzenia ------------------------------------------------------------


class SnmpTarget(BaseModel):
    """Adres i dane SNMP urządzenia (wejście)."""

    host: str = Field(max_length=255)
    port: int = Field(161, ge=1, le=65535)
    driver: DriverName = "auto"
    snmp_version: SnmpVersion = "2c"
    community: str | None = Field("public", max_length=255)
    v3_username: str | None = Field(None, max_length=128)
    v3_auth_protocol: AuthProto | None = None
    v3_auth_key: str | None = Field(None, max_length=255)
    v3_priv_protocol: PrivProto | None = None
    v3_priv_key: str | None = Field(None, max_length=255)
    v3_context: str | None = Field(None, max_length=128)

    @field_validator("host")
    @classmethod
    def _host(cls, v: str) -> str:
        return _check_host(v)

    def credential_error(self) -> str | None:
        return credential_error(
            self.snmp_version,
            self.community,
            self.v3_username,
            self.v3_auth_protocol,
            self.v3_auth_key,
            self.v3_priv_protocol,
            self.v3_priv_key,
        )


class DeviceCreate(SnmpTarget):
    name: str = Field(min_length=1, max_length=128)
    enabled: bool = True


class DeviceUpdate(BaseModel):
    """Częściowa zmiana – pominięte pola zostają bez zmian (także sekrety)."""

    name: str | None = Field(None, min_length=1, max_length=128)
    enabled: bool | None = None
    host: str | None = Field(None, max_length=255)
    port: int | None = Field(None, ge=1, le=65535)
    driver: DriverName | None = None
    snmp_version: SnmpVersion | None = None
    community: str | None = Field(None, max_length=255)
    v3_username: str | None = Field(None, max_length=128)
    v3_auth_protocol: AuthProto | None = None
    v3_auth_key: str | None = Field(None, max_length=255)
    v3_priv_protocol: PrivProto | None = None
    v3_priv_key: str | None = Field(None, max_length=255)
    v3_context: str | None = Field(None, max_length=128)

    @field_validator("host")
    @classmethod
    def _host(cls, v: str | None) -> str | None:
        return None if v is None else _check_host(v)


class DeviceOut(BaseModel):
    """Urządzenie bez sekretów (community i klucze SNMPv3 nie wychodzą z API)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    host: str
    port: int
    enabled: bool
    driver: str
    detected_driver: str | None
    snmp_version: str
    v3_username: str | None
    v3_auth_protocol: str | None
    v3_priv_protocol: str | None
    v3_context: str | None
    kind: str
    vendor: str | None
    model: str | None
    firmware: str | None
    sys_name: str | None
    uptime_s: float | None
    # Status do pokazania: `unknown`, gdy kolektor dawno nie wydał werdyktu (freshness.py); zapisany – w `last_status`
    status: str = Field(validation_alias=AliasChoices("live_status", "status"))
    stale: bool = False
    # Trwa okno serwisowe obejmujące urządzenie (od 0.60.0, api/maintenance.py) – bez powiadomień
    maintenance: bool = False
    # Dane drivera potwierdzone na prawdziwym sprzęcie: verified | partial | test (od 0.64.0, verification.py)
    verification: str = "verified"
    last_status: str | None = Field(None, validation_alias=AliasChoices("last_status", "status"))
    last_polled_at: datetime | None
    last_ok_at: datetime | None
    last_error: str | None
    created_at: datetime
    # SNMP v1/v2c z community „public” albo „private” – samo community nie wychodzi z API
    default_community: bool = Field(False, validation_alias=AliasChoices("default_community", "uses_default_community"))


class ProbeInterface(BaseModel):
    if_index: int
    name: str
    label: str
    alias: str | None
    role: str
    hidden: bool
    oper_status: str
    speed_mbps: int | None


class ProbeWifi(BaseModel):
    ssid: str
    radio: str | None
    channel: int | None
    clients: int | None
    hidden: bool


class ProbeOut(BaseModel):
    driver: str
    name: str | None
    vendor: str | None
    model: str | None
    firmware: str | None
    kind: str
    uptime_s: float | None
    interfaces: list[ProbeInterface]
    wifi: list[ProbeWifi]


class InterfaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    if_index: int
    name: str
    label: str
    alias: str | None
    role: str
    hidden: bool
    mac: str | None
    admin_up: bool | None
    oper_status: str
    speed_mbps: int | None
    in_bps: float | None = None
    out_bps: float | None = None


class InterfaceDetailOut(InterfaceOut):
    """Port z urządzeniem, do którego należy (strona szczegółów portu)."""

    device_id: int
    device_name: str
    device_kind: str
    last_seen_at: datetime | None
    # Numer portu PoE w kontrolerze UniFi (switch UniFi nazywa porty 0/1…0/8); None = port bez PoE z kontrolera
    poe_port_idx: int | None = None


class SensorOut(BaseModel):
    key: str  # nazwa czujnika z urządzenia, np. „cpu-temperature”
    metric: str  # temp_c | fan_rpm | voltage_v | current_a | power_w | sensor_state
    value: float


class PoeOut(BaseModel):
    port: str
    state: int | None  # mtxrPOEStatus: 1 wyłączony, 2 czeka na odbiornik, 3 zasila, 4+ błąd
    power_w: float | None
    voltage_v: float | None


class SfpOut(BaseModel):
    port: str
    rx_dbm: float | None
    tx_dbm: float | None
    temp_c: float | None
    voltage_v: float | None
    rx_loss: bool | None
    tx_fault: bool | None


class SensorsOut(BaseModel):
    """Ostatnie wartości czujników, PoE i SFP urządzenia SNMP (tabela `metrics`, ostatnie 10 minut)."""

    sensors: list[SensorOut]
    poe: list[PoeOut]
    sfp: list[SfpOut]


class WifiOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    key: str
    ssid: str
    radio: str | None
    channel: int | None
    bssid: str | None
    hidden: bool
    clients: int | None


class Point(BaseModel):
    time: datetime
    values: dict[str, float | None]


# --- konta -----------------------------------------------------------------


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    is_admin: bool
    # admin | operator | viewer (od 0.61.0)
    role: str = "admin"
    created_at: datetime
    last_login_at: datetime | None
    # Logowanie dwuskładnikowe włączone (od 0.63.0)
    totp_enabled: bool = False


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class LoginBody(Credentials):
    # Kod z aplikacji uwierzytelniającej albo kod zapasowy – gdy konto ma włączone logowanie dwuskładnikowe
    code: str | None = Field(None, max_length=32)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class AuthStatus(BaseModel):
    setup_required: bool
    authenticated: bool
    user: UserOut | None
    version: str | None  # tylko dla zalogowanych
