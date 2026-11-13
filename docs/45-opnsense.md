# OPNsense przez SNMP (0.80.0)

Driver `opnsense` (`backend/netpulse/drivers/opnsense.py`). Sprawdzony 13.11.2026 na OPNsense 26.7 (FreeBSD 15.1)
w VirtualBox; zanonimizowany zrzut: `backend/tests/fixtures/opnsense.snmprec`.

## Co zgłasza OPNsense

OPNsense z wtyczką `os-net-snmp` to zwykły FreeBSD z agentem net-snmp:

- `sysObjectID` = `1.3.6.1.4.1.8072.3.2.8` (net-snmp na FreeBSD) – nic nie mówi o producencie,
- `sysDescr` = `FreeBSD <host> 15.1-RELEASE-p6 FreeBSD 15.1-RELEASE-p6 stable/26.7-n284285-… SMP amd64`,
- IF-MIB z licznikami 64-bit, ale **bez opisów portów** (`ifAlias` pusty) – nazw „WAN”/„LAN” z panelu OPNsense nie ma,
- UCD-SNMP-MIB (CPU, RAM, obciążenie), HOST-RESOURCES-MIB (dyski, procesy),
- brak własnego MIB-u: gałąź BEGEMOT (`1.3.6.1.4.1.12325`, statystyki `pf`) nie odpowiada.

Przed 0.80.0 urządzenie trafiało do drivera ogólnego jako „Generic FreeBSD (urządzenie)”: bez roli routera,
bez WAN-u, z interfejsami zapory na liście portów.

## Jak driver to interpretuje

| Rzecz | Skąd |
|-------|------|
| Rozpoznanie | `sysDescr` zaczyna się od `FreeBSD` i ma gałąź jądra `stable/<rok>.<miesiąc>` (czysty FreeBSD ma `releng/15.1` albo `stable/15`) albo „OPNsense” w nazwie hosta |
| Rodzaj, model, wersja | `gateway`, „OPNsense”, seria z gałęzi jądra (np. `26.7`; pełnego numeru, np. 26.7.3, agent nie podaje) |
| WAN | interfejs trasy domyślnej: `ipRouteIfIndex.0.0.0.0` (`1.3.6.1.2.1.4.21.1.2.0.0.0.0`) – jeden odczyt, tablicy tras nie czytamy |
| LAN | pozostałe karty Ethernet i sieci VLAN |
| VPN | `wg*`, `ovpns*`/`ovpnc*`, `ipsec*`, `tun*`, `tap*`, `gif*`, `gre*` |
| Ukryte | `lo0`, `enc0`, `pflog0`, `pfsync0` (techniczne), `bridge*`, `lagg*`, `epair*`, `carp*` (wirtualne) |
| Dysk | tylko `/` – zbiory ZFS (`/tmp`, `/var/log`, `/home`…) dzielą jedną pulę i każdy wyglądałby jak osobny dysk |

Bez trasy domyślnej żaden port nie dostaje roli WAN – ustawia się go ręcznie w Ustawienia → Łącza WAN.

## Konfiguracja OPNsense

1. System → Firmware → Plugins: `os-net-snmp`.
2. Services → Net-SNMP → General: Enable, community, Save.
3. Jeśli UplinkView odpytuje od strony WAN: Interfaces → WAN – odznaczyć „Block private networks”;
   Firewall → Rules → WAN – Pass, UDP, źródło = sieć UplinkView, cel „This Firewall”, port 161.

## Czego nie sprawdzono

- VLAN-y, mosty, LAGG, WireGuard/OpenVPN/IPsec, PPPoE – nazwy według konwencji OPNsense, bez zrzutu,
- kilka łączy WAN (grupy bram) – WAN-em zostaje tylko interfejs bieżącej trasy domyślnej,
- pfSense – ma inny `sysDescr`; zostaje na driverze ogólnym, dopóki nie będzie zrzutu,
- sprzęt fizyczny (czujniki temperatury) – w VirtualBox ich nie ma.
