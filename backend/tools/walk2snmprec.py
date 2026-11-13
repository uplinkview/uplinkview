#!/usr/bin/env python3
"""Konwersja `snmpwalk -On` → .snmprec (snmpsim) z anonimizacją.

Zostawia tylko poddrzewa potrzebne driverom (system, IF-MIB, HOST-RESOURCES, UCD, UniFi, MikroTik),
podmienia adresy MAC i nazwy SSID, żeby zrzut z sieci domowej można było
bezpiecznie trzymać w repozytorium jako dane testowe.

Użycie:
    python walk2snmprec.py snmpwalk_192.168.1.1.txt ucg-ultra.snmprec
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

KEEP_PREFIXES = (
    "1.3.6.1.2.1.1.",            # system
    "1.3.6.1.2.1.2.",            # ifTable
    "1.3.6.1.2.1.31.1.1.",       # ifXTable
    "1.3.6.1.2.1.25.1.",         # hrSystem (procesy)
    "1.3.6.1.2.1.25.2.",         # hrStorage (dyski serwerów Linux)
    "1.3.6.1.4.1.2021.4.",       # UCD memory
    "1.3.6.1.4.1.2021.10.",      # UCD load
    "1.3.6.1.4.1.2021.11.",      # UCD cpu
    "1.3.6.1.4.1.41112.1.6.",    # UBNT-UniFi-MIB
    "1.3.6.1.2.1.25.3.3.",       # hrProcessorTable (CPU na rdzeń: MikroTik)
    "1.3.6.1.4.1.14988.1.1.3.",  # MIKROTIK-MIB: czujniki (temperatura, napięcie)
    "1.3.6.1.4.1.14988.1.1.4.",  # MIKROTIK-MIB: licencja i wersja RouterOS
    "1.3.6.1.4.1.14988.1.1.7.",  # MIKROTIK-MIB: płyta (model, numer seryjny)
    "1.3.6.1.2.1.4.21.1.2.0.0.0.0",  # ifIndex trasy domyślnej (OPNsense: który port jest WAN-em); reszty tras nie bierzemy
)
# Numer seryjny płyty MikroTik nie trafia do repozytorium
MIKROTIK_SERIAL = "1.3.6.1.4.1.14988.1.1.7.3.0"
DROP_PREFIXES = (
    "1.3.6.1.2.1.1.9.",          # sysORTable – zbędne
)
MAC_PREFIXES = (
    "1.3.6.1.2.1.2.2.1.6.",                  # ifPhysAddress
    "1.3.6.1.4.1.41112.1.6.1.2.1.2.",        # VAP BSSID
    "1.3.6.1.4.1.41112.1.6.1.1.1.",          # radio table (MAC-i jeśli są)
)
SSID_PREFIX = "1.3.6.1.4.1.41112.1.6.1.2.1.6."
SYS_LOCATION = "1.3.6.1.2.1.1.6.0"
SYS_CONTACT = "1.3.6.1.2.1.1.4.0"

LINE_RE = re.compile(r"^\.?([\d.]+) = (.*)$")


def fake_mac(real: bytes) -> bytes:
    digest = hashlib.sha256(b"netpulse" + real).digest()
    return bytes([0x02]) + digest[:5]  # 02:xx – adres lokalnie administrowany


def _printable(raw: bytes) -> bool:
    return all(32 <= b < 127 for b in raw)


def fake_ssid(real: str) -> str:
    if real.startswith(("element-", "vwire-")):
        return real.split("-")[0] + "-" + hashlib.sha256(real.encode()).hexdigest()[:16]
    return "NetPulse-Test" + ("-2G" if "2.4" in real or "2G" in real.upper() else "")


def parse_value(raw: str) -> tuple[str, str] | None:
    """Zwraca (tag, wartość snmprec) albo None, jeśli typ pomijamy."""
    if raw == '""':
        return "4x", ""
    if ": " not in raw:
        return None
    typ, val = raw.split(": ", 1)
    if typ == "INTEGER":
        m = re.search(r"-?\d+", val)
        return ("2", m.group(0)) if m else None
    if typ == "STRING":
        text = val[1:-1] if val.startswith('"') and val.endswith('"') else val
        return "4x", text.encode().hex()
    if typ == "Hex-STRING":
        return "4x", val.replace(" ", "").lower()
    if typ == "OID":
        return "6", val.lstrip(".")
    if typ == "IpAddress":
        return "64", val
    if typ == "Counter32":
        return "65", val
    if typ == "Gauge32":
        return "66", val
    if typ == "Timeticks":
        m = re.match(r"\((\d+)\)", val)
        return ("67", m.group(1)) if m else None
    if typ == "Counter64":
        return "70", val
    return None


def convert(text: str) -> list[tuple[str, str, str]]:
    records: list[tuple[str, str, str]] = []
    for line in text.splitlines():
        m = LINE_RE.match(line.strip())
        if not m:
            continue
        oid, raw = m.groups()
        if not oid.startswith(KEEP_PREFIXES) or oid.startswith(DROP_PREFIXES):
            continue
        parsed = parse_value(raw.strip())
        if parsed is None:
            continue
        tag, value = parsed
        if tag == "4x" and len(value) == 12 and (
            oid.startswith(MAC_PREFIXES) or not _printable(bytes.fromhex(value))
        ):
            value = fake_mac(bytes.fromhex(value)).hex()
        elif oid.startswith(SSID_PREFIX) and tag == "4x":
            value = fake_ssid(bytes.fromhex(value).decode(errors="replace")).encode().hex()
        elif oid == MIKROTIK_SERIAL and tag == "4x":
            value = b"0000000000".hex()
        elif oid in (SYS_LOCATION, SYS_CONTACT):
            value = b"homelab".hex()
        records.append((oid, tag, value))
    records.sort(key=lambda r: tuple(int(p) for p in r[0].split(".")))
    return records


def main() -> None:
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    records = convert(src.read_text(errors="replace"))
    dst.write_text("".join(f"{o}|{t}|{v}\n" for o, t, v in records))
    print(f"{dst}: {len(records)} rekordów")


if __name__ == "__main__":
    main()
