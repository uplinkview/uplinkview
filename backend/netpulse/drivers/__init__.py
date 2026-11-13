"""Rejestr driverów i automatyczny wybór drivera dla urządzenia."""

from __future__ import annotations

from ..snmp import SnmpClient
from .base import (
    DeviceHealth,
    DiskSample,
    Driver,
    InterfaceSample,
    MetricSample,
    PollResult,
    ServerSample,
    SystemInfo,
    WifiSample,
)
from .generic import GenericDriver, read_system
from .linux import LinuxDriver
from .mikrotik import MikrotikDriver
from .omada import OmadaDriver
from .opnsense import OpnsenseDriver
from .unifi import UnifiDriver

DRIVERS: dict[str, type[GenericDriver]] = {
    GenericDriver.name: GenericDriver,
    UnifiDriver.name: UnifiDriver,
    LinuxDriver.name: LinuxDriver,
    MikrotikDriver.name: MikrotikDriver,
    OmadaDriver.name: OmadaDriver,
    OpnsenseDriver.name: OpnsenseDriver,
}


def detect_driver(system: SystemInfo) -> type[GenericDriver]:
    return max(DRIVERS.values(), key=lambda d: d.match(system))


async def poll_device(client: SnmpClient, driver_name: str = "auto") -> PollResult:
    """Odczytuje system, wybiera driver (gdy `auto`) i wykonuje pełny odczyt."""
    system = await read_system(client)
    if system.descr is None and system.name is None and system.uptime_s is None:
        from ..snmp import SnmpError

        raise SnmpError("Urządzenie nie zwróciło danych SNMPv2-MIB::system")
    if driver_name == "auto" or driver_name not in DRIVERS:
        driver_cls = detect_driver(system)
    else:
        driver_cls = DRIVERS[driver_name]
    return await driver_cls().poll(client, system)


__all__ = [
    "DRIVERS",
    "DeviceHealth",
    "DiskSample",
    "Driver",
    "GenericDriver",
    "InterfaceSample",
    "LinuxDriver",
    "MetricSample",
    "MikrotikDriver",
    "OmadaDriver",
    "OpnsenseDriver",
    "PollResult",
    "ServerSample",
    "SystemInfo",
    "UnifiDriver",
    "WifiSample",
    "detect_driver",
    "poll_device",
]
