# UplinkView

Self-hosted aplikacja webowa do monitorowania sieci w homelabie. W jednym panelu zbiera ruch i stan portów
routera, switchy i access pointów, klientów WiFi, topologię, serwery Linux i Proxmox oraz alerty.

## Instalacja

Jedna komenda na czystym Ubuntu Server (instaluje Dockera, jeśli go brak, tworzy `.env` z losowymi hasłami
i uruchamia usługi):

```bash
curl -fsSL https://raw.githubusercontent.com/uplinkview/uplinkview/main/install.sh | sudo bash
```

Potem otwórz panel w przeglądarce (`http://ADRES-SERWERA:8000`): załóż konto, a kreator pierwszej konfiguracji
pomoże dodać urządzenia. Aktualizacja jednym kliknięciem w panelu (Ustawienia → Aktualizacje) albo poleceniem:

```bash
uplinkview update
```

Szczegóły: [`docs/04-instalacja-i-aktualizacja.md`](docs/04-instalacja-i-aktualizacja.md).

## Co potrafi

- **Pulpit:** karty urządzeń, wykresy ruchu, błędów i dropów, tryb „Na żywo” (ruch WAN co 1–2 s), wiele pulpitów,
  pulpity publiczne tylko do odczytu (`/p/<token>`, np. na wyświetlacz ścienny). Motyw ciemny i jasny.
- **Urządzenia i porty:** status portów, prędkość, PoE, strony szczegółów urządzenia, portu i klienta,
  dostępność w procentach, historia do roku (agregaty godzinowe).
- **WiFi:** sieci, klienci z historią sygnału, obecności i przejść między AP (UniFi Network API).
- **Topologia:** mapa sieci z LLDP.
- **Dual WAN:** stan łączy, przełączenia i SLA.
- **Serwery:** Linux przez SNMP albo własny agent (kontenery Docker, usługi systemd, SMART, temperatury),
  Proxmox VE (maszyny VM/LXC, magazyny, kopie vzdump).
- **Alerty:** urządzenie offline, port down, przeciążenie, CPU/RAM, dysk, błędy portów, dane z agenta;
  powiadomienia przez webhook i Telegram.
- **Administracja:** kopie zapasowe z panelu i `uplinkview backup`, sekrety zaszyfrowane w bazie, moduły
  do włączania i wyłączania, migracje bazy (Alembic).

## Obsługiwane urządzenia

| Producent        | Status | Źródła danych |
|------------------|--------|---------------|
| Ubiquiti UniFi   | ✅ sprawdzone na sprzęcie (UCG Ultra, USW Lite 8 PoE, U6+) | SNMP (IF-MIB, UBNT-UniFi-MIB) + UniFi Network API |
| Serwery Linux    | ✅ | SNMP (`snmpd`) albo agent UplinkView |
| Proxmox VE       | sprawdzone na atrapie API, czeka na prawdziwy serwer | API Proxmox (token, rola PVEAuditor) |
| MikroTik         | driver SNMP na zrzutach syntetycznych | SNMP (IF-MIB, MIKROTIK-MIB, HOST-RESOURCES); RouterOS API planowane |
| TP-Link Omada    | driver SNMP na zrzutach syntetycznych | SNMP (IF-MIB); Omada Controller API planowane |
| Inne             | ✅ podstawowo | generyczny driver SNMP (IF-MIB) |

SNMP v1, v2c i v3 (authPriv).

## Stack technologiczny

| Warstwa       | Technologia |
|---------------|-------------|
| Kolektor      | Python 3.13, asyncio, `pysnmp` 7 |
| Backend API   | FastAPI, Pydantic v2, SQLAlchemy 2 (async), asyncpg, Alembic |
| Baza danych   | PostgreSQL 17 + TimescaleDB (hypertables, retencja, agregaty ciągłe) |
| Frontend      | React 19 + TypeScript, Vite, Tailwind CSS, TanStack Query, Apache ECharts |
| Live update   | WebSocket |
| Wdrożenie     | Docker Compose na Ubuntu Server, obrazy z GHCR, osobny kontener `updater` |

## Architektura

```
 [Router] [Switch] [AP] ──SNMP/API──►  Kolektor (async, co 30 s)  ◄── raporty agenta (push)
 [Proxmox] [kontroler UniFi]                 │
                                             ▼
                               PostgreSQL + TimescaleDB  ◄──  Backend API (FastAPI)
                                                                 │  REST + WebSocket
                                                                 ▼
                                                    Frontend (React) – panel
```

Każdy producent to driver ze wspólnym interfejsem (`discover`, `poll_interfaces`, `poll_extra`, `neighbors`).
Driver generyczny (IF-MIB) działa dla każdego urządzenia ze SNMP, a drivery producentów dokładają resztę.
Wybór drivera jest automatyczny (`sysObjectID` / `sysDescr`).

## Plan prac

1. ✅ Inwentaryzacja i test SNMP
2. ✅ Szkielet projektu: Docker Compose, baza, `install.sh`, `uplinkview update`
3. ✅ Kolektor SNMP: driver generyczny + UniFi
4. ✅ Backend API: urządzenia, porty, metryki, logowanie
5. ✅ Panel: pulpit, ustawienia, aktualizacja jednym kliknięciem, personalizacja, tryb „Na żywo”
6. ✅ UniFi Network API: PoE, klienci WiFi
7. ✅ Topologia LLDP
8. Alerty: ✅ silnik, panel, webhook, Telegram · do zrobienia: e-mail, ntfy, ciche godziny, grupowanie
9. ✅ SNMP v3 · MikroTik i Omada: drivery SNMP gotowe, czekają na prawdziwy sprzęt; API RouterOS i Omada do zrobienia
10. ✅ Serwery Linux (SNMP i agent), Proxmox VE, Dual WAN, kopie zapasowe, szyfrowanie sekretów, moduły,
    strony szczegółów, wiele pulpitów i pulpity publiczne

Dalsze pomysły (ping i test prędkości, raport tygodniowy, role użytkowników, PWA, wersja angielska, eksport
do Prometheus i Home Assistant): [`docs/06-projekt-panelu.md`](docs/06-projekt-panelu.md), sekcja backlog.

## Struktura katalogów

```
UplinkView/
├── backend/        # FastAPI + kolektor + agent Linux (wspólne modele i drivery)
├── frontend/       # React + Vite
├── updater/        # kontener aktualizacji i kopii zapasowych
├── deploy/         # docker-compose.yml, .env.example
├── scripts/        # polecenie `uplinkview` na serwerze (update, status, logs, backup...)
├── install.sh      # instalator jednym linkiem
└── docs/           # dokumentacja
```

## Licencja

UplinkView jest wolnym oprogramowaniem na licencji [GNU AGPL-3.0](LICENSE). Możesz go używać (także w firmie),
zmieniać i rozpowszechniać bez opłat. Jeśli udostępniasz zmienioną wersję innym – również jako usługę przez sieć –
musisz udostępnić jej kod źródłowy na tej samej licencji. Wszystko, co instalujesz u siebie, jest darmowe i bez limitów;
płatna będzie tylko opcjonalna chmura (dostęp z zewnątrz, powiadomienia push).

Chcesz pomóc? Zobacz [`CONTRIBUTING.md`](CONTRIBUTING.md). Licencja komercyjna (bez obowiązków AGPL) – napisz w zgłoszeniu
na GitHubie.
