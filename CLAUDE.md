# UplinkView – kontekst projektu dla Claude Code

## O projekcie

UplinkView to self-hosted aplikacja webowa do monitorowania sieci w homelabie. Zbiera w jednym
panelu ruch i stan portów routera, switchy i access pointów: wykresy przepustowości, błędy,
status portów, klienci WiFi, a później topologia i alerty.

Repozytorium: https://github.com/uplinkview/uplinkview

**Nazwa: UplinkView** (od 0.78.0; wybrana 13.11.2026, dawna nazwa NetPulse była zajęta; domena uplinkview.com, konto GitHub `uplinkview`).
Wszystko, co widać, mówi UplinkView: panel, dokumentacja, instalator, powiadomienia, raporty, nazwy pobieranych plików, aplikacja Android.
Polecenie `uplinkview` (dawne `netpulse` działa dalej – oba to dowiązania do `scripts/netpulse`), nowe instalacje w `/opt/uplinkview`,
stare zostają w `/opt/netpulse` (`np_install_dir`, `np_default_dir`). Stary adres repozytorium `arkadiuszbaglaj/NetPulse` zamieniają
na nowy `uplinkview update` i updater (`np_migrate_origin`, `git_ops.set_origin`). **Celowo bez zmiany (zgodność istniejących instalacji):**
pakiet Pythona `netpulse`, `netpulse_updater`, zmienne `NETPULSE_*`, nazwa projektu compose, wolumeny i baza `netpulse`, obrazy
`netpulse-*`, ciasteczka `netpulse_session*`, klucze `netpulse.*` w przeglądarce, plik `scripts/netpulse`, agent `/opt/netpulse-agent`,
`applicationId` `pl.netpulse.app` (inaczej telefon uznałby aplikację za nową), nazwy plików kopii zapasowych.

## Zasady współpracy

- Komunikacja z użytkownikiem **po polsku**. Kod, nazwy w kodzie i komentarze techniczne mogą być po angielsku, dokumentacja w `docs/` po polsku.
- Użytkownik chce być prowadzony **krok po kroku**: po każdym etapie krótko podsumuj, co powstało i jak to sprawdzić, i zaproponuj następny krok.
- Testuj na prawdziwych urządzeniach (sieć 192.168.1.0/24 jest osiągalna z serwera).
- **Instalacja jednym linkiem** jest wymaganiem: UplinkView ma się instalować na czystym Ubuntu Server
  jedną komendą, np.
  `curl -fsSL https://raw.githubusercontent.com/uplinkview/uplinkview/main/install.sh | sudo bash`
  (skrypt instaluje Dockera, jeśli go brak, pobiera projekt, tworzy `.env` z losowymi hasłami i uruchamia `docker compose up -d`).

## Sposób pracy

- Kod pisze Claude i wypycha na GitHub (`main`). Użytkownik instaluje/aktualizuje na serwerze
  (`install.sh`, potem `uplinkview update`) i zgłasza wyniki.
- **Każdy commit na `main` musi być podpisany** (od 0.69.0, klucz `~/.ssh/netpulse_signing`, w tym repo `commit.gpgsign true`): updater
  i `uplinkview update` odrzucają aktualizację bez podpisu kluczem z `deploy/update-signers` zainstalowanej wersji. Przed pushem
  `git log --format='%h %G? %s' -3` (ma być `G`). Nie commitować ani nie scalać w przeglądarce na GitHubie. Opis: `docs/41-podpisane-aktualizacje.md`.
- Każdy push przechodzi CI (`.github/workflows/ci.yml`): ruff, pytest (drivery na fixtures,
  pysnmp kontra snmpsim v2c/v3, kolektor + TimescaleDB, API) oraz test end-to-end `install.sh`
  → `device add` → dane w API → `uplinkview update`. Wynik CI sprawdzać przed zgłoszeniem
  użytkownikowi, że wersja jest gotowa.
- **Numer wersji** (`backend/netpulse/__init__.py` i `frontend/package.json` + `package-lock.json`) podnosimy przy każdym wypchnięciu zmian, które użytkownik ma zainstalować: drobne zmiany i poprawki → patch (0.8.0 → 0.8.1), nowa funkcja albo etap → minor (0.8.x → 0.9.0). Bez tego panel pokazuje „dostępne zmiany” przy tym samym numerze wersji.
- Fixtures `backend/tests/fixtures/*.snmprec` to zanonimizowane zrzuty z prawdziwych urządzeń
  (`backend/tools/walk2snmprec.py` – podmienia MAC-i i SSID).

## Środowisko docelowe

- Ubuntu Server (na start), wdrożenie przez Docker Compose.
- Urządzenia testowe (Ubiquiti UniFi), SNMP v2c, community `public` (do zmiany przed produkcją):

| Urządzenie          | IP          | Rola         |
|---------------------|-------------|--------------|
| Cloud Gateway Ultra | 192.168.1.1 | router       |
| USW Lite 8 PoE      | 192.168.1.2 | switch       |
| U6+                 | 192.168.1.3 | access point |

- Port 7 switcha: telewizor (link 100 Mb/s – to normalne).
- Przyszłe wsparcie: MikroTik, TP-Link Omada, potem inne. SNMP v3 musi być przewidziane od początku (model danych + klient).

## Stack

- Backend / kolektor: Python 3.13, asyncio, `pysnmp` 7 (v1/v2c/v3), FastAPI, SQLAlchemy 2 async, asyncpg
- Baza: PostgreSQL 17 + TimescaleDB (metryki jako hypertables, retention policy)
- Frontend: React 19 + TypeScript, Vite, Tailwind CSS, TanStack Query, Apache ECharts
- Live update: WebSocket; Redis dojdzie, gdy będzie potrzebny
- Panel: motyw ciemny i jasny, pulpit z kartami, menu po lewej, pasek górny z kontem i interwałem
  odświeżania; aktualizacja jednym kliknięciem przez osobny kontener `updater`; wykresy i układ
  pulpitu personalizowane na koncie. Szczegóły i etapy 5a–5e: `docs/06-projekt-panelu.md`.
- Kierunek: aplikacja do samodzielnej instalacji przez innych, potem chmura i aplikacja mobilna
  z powiadomieniami i widgetami – panel jest wyłącznie klientem API, sekcje dochodzą przez rejestr modułów.

## Architektura

Każdy producent = driver ze wspólnym interfejsem; driver generyczny (IF-MIB) działa dla
każdego urządzenia ze SNMP, drivery producentów dokładają resztę. Wybór drivera automatyczny
po `sysObjectID` / `sysDescr`.

Kolektor co 30 s: odpytuje urządzenia równolegle, liczy przepływ z różnic liczników
(`ifHCInOctets`/`ifHCOutOctets`; obsługa przepełnienia Counter32 i resetu urządzenia; od 0.54.4 próbka z chwili,
gdy łącze padło albo wróciło, albo z resetem w jednym kierunku – bez ruchu, porty Ethernet odrzucają > 1,1× prędkości: `rates.py`),
zapisuje do TimescaleDB. Port idzie za nazwą (`ifName`), nie numerem: przesunięty `ifIndex` (UCG Ultra po UniFi OS 6.0)
przenosi wiersz `interfaces` (`netpulse/ifindex.py`, od 0.65.7), port, którego numer zajął inny, dostaje `if_index = -id`.

Schemat bazy zmieniają **migracje Alembic** (od 0.10.0; `backend/netpulse/db/migrations/`, opis:
`docs/13-migracje-bazy.md`). `init_db` (kolektor przy starcie, `uplinkview db init`) wykonuje `upgrade head` pod blokadą
w jednej transakcji, potem zakłada hypertables. Każda zmiana w `models.py` = nowa migracja (`--rev-id 0002`, …);
brak migracji wyłapie `test_migrations.py::test_fresh_db_matches_models`. Nowa hypertable = indeks (obiekt, `time`) – klucz główny zaczyna się od czasu (0017, 0.65.4).
Od 0.67.0 kompresja chunków starszych niż 7 dni (`netpulse/compression.py`, zakłada `init_db`; `NETPULSE_COMPRESS_AFTER_DAYS`, 0 = wyłączona):
**nowa hypertable = wpis w `SEGMENT_BY`**, migracja zmieniająca typ kolumny tabeli metryk musi najpierw zdekompresować chunki (`docs/13`).
Czy jest TimescaleDB, API sprawdza przez `timescale_available()` (zapamiętane w procesie), nie `has_timescale(conn)` przy każdym żądaniu. Migracja bazowa `0001` = schemat 0.9.0
i przejmuje bazy sprzed migracji bez utraty danych.

## Wyniki analizy SNMP (szczegóły: `docs/02-wyniki-snmp.md`)

- Wszystkie urządzenia: IF-MIB z licznikami 64-bit, UCD-SNMP-MIB (RAM, load).
- UCG Ultra (sysDescr `Ubiquiti UniFi UCG-Ultra ...`): `eth4` = WAN, `eth0`–`eth3` = LAN 1–4 (potwierdzone przez użytkownika). Ukryć interfejsy techniczne: lo, dummy0, ip_vti0, ip6_vti0, ip6tnl0, miireg, bond0, ifb0/1; switch0, switch0.1, br0 jako wirtualne.
- USW Lite 8 PoE (sysDescr `Linux UBNT ...`): porty `ifName` 0/1–0/8, nazwy z UniFi w `ifAlias` (np. „AP U6+”, „UCG Ultra”). BRIDGE-MIB z tablicą MAC. Brak PoE-MIB i LLDP-MIB.
- U6+ (sysObjectID `.1.3.6.1.4.1.41112`): uplink `eth0`; `ra*` = 2.4 GHz, `rai*` = 5 GHz. UBNT-UniFi-MIB VAP table `.1.3.6.1.4.1.41112.1.6.1.2.1`: .2 BSSID, .4 kanał, .6 ESSID, .7 nazwa interfejsu, .8 liczba klientów, .9 radio (ng/na), .10 rx bytes, .16 tx bytes (Counter32). Ukryć wewnętrzne SSID `element-*`, `vwire-*`.
- Czego SNMP nie da: PoE na portach, LLDP/topologia, lista klientów WiFi z nazwami i sygnałem → UniFi Network API (klucz API), etap 6.
- Surowe zrzuty `snmpwalk` **nie trafiają do repo** (MAC-i, SSID, trasy sieci domowej) – są w `.gitignore`; do repo idą tylko zanonimizowane `.snmprec`.

## Plan prac

1. ✅ Inwentaryzacja i test SNMP
2. ✅ Szkielet projektu – struktura, Docker Compose, baza, `install.sh`, `uplinkview update`
3. ✅ Kolektor SNMP – driver generyczny IF-MIB + UniFi, zapis metryk (+ wstępne API tylko do odczytu)
4. ✅ Backend API – urządzenia (CRUD + test SNMP), porty, metryki, logowanie (kreator pierwszego konta, sesje w ciasteczku, `uplinkview user passwd`)
5. Panel (MVP), etapy: 5a ✅ szkielet (pasek górny, menu, motyw, logowanie; kod w `frontend/`), 5b ✅ dashboard + interwały odświeżania,
   5c ✅ ustawienia (konto, urządzenia, odświeżanie), 5d ✅ aktualizacja jednym kliknięciem (updater + obrazy GHCR),
   5e ✅ personalizacja wykresów i układu, 5f ✅ dane „Na żywo” – wykresy kołowe (od 0.40.0), a od 0.45.0 także bieżący ruch WAN, nagłówki wykresów, tabele i paski portów oraz CPU/RAM urządzeń SNMP, od 0.72.0 strona urządzenia i portu, mapa sieci i VPN (WebSocket `/api/live/device`, co ~1,5 s; jeden wspólny kanał `lib/liveHub.ts`, przełącznik „Na żywo” w pasku górnym; historia dalej co 30 s; `api/live.py`, opis w `docs/06-projekt-panelu.md`)
6. ✅ Driver UniFi przez API – PoE, klienci WiFi (kontrolery z kluczem API, starsze API `stat/*`; opis: `docs/08-unifi-api.md`).
   Od 0.52.0 urządzenia bez SNMP (USW Flex/Ultra) z oficjalnego Network API: `driver = "unifi_api"` (`NON_SNMP_DRIVERS`
   w `models.py`), zakładane przez kolektor UniFi, zapis jak SNMP (`unifi_devices.py`), mapowanie `unifi_api_devices`
   (migracja 0012; `device_id = NULL` = usunięte, nie zakładać ponownie). Zajętość kanału AP z UI-MIB (`channel_util_percent`).
7. ✅ Topologia LLDP – mapa sieci (od 0.35.0 obciążenie i prędkość kabli, przybliżanie; opis: `docs/22-wykresy.md`)
8. ✅ Alerty (8a silnik, 8b panel, reguły dysku i błędów portów, powiadomienia: webhook/Telegram, od 0.25.0 ntfy i e-mail (SMTP), ciche godziny z podsumowaniem po ciszy, grupowanie po topologii LLDP; opis: `docs/21-powiadomienia.md`) – port down, przeciążenie, urządzenie offline; reguły z progami (ruch, błędy, CPU/RAM, dysk), lista i historia w panelu, dzwonek w pasku górnym (opis w `docs/06-projekt-panelu.md`, backlog)
9. SNMP v3 ✅ (testowane klientem pysnmp kontra snmpsim w CI), MikroTik i Omada: drivery SNMP gotowe, ale na zrzutach syntetycznych – czekają na prawdziwe zrzuty (opis: `docs/12-mikrotik-omada-snmp.md`); API kontrolera Omada i RouterOS dalej do zrobienia
10. Serwery Linux – etap A ✅ SNMP (`snmpd`, driver `linux`, dyski, karta serwera), etap B ✅ (0.11.0) własny agent: push z tokenem (`api/agents.py`), jeden plik Pythona `backend/netpulse/agent/netpulse_agent.py` + `install.sh` serwowane przez API, systemd, Docker, SMART, ogólna tabela `metrics` (migracja 0002), Ustawienia → Agenci. Opis: `docs/14-agent-linux.md`. Alerty z agenta ✅ (0.12.0: kontener, usługa, SMART, temperatura; pole `alert_rules.match`, migracja 0003); wykresy z `metrics` ✅ (0.13.0, źródła `agent_*` w edytorze wykresu); strona szczegółów serwera `/devices/<id>/server` i ostrzeżenie „agent starszy niż UplinkView” ✅ (0.24.0)

## Kopie zapasowe

Od 0.14.0: Ustawienia → Kopia zapasowa (utworzenie, pobranie, wgranie z komputera od 0.16.0, przywrócenie z kopią bezpieczeństwa) i `uplinkview backup`;
`uplinkview update` robi kopię przed zmianą kodu. Od 0.43.3 `uplinkview backup` działa bez sudo dla użytkownika z grupy `docker`
(zleca kopię usłudze updater, jak panel). Wykonuje je updater (`updater/netpulse_updater/backups.py`), opis: `docs/15-kopia-zapasowa.md`.

## Szyfrowanie sekretów

Od 0.15.0 community SNMP, klucze SNMPv3, klucz API kontrolera i adresy webhooków są w bazie zaszyfrowane
(`backend/netpulse/crypto.py`, typ kolumny `EncryptedText`, prefiks `enc:v1:`). Klucz: plik w wolumenie `netpulse_keys`
(tworzony sam) albo `NETPULSE_SECRET_KEY` w `.env`. Nowa kolumna z sekretem = `EncryptedText` + wpis w `SECRET_COLUMNS`.
Opis: `docs/16-szyfrowanie-sekretow.md`.

## Proxmox VE

Od 0.17.0: Ustawienia → Proxmox (token API, rola PVEAuditor), strona Proxmox (VM/LXC, magazyny), węzły jako urządzenia
`driver = "proxmox"` (karta, alerty, wykresy), alerty: maszyna zatrzymana, kopia vzdump z błędem, brak świeżej kopii.
Kod: `backend/netpulse/proxmox.py`, `proxmox_collector.py`, `api/proxmox.py`; atrapa API do testów: `backend/tests/pve_fake.py`.
Kolekcja `guests` do tabeli i pasków (0.31.0, `panels._guest_rows`): stan, CPU, RAM, ruch, czas pracy, wiek kopii w h.
Opis: `docs/17-proxmox.md`. Sprawdzone 2026-10-27 na prawdziwym PVE 9.1.1/9.2.24 (jeden węzeł, VM i LXC, alert zatrzymanej maszyny, kopia vzdump) –
parsery bez zmian; PVEAuditor nie widzi plików kopii, więc od 0.28.5 wiek kopii też z zadań vzdump i ich logów; klaster dalej tylko na atrapie.

## Moduły

Od 0.18.0: Ustawienia → Moduły (Proxmox, UniFi, agenci, kopia zapasowa z panelu). Wyłączony moduł znika z panelu, kolektor
go pomija, jego urządzenia i reguły alertów są pomijane; dane zostają. Nowa instalacja startuje z wyłączonymi integracjami.
Backend: `netpulse/modules.py` (`require_module`, `hidden_drivers`), panel: pole `module` w rejestrze `frontend/src/modules.tsx`.
Strony w rejestrze są ładowane na żądanie (od 0.36.1 – nowa strona przez `page()`, opis: `docs/06-projekt-panelu.md`).
Nowa integracja = nowy moduł. Opis: `docs/18-moduly.md`.

## Dual WAN (failover)

Od 0.19.0: łącza WAN routera (`wan_links`, historia w hypertable `wan_link_metrics`, migracja 0006). Port z rolą `wan`
w driverze zostaje sam WAN 1; kolejne porty ustawia się w Ustawienia → Łącza WAN (port dostaje rolę `wan`, więc wlicza się
do ruchu WAN, „Na żywo” i alertów). „Aktywne” = informacja z kontrolera UniFi (`wan1`/`wan2`, `uplink`, `is_uplink`),
bez kontrolera – link (`ifOperStatus`) i ruch. Logika: `backend/netpulse/wan.py` (czysta), zapis: `wan_links.py`,
API: `api/wan.py` (`/api/wan/status|history|sla|links`), widgety `wan_status`, `wan_chart`, `wan_sla`.
Od 0.46.0 kolejność łączy jest wspólna dla wszystkich routerów (migracja 0011): WAN 1 główne, łącza innych routerów
są zapasem (`source = "priority"`), dopóki WAN 1 działa (`decide(..., outranked_by)`). Od 0.47.0 podpowiedź w Łączach WAN: łącze WAN zgłoszone przez kontroler, którego nie ma na liście
(`wan_links.save_detected`, `GET /api/wan/suggestions`). Od 0.55.0 pingi każdego łącza (też zapasowego) z bramy UniFi (`wan1.latency`, `uptime_stats.WAN*.monitors`) w `metrics` (`wan_latency_ms`, `wan_ping_ms`, źródła wykresu `wan_latency`/`wan_ping`) i opcja wykresu `wan_backup` – ruch przez łącze zapasowe innym kolorem (`backupSpans`, visualMap). Opis: `docs/19-dual-wan.md`. **Sprawdzone 11.11.2026 na prawdziwym sprzęcie** (UCG Ultra, GSM na `eth3`: awaria WAN 1, praca na GSM, powrót;
zrzut kontrolera `unifi_gateway_dual_wan.json`). Krótkie mignięcia łącza (< 30 s) instancje łapią zależnie od chwili odczytu.

## Szczyt ruchu WAN i testy prędkości bramy (0.70.0)

Wykres to średnia z 30 s, więc krótki test prędkości wyglądał na kilka razy wolniejszy niż na bramie. Od 0.70.0: (1) wynik testu
prędkości bramy UniFi z kontrolera (`speedtest-status` → `unifi.parse_speedtest`, zapis każdego nowego testu do `metrics` z czasem testu:
`speedtest_down_bps|up_bps|ping_ms`, źródło wykresu `speedtest`, szablon „Testy prędkości bramy”) – zgodność 1:1 z bramą;
(2) szczyt portów WAN: `netpulse/peaks.py` czyta liczniki co sekundę (`NETPULSE_PEAK_INTERVAL`, 0 = wyłączone) i kolektor zapisuje
najwyższą średnią z ok. 5 s (od 0.71.0 odczyt co 0,5 s) w `interface_metrics.in_bps_max|out_bps_max` (migracja 0018; serie `in_bps_max`/`out_bps_max` źródeł Ruch WAN
i Port, puste powyżej 7 dni – agregat godzinowy ich nie ma). Prędkość liczona między zmianami licznika (UCG odświeża co ~1 s), dokładność
ok. ±20 %. `Collector(peaks=None)` w testach działa jak dotąd. Opis: `docs/42-szczyt-i-testy-predkosci.md`. Pierwszy test na serwerach
(12.11.2026): wynik testu 1:1 na obu, szczyt na VPS +4 %, na domowym zaniżony przez nieodpowiadający router – poprawione w 0.70.1
(próbnik: limit czasu 0,8 s, pomijanie milczącego routera na 30 s); do ponownego sprawdzenia.

## Zgodność z UniFi (0.71.0)

Wykresy ruchu mają się zgadzać z UCG Ultra 1:1 (wymaganie użytkownika). UniFi trzyma historię w kubełkach 5 min / 1 h
(bajty; dla WAN też najwyższa chwilowa prędkość), wykres UniFi rysuje średnią z kubełka. UplinkView od 0.71.0: odczyty kolektora
równo o :00/:30 (`rates.wait_for_slot`), czas próbki = środek jej przedziału (`rates.sample_times`, `collector.spread`),
kubełki wykresów z drabinki `aggregates.RAW_BUCKETS_S` (24 h = 5 min, 7 dni = 1 h; w panelu `bucketSeconds` – **zmiana tylko
w obu miejscach**), szczyt WAN w dymku obok średniej (`PanelLine.peaks`), niemożliwa szybkość w jednym kierunku odrzuca próbkę.
Porównanie 13.11.2026 (SSH do bramy kluczem `~/.ssh/netpulse_ucg`, tylko odczyt; baza `unifi-network` na 127.0.0.1:5434):
sumy bajtów WAN i portów LAN zgodne co do 0,1–1 %. Opis: `docs/42-szczyt-i-testy-predkosci.md`.

## VPN (0.57.0)

Klienci VPN bramy UniFi z kontrolera (`rest/networkconf` → `remote-user-vpn`, `v2/.../wireguard/users`, `stat/remoteuservpn`):
stan w `app_settings` (`vpn:<kontroler>`), metryki `vpn_connected|vpn_down_bps|vpn_up_bps` w `metrics` na bramie (klucz = klient),
bez migracji. Kod: `netpulse/vpn.py`, `unifi.py` (`UnifiApi.vpn`), `api/vpn.py` (`GET /api/vpn`), widget `vpn`, źródło wykresu `vpn`,
alert i zdarzenie `vpn_connect`. Od 0.72.0: `rx_rate`/`tx_rate` kontrolera są już w b/s (do 0.71.1 ×8, migracja 0019 poprawia
historię) i widget VPN na żywo (`/api/live/vpn`, `VpnLiveHub`, `useLiveVpn` + `withLiveVpn`). Interfejs, którego nie ma w odczycie SNMP (np. `wgsrv1` między sesjami, rola `vpn`), dostaje
`oper_status = "notPresent"` bez próbek (panel: „brak sesji” / „nieobecny”). Opis: `docs/30-vpn.md`.

## Wykrywanie urządzeń i raport urządzenia (0.73.0)

Etap 5 planu (`docs/40`). Skan podsieci w kreatorze `/setup` i w Ustawienia → Urządzenia → Wykryj w sieci:
`netpulse/discovery.py` (v1/v2c: **jedno gniazdo UDP** dla całej podsieci, `scan_community`, /24 w ok. 5 s; v3: klienci pysnmp
po 8), rozpoznanie tym samym `detect_driver` + `enrich_system` co kolektor, producent na driverze ogólnym z `ENTERPRISES`;
API `api/discovery.py` (`/api/discovery/suggest|scan`), panel `DiscoveryPanel.tsx` (zaznacza sam sprzęt sieciowy, dodaje przez
`POST /api/devices`). Raport urządzenia: `netpulse/devreport.py` (gałęzie standardowe + producenta, drugi odczyt po 30 s,
anonimizacja `Anonymizer`; tablic MAC/ARP/tras/klientów nie czyta; `PySnmpClient.walk_typed` – typy .snmprec),
`POST /api/devices/{id}/report`, panel `pages/DeviceReport.tsx` (pobranie JSON + link do szablonu
`.github/ISSUE_TEMPLATE/nowe-urzadzenie.yml`). **Nowa gałąź z danymi osobowymi = reguła w `devreport.anonymize` i test
w `test_discovery.py::test_report_has_no_private_values`.** Sprawdzone 13.11.2026 na UCG, USW i U6+. Opis: `docs/43-wykrywanie-urzadzen.md`.

## OPNsense (0.80.0)

Driver `opnsense` (`drivers/opnsense.py`, na bazie `LinuxDriver`): OPNsense to zwykły FreeBSD z net-snmp (`8072.3.2.8`), bez własnego MIB-u
i bez `ifAlias`. Rozpoznanie po gałęzi jądra w `sysDescr` (`stable/26.7` = seria OPNsense), `kind = gateway`, WAN = interfejs trasy domyślnej
(`O.IP_ROUTE_DEFAULT_IF_INDEX`, jeden odczyt), ukryte `lo0`/`enc0`/`pflog0`/`pfsync0`, dysk tylko `/` (ZFS). Sprawdzone 13.11.2026 na OPNsense 26.7
w VirtualBox (192.168.1.135; `em1` = WAN, `em0` = LAN 192.168.10.1), fixture `opnsense.snmprec`. VLAN, VPN, kilka WAN i pfSense bez zrzutu.
**Nowy driver = wpisy w:** `drivers/__init__.py`, `DriverName` (`api/schemas.py`, `lib/api.ts`), `deviceFormLogic.ts`, `devform.driver.*` w `pl.ts`/`en.ts`,
`verification.SOURCES` + `messages.py`, `NETWORK_DRIVERS` (`lib/discovery.ts`, jeśli sprzęt sieciowy). Opis: `docs/45-opnsense.md`.

## Język angielski (0.74.0–0.76.0)

Etap 4 planu, część 4a (opis i dalsze części: `docs/44-jezyk-angielski.md`). Panel w dwóch językach: `i18n/pl.ts` (źródło kluczy)
i `i18n/en.ts` (`Record<TextKey, string>`) – **nowy tekst = wpis w obu plikach** (brak klucza w `en.ts` to błąd typów,
`English.test.tsx` pilnuje zmiennych `{…}` i braku polskich znaków). Wybór języka: Ustawienia → Konto i strona logowania,
w przeglądarce (`netpulse.language`), domyślnie język przeglądarki; zmiana przeładowuje panel. Daty i liczby: `lib/intl.ts`
(`dateFormat`, `numberFormat`, `formatNumber`) albo `locale()` – **nie `"pl"` wpisane w kod**. Testy panelu działają po polsku
(`test/setup.tsx`). Od 0.75.0 (4b) backend tłumaczy odpowiedzi JSON dla `Accept-Language: en` (panel wysyła je zawsze):
`netpulse/i18n.py` (`LanguageMiddleware`, `translate`) według katalogu wzorców `netpulse/messages.py`; kod dalej pisze po polsku.
**Nowy polski komunikat backendu albo updatera = wpis w `messages.py`** (pilnuje `test_i18n.py`), pisany w całości, nie
z kawałków. Od 0.76.0 (4c): język powiadomień = ustawienie serwera (`i18n.server_language`, Ustawienia → Powiadomienia),
raport PDF/CSV w języku panelu (`?lang=`), Android: `res/values` (angielski) + `res/values-pl` – **nowy tekst w obu**.

## Szczegóły, dostępność i pulpity

Od 0.20.0–0.23.0 (opis: `docs/20-szczegoly-i-pulpity.md`):
- Strony szczegółów (trasy ukryte w menu: `hidden: true` w `frontend/src/modules.tsx`): urządzenie `/devices/<id>`,
  port `/devices/<id>/ports/<id>`, klient `/clients/<MAC>`. Dostępność w %: `api/availability.py`.
- Ciągłe agregaty godzinowe TimescaleDB (`netpulse/aggregates.py`, zakłada `init_db`, poza Alembikiem): wykresy 30 dni
  i 1 rok (`RangeMinutes`), powyżej 7 dni zapytania idą do widoków `*_1h`. Przed `drop_all` w testach: `aggregates.drop_all`.
- Historia klientów: `client_metrics` + `known_clients` (migracja 0007), API `api/clients.py`.
- Kreator pierwszej konfiguracji `/setup` (otwiera się po założeniu konta).
- Wiele pulpitów (`dashboards`, jeden `is_default`), Ustawienia → Dashboardy z kreatorem, pulpit publiczny `/p/<token>`
  (migracja 0008): API `api/public.py` z białą listą danych z widgetów pulpitu – **nowy widget = dopisać jego ścieżki
  w `resolve()`**; w panelu `setPublicDashboard` w `lib/api.ts` kieruje zapytania widgetów do API publicznego.

## Sprawdzanie dostępności

Od 0.30.0: strona Dostępność (od 0.58.3 w Ustawieniach, `/settings/checks`) – ping (opóźnienie, utrata pakietów, jitter = jakość łącza), HTTP(S) (kod, tekst,
ważność certyfikatu), port TCP i od 0.64.0 DNS. Ping bez roota (gniazdo ICMP `SOCK_DGRAM`, działa w kontenerze kolektora), bez
zewnętrznej biblioteki. Kod: `netpulse/checks.py`, `checks_collector.py` (pętla w kolektorze), `api/checks.py`,
migracja 0010 (`checks`, hypertable `check_metrics`). Alerty: `check_down` + metryki `check_latency_ms`,
`check_loss_percent`, `check_cert_days` (filtr nazwy w `match`, bez urządzenia). Pulpit: źródło `check`, kolekcja
`checks`, oś stanów `kind: "check"`. Rdzeń, nie moduł. Opis: `docs/23-dostepnosc.md`. `1.1.1.1` nie odpowiada na
ping w sieci użytkownika – domyślny gotowy wybór to `8.8.8.8`.

## Świeżość danych (0.59.0)

Awaria ≠ brak danych: werdykt kolektora (`Device.last_polled_at`) starszy niż `max(120 s, 4 × poll_interval)` daje
w API `status = "unknown"`, `stale = true`, `last_status` = zapisany werdykt (`netpulse/freshness.py`, `Device.live_status`,
w SQL `status_sql`; sprawdzenia: `Check.live_status` z `interval_s`). Alerty: nieaktualne urządzenie nie otwiera
„nie odpowiada”, a jego otwarte alerty trwają (bez fałszywego „zakończony”). **Nowe miejsce, które czyta status
urządzenia w API = `live_status` / `status_sql`, nie surowe `Device.status`.** Nowy zapis statusu = też `last_polled_at`.
Testy alertów z bazą: helper `polled(now)` (świeży werdykt przed oceną). Panel: plakietka „brak aktualnych danych”
(`deviceState`, `staleHint` w `DevicesWidget.tsx`). Opis: `docs/31-swiezosc-danych.md`.

## Okna serwisowe (0.60.0)

Ustawienia → Okna serwisowe: jednorazowe (`starts_at`–`ends_at`) albo co tydzień (`days` 0 = pon., `time_from`, `duration_min`,
czas serwera TZ), na wybrane urządzenia albo na wszystko (`device_ids` puste – też alerty bez urządzenia). W oknie alert powstaje
z `muted = maintenance = true` (bez powiadomienia, bez dzwonka), po oknie – powiadomienie, gdy problem trwa; koniec w oknie
bez „zakończony”. Dostępność odejmuje próbki z okien (z surowych tabel, `maintenance_s`). Kod: `netpulse/maintenance.py`
(czysta logika), `api/maintenance.py`, migracja 0013 (`maintenance_windows`, `alerts.maintenance`), panel
`pages/settings/MaintenancePage.tsx`, `MaintenanceBadge`. SLA WAN i dostępność sprawdzeń jeszcze bez okien. Opis: `docs/32-okna-serwisowe.md`.

## Role i dziennik zdarzeń (0.61.0)

Role kont: `admin` / `operator` (potwierdza alerty, okna serwisowe) / `viewer` (tylko odczyt + własne hasło, odświeżanie,
własne pulpity); `users.role` (migracja 0014, `is_admin` zostaje i ustawia je `User.set_role`). API: domyślnie każda zmiana
wymaga administratora – **nowa trasa dla niższej roli = wpis w `ROLE_RULES` (`api/security.py`)**, `test_roles.py` pilnuje,
że wpisy wskazują istniejące trasy. Ustawienia → Konta (`api/users.py`, ostatni administrator chroniony) i Dziennik zdarzeń
(`audit_log`, `netpulse/audit.py`, middleware `audit_changes`; logowania i każda zmiana z kodem odpowiedzi, **bez treści
żądań**, rok przechowywania). Panel: `lib/roles.ts` (`useCan`), pole `role` podstron Ustawień w `modules.tsx` (bez niego –
tylko administrator). Opis: `docs/33-role-i-audyt.md`.

## Wydajność API (0.67.0)

Proxy kompresuje odpowiedzi (gzip w `deploy/proxy/nginx.conf`). API pamięta sprawdzoną sesję 10 s (`_sessions` w `api/security.py`,
`NETPULSE_SESSION_CACHE_S`; w testach wyłączona przez `conftest.py`) – **nowa trasa zmieniająca sesje, role, hasła albo 2FA woła
`forget_sessions()`**. Argon2 w trasach API tylko przez `hash_password_async` / `verify_password_async` (wątek, nie pętla asyncio).

## HTTPS (0.62.0)

Kontener `proxy` (nginx, `deploy/proxy/`) przyjmuje `NETPULSE_PORT` (HTTP, jak dotąd) i `NETPULSE_HTTPS_PORT` (8443);
**API nie ma już opublikowanego portu** (dlatego `NETPULSE_FORWARDED_ALLOW_IPS="*"` – adres klienta z `X-Forwarded-For`).
Certyfikat lokalnego CA UplinkView wystawia i odnawia `deploy/proxy/tls.sh` w `<katalog>/deploy/tls` (adresy: `NETPULSE_TLS_NAMES`
z instalatora/`uplinkview update` – `np_tls_names` – oraz dopisane w panelu `request/names`; własny certyfikat w `custom/`).
API: `netpulse/tls.py`, `api/tls.py` (`/api/system/tls`, `ca.pem`, `PUT names`), panel: `HttpsCard` w Ustawienia → System.
Ciasteczko sesji: `netpulse_session` (HTTPS, Secure) i `netpulse_session_http` (HTTP) – jedna nazwa blokowała logowanie przez HTTP
po HTTPS (0.65.5); token czytać przez `session_token()`, nie `request.cookies`.
Od 0.68.0 pełny CSP (`content_security_policy` w `api/web.py`, skrót skryptu motywu liczony z index.html; **zasób z obcego adresu = dopisać
źródło tam**, podgląd z polityką: `frontend/dev/csp-preview.mjs`), limit logowań także na konto (20 prób, z wyjątkiem adresu znanego z udanego
logowania), kontenery z `cap_drop`/`no-new-privileges`, obraz bazy przypięty (`timescale/timescaledb:2.32.0-pg17` w compose i `ci.yml`, nie obniżać;
rozszerzenie aktualizuje `update_timescale_extension` w `init_db`) i `backend/requirements.lock` (**zmiana zależności w `pyproject.toml` = odświeżyć
plik poleceniem z `docs/34-https.md`**). Osobna rola bazy odłożona (uzasadnienie w `docs/34`).
Od 0.65.6 nagłówki bezpieczeństwa w każdej odpowiedzi (`SECURITY_HEADERS`, `frame-ancestors 'self'`), `/docs` i wersja tylko po zalogowaniu,
dymek wykresu escapuje nazwy serii (`tooltipHtml`) – **nowy formatter ECharts składający HTML = `escapeHtml` na tekstach z danych**.
Opis: `docs/34-https.md`.

## Logowanie dwuskładnikowe (0.63.0)

TOTP (RFC 6238, `netpulse/totp.py`, bez biblioteki; QR z `segno`) i 10 jednorazowych kodów zapasowych; kolumny `users.totp_*`
(migracja 0015, sekret w `SECRET_COLUMNS`). Login: bez kodu 401 `detail.code = "totp_required"`, zły kod `totp_invalid`
(liczony do limitu logowań) – panel czyta `ApiError.code`. Każdy krok czasu działa raz (`totp_last_step`). Własne konto:
`/api/auth/totp*` (wszystkie role, wpisy w `ROLE_RULES`), administrator: `reset_totp` w `PATCH /api/users/{id}`,
serwer: `uplinkview user 2fa-off <login>`. Opis: `docs/35-logowanie-dwuskladnikowe.md`.

## DNS i potwierdzenie danych (0.64.0)

Sprawdzenie `kind = "dns"` (Ustawienia → Dostępność): własny klient `netpulse/dnsquery.py` (UDP, przy TC – TCP, bez biblioteki),
typy A/AAAA/CNAME/MX/TXT/NS/PTR, serwer `dns_server` (puste = resolv.conf), oczekiwana odpowiedź w `keyword`, port serwera w `port`;
migracja 0016 (`checks.dns_type|dns_server|last_answer`). Potwierdzenie danych: rejestr `netpulse/verification.py` (`SOURCES`,
poziomy `verified|partial|test`) – **po sprawdzeniu źródła na prawdziwym sprzęcie zmienić tam poziom**; `Device.verification`,
`GET /api/system/verification`, panel `components/Verification.tsx` (plakietka na stronie urządzenia, lista w Ustawienia → System).
Nowy driver = wpis w `SOURCES` (pilnuje `test_verification.py`). Opis: `docs/36-dns-i-potwierdzenie-danych.md`.

## Raport miesięczny (0.65.0)

Menu → Raporty (`/reports`, grupa Zdarzenia, każda rola): podgląd i pobranie PDF/CSV za miesiąc (`month=RRRR-MM`, puste =
poprzedni). Kod: `netpulse/report.py` (`build`, `to_csv` – średnik, przecinek, BOM; `to_pdf` – `fpdf2`, czcionka DejaVu
z `fonts-dejavu-core` w Dockerfile, bez niej Helvetica bez ogonków), `api/reports.py` (`/api/reports/monthly`, `.csv`, `.pdf`),
panel `pages/ReportsPage.tsx`. Urządzenia i ruch WAN z agregatów godzinowych (cały miesiąc), sprawdzenia i SLA WAN z surowych
próbek (tylko `retention_days` – raport podaje `raw_from`). Bez zapisu raportów i wysyłki e-mailem. Opis: `docs/37-raport-miesieczny.md`.

## Aplikacja Android (0.1.0, widget 0.2.0)

`mobile/android/` – Kotlin + Jetpack Compose, OkHttp, bez zmian na serwerze: logowanie ciasteczkiem jak panel (adres,
login, hasło, kod 2FA), ekran ruchu WAN (`/api/wan/status`, `/api/dashboard/traffic`, WebSocket `/api/live/device`).
Od 0.2.0 widget „Ruch WAN” (Glance, `WanWidget.kt`; odświeżanie WorkManager co 15 min, przycisk ↻ i aplikacja – `WidgetData.kt`).
0.1.0 sprawdzona przez użytkownika na telefonie (7.11.2026).
Buduje GitHub Actions (`.github/workflows/android.yml`, lokalnie brak Javy/SDK), podpis kluczem z sekretów
`NETPULSE_KEYSTORE_B64|PASSWORD` (plik poza repo: `NetPulse-android-klucz/`), na `main` wydanie `android-v<wersja>`.
Od 0.3.0 po angielsku albo po polsku według języka telefonu (`res/values`, `res/values-pl`). Wersja aplikacji (0.2.1 przyjmuje obie nazwy ciasteczka, 0.4.0 = nazwa UplinkView) osobno: `appVersionName` + `appVersionCode` (+1) w `app/build.gradle.kts`. Telefon testowy: Samsung S10+,
Android 12, instalacja ręczna (bez konta Google Play). Opis: `docs/38-aplikacja-android.md`.

## Wykresy (przebudowa w stylu Grafany)

Plan etapów A–C: `docs/22-wykresy.md` (wzory: folder `graf/`, poza repo). Etap A ✅ (0.26.0): widget `chart` ma `queries`
(do 6 źródeł, 12 serii; `offset_min` = porównanie z godziną/dniem/tygodniem wcześniej – parametr `offset` w API metryk),
osie lewa/prawa, progi, legendę lista/tabela z min/maks/śr./ostatnią, stos. Stary format (`source`, `series`, `y_max`)
zamienia `upgrade_chart` w `layout_schemas.py` (i `upgradeChartConfig` w panelu). Render: `components/charts/PanelChart.tsx`
+ `ChartLegend.tsx` + czyste funkcje `panelData.ts`; edytor: `components/widgets/ChartEditor.tsx`. Pulpit publiczny
przepuszcza `offset` tylko taki, jaki ma zapytanie. Etap B ✅ (0.27.0): widgety `stat` (liczba z mini-wykresem), `bargauge`
(paski), `table`, `state_timeline` (oś stanów); dane: `api/panels.py` (`/api/collections/{kind}`, `/api/states`), panel:
`components/widgets/PanelWidgets.tsx` + `PanelEditors.tsx`, `lib/panels.ts`. Etap C ✅ (0.28.0): swobodna siatka
(`x`, `y`, `h` na widgecie, `w` 1–12; `components/DashboardGrid.tsx` z react-grid-layout, `placeWidgets` układa stare
pulpity), sekcje zwijane (`type: "section"`). Etap D ✅ (0.32.0): powiększanie zaznaczeniem (`ZoomLayer.tsx`, `zoom` w `lib/refresh.tsx`,
API pyta o samo okno), wspólny kursor (`charts/chartSync.ts`), linki z tabel, pasków i mapy (`rowLink`). Etap E ✅ (0.33.0): liczba jako wskaźnik i ze zmianą (`display`, `max`, `show_change`),
pełny ekran (`WidgetExpandContext`), menu „⋯” z eksportem CSV/PNG (`WidgetActions.tsx`, `linesToCsv`). Etap F ✅ (0.34.0): zdarzenia na osi czasu
(`api/events.py` + `timeline.py`: restarty z `uptime_s`, przełączenia WAN). **Od 0.49.0 wykresy nie rysują zdarzeń** – kafelek `events`
(„Zdarzenia”) i alerty `wan_switch` / `device_restart` (trwają 10 min, bez powiadomienia o końcu). Od 0.36.0 jeden silnik
wykresów: `ChartCard` też rysuje `PanelChart` (stary `TimeSeriesChart` usunięty). Mapa cieplna ✅ (0.37.0): widget `heatmap`
(godzina × dzień tygodnia albo data, `lib/heatmap.ts`, dane tydzień po tygodniu z API metryk). Wykres kołowy ✅ (0.39.0): widget `pie` – urządzenie, potem co monitorować (zajętość, udział, stan; `lib/pie.ts`); od 0.40.0 jeden wybrany port (obciążenie albo odbierane / wysyłane) z danymi na żywo. Podgląd panelu bez serwera: atrapa `frontend/dev/mock-api.mjs` + `.claude/launch.json` (dla `Accept-Language: en` dane po angielsku – tablica `EN`).
README: `README.md` po angielsku i `README.pl.md` po polsku (0.79.1) – **zmiana w obu**; zrzuty w `docs/img/` odświeża
`frontend/dev/screenshots.mjs` (Chrome headless kontra atrapa, w Git Bash `MSYS_NO_PATHCONV=1`).

## Nowy wygląd panelu (0.42.0)

Wariant A „klasyczny jasny” (szarości i biel, grafitowy akcent, Inter w paczce, menu z grupami) i nowy pulpit
domyślny z widgetami `status`, `alerts`, `checks` oraz tabelą urządzeń (`display: "table"`). Nowy widget = też
wpis w `layout_schemas.py` i ścieżki w `resolve()` (pulpit publiczny). Opis: `docs/06-projekt-panelu.md`
(„Nowy wygląd”). Wykresy w stylu B (0.43.0): akcent niebieski + szary, dalej stonowana paleta, tokeny `--state-*`
dla stanów. Od 0.44.0 okno „Dodaj widget” z szablonami (według rodzaju i według urządzenia, cała sekcja urządzenia):
`lib/widgetTemplates.ts` – nowy szablon = wpis tam (zbudowany widget musi przejść schemat `layout_schemas.py`).
Panel na prawdziwym serwerze sprawdzam w podglądzie przeglądarki, gdy użytkownik sam się w nim zaloguje.
Od 0.53.0 widgety skalują treść z kartą: komórka siatki `np-cell` (+ `np-fit` przy stałej wysokości) jest kontenerem
zapytań, style w `index.css` (klasy `np-*`), legenda wykresu ustępuje miejsca (`charts/legendFit.ts`). Nowy widget =
dodać mu klasy `np-*`, jeśli ma rosnąć z kartą. Etap 3 ✅ (0.54.0): swobodna siatka od 720 px szerokości siatki,
pary w dwóch kolumnach z tego samego rzędu (`pairsInColumns`). Etap 4 ✅ (0.56.0): widgety z listą (`AUTO_HEIGHT`)
w podglądzie wydłużają się do treści (`OverflowWatch`, `rowsFor`, `pushDown`), w edycji przycisk „Dopasuj wysokość”;
nowy widget z listą = dopisać do `AUTO_HEIGHT`. Opis: `docs/29-responsywnosc-widgetow.md`.
Od 0.58.0 wygląd „Błękit” (wybrany przez użytkownika z projektów na płótnie): niebieski akcent `#1f6feb`/`#4c9bff`,
chłodne tła, font Geist + Geist Mono w paczce, karty 16 px, kolor wykresu 8 = błękit (druga seria). Tekst w kolorze
akcentu = `text-accent-text` (nie `text-accent` – za mały kontrast na `bg-accent-soft`). Opis: `docs/06-projekt-panelu.md`.
Od 0.66.0 (etap 3 planu `docs/40`): tabela urządzeń bez przewijania (kolumny znikają z szerokością karty), paski dostępności
kolorują dzień dopiero poniżej 99 %, mapa sieci z plakietkami (ruch, klienci) i układem poziomym (`layoutTopology(…, "horizontal")`),
skrót stanu sieci w menu (`lib/status.ts`), paleta poleceń Ctrl+K (`lib/palette.ts`, `CommandPalette.tsx` – strony z rejestru
modułów trafiają do niej same). **Widget, który może być pusty = `EmptyHint` (`ui.tsx`), nie `return null`.**
Od 0.58.1 menu w grupach Monitoring / Zdarzenia / Integracje / System – pole `group` w `modules.tsx` (nowa integracja = `"integrations"`). Grupa według przeznaczenia, nie źródła danych: Klienci (z UniFi) są w Monitoringu (0.58.4).

## Do sprawdzenia później

- **Wykrywanie urządzeń – reszta** – części A i B zrobione w 0.73.0 (`docs/43`); wysyłka raportu do serwera projektu
  (sposób B z `docs/24`) dopiero z chmurą. Skan z kontenera API sprawdzony na obu serwerach (13.11.2026).
- **Własne OID-y, przeglądarka MIB, profile YAML** – propozycja w `docs/25-wlasne-oid-propozycja.md` (tylko dokument,
  4.11.2026). Hybryda: drivery zostają, dochodzą własne metryki SNMP (tabela `metrics`), przeglądarka MIB (`pysmi`)
  i profile urządzeń w YAML. Nie wdrażać bez decyzji użytkownika.
- **Plan testów na różnym sprzęcie** – propozycja w `docs/26-plan-testow-sprzetu.md` (4.11.2026): ryzyka R1–R10
  (liczniki 32-bit, interfejsy techniczne w driverze ogólnym, brak roli WAN, zmiana `ifIndex`, duże urządzenia,
  NAS, ARM), etapy 1–5. Etap 1 ✅ (0.77.0): `tests/test_robustness.py`, fixture `broken-agent.snmprec`; poprawione
  NUL i za długie teksty (wywracały zapis urządzenia), prędkość 2³²−1, zawinięcie Counter32 z dolnej połowy,
  limit czasu odczytu urządzenia (`NETPULSE_POLL_TIMEOUT`), polskie błędy pysnmp (`ERROR_HINTS`). Etapy 2–5 czekają na decyzję.
- **Synology NAS** – propozycja w `docs/27-synology-propozycja.md` (4.11.2026, z przewodnika Synology SNMP MIB Guide –
  PDF poza repo): driver `synology` (rozpoznanie sondą `modelName`, dyski, RAID, UPS, I/O, alerty), potem moduł DSM API
  (Hyper Backup, pakiety, kontenery). Odłożone – brak prawdziwego Synology do zrzutu; nie wdrażać bez decyzji.
- **Źródła producentów (MIB, OID, API)** – `docs/28-zrodla-producentow.md` (4.11.2026): oficjalne MIB-y i API
  UniFi, MikroTik (MIB per wersja), Omada (MIB EAP i switchy L2, Open API). Etap A ✅ (0.51.0): driver `omada` rozpoznaje
  bramy ER/DR/FR (też 4 cyfry), WAN `eth0.<VLAN>` i LAN `br-lan`, czyta CPU/RAM, PoE i SFP switchy z oficjalnego MIB
  (zrzuty syntetyczne `tplink-jetstream`, `tplink-er7206` – czekają na prawdziwy sprzęt). Etap D ✅ (0.52.0): oficjalne API UniFi dla urządzeń bez SNMP i zajętość kanału AP. Etapy B–C czekają na decyzję.
- **Plan działania** – `docs/40-plan-dzialania.md` (12.11.2026, po analizie wydajności, bezpieczeństwa i wyglądu):
  etapy 1 wydajność (gzip, kompresja TimescaleDB), 2 bezpieczeństwo (podpisane wydania, rola bazy, CSP), 3 wygląd,
  4 angielski, 5 wykrywanie, 6 publikacja (nazwa ✅ UplinkView, 13.11.2026), 7–8 funkcje, 9 chmura. Etap 1 ✅ (0.67.0), etap 2 ✅ (0.68.0, 0.69.0), etap 3 ✅ (0.66.0, widok na telefonie 0.76.1), etap 4a ✅ (0.74.0, panel po angielsku), 4b ✅ (0.75.0, komunikaty backendu), 4c ✅ (0.76.0, powiadomienia, raport, Android; `docs/44`), etap 5 ✅ (0.73.0).
- **Chmura producenta** – propozycja architektury w `docs/39-chmura-propozycja.md` (12.11.2026, tylko dokument):
  łącznik wychodzący (kontener `cloud`, WSS, parowanie kodem, logowanie podpisem), tunel panelu + skrót stanu
  (historia zostaje u użytkownika), push przez chmurę; etapy C0–C6. Nie wdrażać bez decyzji.
- **MikroTik**: ✅ (0.28.2) sprawdzony na prawdziwym RouterOS 7.18.2 (CHR w VirtualBox, 192.168.1.62) – fixture
  `mikrotik-chr.snmprec`, rozpoznawanie WAN po nazwie portu. Od 0.50.0 czujniki, PoE i SFP według **oficjalnego
  MIKROTIK-MIB 7.25.1** (tabela `metrics`, `GET /api/devices/{id}/sensors`, źródła wykresów `snmp_sensor|snmp_poe|snmp_sfp`,
  alerty `temp_c` i `sfp_rx_dbm`; opis w `docs/12-mikrotik-omada-snmp.md`). Fizyczny routerboard (kilka rdzeni, PPPoE,
  czujniki, PoE, SFP) dalej tylko na syntetycznym `mikrotik-hex.snmprec`.
- **API RouterOS i API kontrolera Omada** – robić dopiero z prawdziwym sprzętem (razem z weryfikacją MikroTika).
- **Proxmox – reszta na prawdziwym sprzęcie** – PVE 9.2.24 (192.168.1.86, VM 100 + LXC 101, kopia LXC 101) działa;
  po 0.28.5 sprawdzić „ostatnia kopia” LXC 101 w panelu i alert „brak świeżej kopii” po 36 h bez nowej kopii.
- **Wersja 0.9.0 na serwerze** – użytkownik jeszcze nie potwierdził `uplinkview update` i działania: karta serwera
  UplinkView, serwery Linux przez SNMP, reguły alertów dla dysku i błędów portów, powiadomienia webhookiem.
