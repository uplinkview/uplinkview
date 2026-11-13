"""Driver OPNsense (FreeBSD z wtyczką `os-net-snmp`): router z WAN-em rozpoznanym po trasie domyślnej.

OPNsense zgłasza się jak zwykły FreeBSD z net-snmp (`sysObjectID` 1.3.6.1.4.1.8072.3.2.8) – bez własnego MIB-u
i bez opisów portów (`ifAlias` pusty). Rozpoznajemy go po gałęzi jądra w `sysDescr` (`stable/26.7` = seria OPNsense;
czysty FreeBSD ma `releng/15.1` albo `stable/15`) albo po słowie „OPNsense” w nazwie hosta.

Na bazie drivera Linux (ten sam agent net-snmp: IF-MIB, UCD-SNMP-MIB, HOST-RESOURCES-MIB). Różnice:
- `kind = gateway`, model „OPNsense”, wersja = seria z jądra (pełnego numeru, np. 26.7.3, agent nie podaje),
- WAN = interfejs trasy domyślnej (`ipRouteIfIndex.0.0.0.0`) – jeden odczyt, bez czytania tablicy tras,
- pozostałe porty Ethernet i sieci VLAN = LAN, tunele (WireGuard, OpenVPN, IPsec) = VPN,
- ukryte interfejsy techniczne zapory: `lo0`, `enc0`, `pflog0`, `pfsync0`,
- dysk: tylko `/` (zbiory ZFS dzielą jedną pulę – każdy byłby osobnym „dyskiem” o tej samej wolnej przestrzeni).

Sprawdzone 13.11.2026 na OPNsense 26.7 (FreeBSD 15.1) w VirtualBox – zrzut `opnsense.snmprec`.
"""

from __future__ import annotations

import re

from ..snmp import SnmpClient, SnmpError, as_int
from ..snmp import oids as O
from .base import InterfaceSample, PollResult, SystemInfo
from .linux import LinuxDriver

# net-snmp na FreeBSD: NET-SNMP-MIB::netSnmpAgentOIDs.8
_FREEBSD_AGENT = "1.3.6.1.4.1.8072.3.2.8"
# Jądro OPNsense budowane jest z gałęzi stable/<rok>.<miesiąc>, np. „stable/26.7-n284285-1633399de9dd”
_SERIES = re.compile(r"\bstable/(\d{2}\.\d{1,2})-n\d+")
_FREEBSD = re.compile(r"\bFreeBSD (\d+\.\d+-[A-Z]+(?:-p\d+)?)")

_TECHNICAL_IF = re.compile(r"^(lo|enc|pflog|pfsync)\d+$")
_VPN_IF = re.compile(r"^(wg|ovpn[sc]|ipsec|tun|tap|gif|gre|zt)\w*$")
_VIRTUAL_IF = re.compile(r"^(bridge|lagg|vxlan|epair|carp)\d+$")
_VLAN_IF = re.compile(r"^(vlan\d+(\.\d+)?|\w+[._]vlan\d+|\w+\.\d+)$")


def parse_series(descr: str | None) -> str | None:
    """Seria OPNsense (np. „26.7”) z gałęzi jądra w `sysDescr`."""
    m = _SERIES.search(descr or "")
    return m.group(1) if m else None


class OpnsenseDriver(LinuxDriver):
    name = "opnsense"
    vendor = "OPNsense"

    def __init__(self) -> None:
        self._wan_index: int | None = None

    @classmethod
    def match(cls, system: SystemInfo) -> int:
        descr = system.descr or ""
        if not descr.startswith("FreeBSD "):
            return 0
        if parse_series(descr) or "opnsense" in descr.lower() or "opnsense" in (system.name or "").lower():
            return 70 if (system.object_id or "").startswith(_FREEBSD_AGENT) else 60
        return 0

    async def poll(self, client: SnmpClient, system: SystemInfo | None = None) -> PollResult:
        self._wan_index = await self._default_route_interface(client)
        result = await super().poll(client, system)
        result.disks = [d for d in result.disks if d.mount == "/"]
        return result

    async def _default_route_interface(self, client: SnmpClient) -> int | None:
        """`ifIndex` interfejsu trasy domyślnej; brak trasy albo tabeli = nie wiemy, który port jest WAN-em."""
        try:
            v = await client.get([O.IP_ROUTE_DEFAULT_IF_INDEX])
        except SnmpError:
            return None
        idx = as_int(v.get(O.IP_ROUTE_DEFAULT_IF_INDEX))
        return idx if idx and idx > 0 else None

    def enrich_system(self, result: PollResult) -> None:
        system = result.system
        series = parse_series(system.descr)
        freebsd = _FREEBSD.search(system.descr or "")
        system.kind = "gateway"
        system.vendor = self.vendor
        system.model = "OPNsense"
        system.firmware = series or (f"FreeBSD {freebsd.group(1)}" if freebsd else None)

    def enrich_interface(self, iface: InterfaceSample, result: PollResult) -> None:
        name = iface.name
        iface.label = iface.alias if iface.alias and iface.alias != name else name
        if self._wan_index is not None and iface.if_index == self._wan_index:
            iface.role = "wan"  # także PPPoE albo VLAN – WAN-em jest to, przez co idzie trasa domyślna
            if iface.label == name:
                iface.label = "WAN"
        elif iface.if_type == O.IF_TYPE_LOOPBACK or _TECHNICAL_IF.match(name):
            iface.role, iface.hidden = "system", True
        elif _VPN_IF.match(name) or iface.if_type == O.IF_TYPE_TUNNEL:
            iface.role = "vpn"
        elif _VIRTUAL_IF.match(name):
            iface.role, iface.hidden = "virtual", True
        elif iface.if_type == O.IF_TYPE_ETHERNET or _VLAN_IF.match(name):
            iface.role = "lan"
