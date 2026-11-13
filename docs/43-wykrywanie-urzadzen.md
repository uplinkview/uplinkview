# Wykrywanie urządzeń i raport urządzenia (0.73.0)

Etap 5 planu (`docs/40-plan-dzialania.md`, „pierwsze 5 minut”) – części A i B propozycji `docs/24-wykrywanie-propozycja.md`.
Sposób wysyłki raportu: **A** (plik do pobrania + link do gotowego zgłoszenia na GitHubie). Bez automatycznej wysyłki.

## Część A – wykrywanie w sieci

Gdzie: kreator `/setup` (krok „Urządzenia”, wykrywanie jest pierwsze, formularz ręczny pod przyciskiem „Dodaj urządzenie
ręcznie”) i Ustawienia → Urządzenia → **Wykryj w sieci** (bez urządzeń panel jest widoczny od razu).

1. Podsieć podpowiada `GET /api/discovery/suggest`: najczęstsza /24 wśród dodanych urządzeń, a bez nich – /24 adresu
   przeglądarki (tylko adresy prywatne).
2. `POST /api/discovery/scan` (`network`, port i dane SNMP jak przy dodawaniu urządzenia): CIDR (`192.168.1.0/24`),
   zakres (`192.168.1.10-60` albo pełne adresy) lub jeden adres, najwyżej /22 (1024 adresy).
3. **SNMP v1/v2c – jedno gniazdo UDP** (`discovery.scan_community`): zapytanie GET o `sysDescr`, `sysObjectID`, `sysUpTime`,
   `sysName` do każdego adresu (paczki po 32, 5 ms przerwy), odpowiedzi zbierane 2 s, druga runda tylko do milczących.
   Pakiety koduje i dekoduje pysnmp (`pysnmp.proto.api`), odpowiedź z inną community jest odrzucana. Cała /24 – ok. 4–5 s.
   Pierwsza wersja z osobnym klientem pysnmp na adres trwała 78 s i przy 64 klientach naraz nie znalazła nic
   (sprawdzone 13.11.2026 w sieci użytkownika) – stąd jedno gniazdo.
4. **SNMPv3** – klienci pysnmp, po 8 naraz (`discovery.scan`), limit czasu 2 s; wolniej, ale v3 w domu to rzadkość.
5. Rozpoznanie (`discovery.describe`): ten sam wybór drivera co w kolektorze (`detect_driver` po `sysObjectID`/`sysDescr`)
   i `enrich_system` drivera bez odczytu portów – model, firmware, rodzaj (router / switch / AP / serwer / inne).
   Na driverze ogólnym producent z numeru w `sysObjectID` (`ENTERPRISES`: Synology, HP, Cisco, QNAP…), net-snmp (8072)
   nic nie mówi. Oznaczenia: „już w UplinkView” (adres jest w bazie), „podstawowa obsługa” (driver `generic`).
6. Panel zaznacza od razu nowy sprzęt sieciowy (driver UniFi / MikroTik / Omada / OPNsense albo rodzaj router/switch/AP), resztę
   (drukarki, NAS-y, telewizory) – tylko na życzenie. Nazwa = `sysName` (do zmiany w wierszu). „Dodaj zaznaczone” wysyła
   kolejno `POST /api/devices` z danymi SNMP skanu i `driver = "auto"` (jak formularz – z testem SNMP).

Skan i dodawanie – tylko administrator (POST, domyślna reguła ról). Skan niczego nie zapisuje.

**Sprawdzone 13.11.2026 w sieci użytkownika** (192.168.1.0/24, z komputera w LAN): 4,4 s, znalezione 3 z 254:
UCG-Ultra (router, UCG-Ultra 6.0.17), USW (switch), U6+ (AP, 6.7.54.15663) – driver `unifi`, rodzaje zgodne.

## Część B – raport urządzenia

Gdzie: strona urządzenia SNMP (administrator). Przy driverze `generic` karta „UplinkView zna to urządzenie tylko częściowo”
z przyciskiem „Przygotuj raport”, przy pozostałych – dyskretny link na dole strony.

`POST /api/devices/{id}/report?interval=30` (`netpulse/devreport.py`, bez zapisu, trwa ok. `interval` + odczyt):

- gałęzie: system, IF-MIB (`ifTable`, `ifXTable`), HOST-RESOURCES (`hrSystem`, `hrStorage`, `hrDevice`), ENTITY
  (`entPhysicalTable`), ENTITY-SENSOR, UCD (pamięć, dyski, load, CPU), BRIDGE `dot1dBase`, LLDP (lokalne i sąsiedzi),
  POWER-ETHERNET i **gałąź producenta** z `sysObjectID` (bez net-snmp 8072 i UCD 2021); limity na gałąź (gałąź
  producenta 8000), razem 30 000 wartości, 90 s na odczyt;
- **nie czyta** tablic adresowych: MAC (FDB), ARP, tras, procesów, klientów WiFi (UniFi `41112.1.6.1.3`, MikroTik
  `14988.1.1.1.2`);
- typy wartości jak w `.snmprec` (`PySnmpClient.walk_typed` – Counter64 = 70, Gauge32 = 66 itd.);
- drugi odczyt po `interval` – w raporcie tylko wartości liczbowe, które się zmieniły (`walk2_changes`): widać liczniki.

Anonimizacja (`devreport.Anonymizer`, spójna – ten sam adres zawsze daje ten sam zastępczy):

| Co | Na co |
|---|---|
| `sysName`, nazwa lokalna LLDP | `device` (także w innych tekstach) |
| `sysContact`, `sysLocation` | `homelab` |
| `ifAlias`, alias i asset ID ENTITY | `alias-<indeks>` |
| numery seryjne (ENTITY, MikroTik) | `SERIAL` |
| SSID | `ssid-N`; wewnętrzne UniFi `element-*`/`vwire-*` zachowują przedrostek (po nim driver je ukrywa) |
| sąsiedzi LLDP | `neighbor-N`, opisy ich portów `port` |
| MAC (wartości binarne, tekst `aa:bb:…`, indeksy tabel) | `02:…` (lokalnie administrowany, z SHA-256) |
| IPv4 (wartości IpAddress, tekst, 4-bajtowe wartości, znane adresy w indeksach) | `198.18.x.y` (zakres testowy RFC 2544); 0.0.0.0, maski, 127.x zostają |
| adresy e-mail | `user@example.com` |

Nazwa, która jest częścią `sysDescr` (np. `UCG-Ultra` w „Ubiquiti UniFi UCG-Ultra 6.0.17”), to model – nie jest
zastępowana. Community, klucze SNMPv3 i adres urządzenia nigdy nie trafiają do raportu.

Sprawdzone 13.11.2026 na UCG Ultra, USW Lite 8 PoE i U6+: 724 / 411 / 1234 wartości, ok. 11 s (z odstępem 10 s);
w raportach 0 adresów 192.168.*, 0 prawdziwych MAC-ów, brak nazw urządzeń i SSID.

W panelu: podgląd (gałęzie z liczbą wartości, pierwsze 400 wierszy zrzutu), pola „Model i wersja firmware” i „Uwagi”,
**Pobierz raport** (`uplinkview-report-<sysObjectID>-<data>.json` z uwagami) i **Zgłoś na GitHubie** – link do szablonu
`.github/ISSUE_TEMPLATE/nowe-urzadzenie.yml` z wypełnionymi polami (model, sysObjectID, sysDescr, driver, wersja, uwagi);
plik użytkownik dołącza sam (link ma limit długości).

Format pliku: `format = "netpulse-device-report"`, `format_version = 1`, `walk` i `walk2_changes` w formacie `.snmprec`
(`OID|typ|wartość`) – `walk` od razu nadaje się na fixture `backend/tests/fixtures/<model>.snmprec`.

## Kod

Backend: `netpulse/discovery.py`, `netpulse/devreport.py`, `api/discovery.py`, `PySnmpClient.walk_typed`
(`snmp/client.py`). Panel: `lib/discovery.ts`, `pages/settings/devices/DiscoveryPanel.tsx`, `pages/DeviceReport.tsx`,
`SnmpCredentialFields` (wspólne pola SNMP formularza i skanu, `DeviceForm.tsx`). Testy: `test_discovery.py` (zakresy,
rozpoznanie na fixtures, skan jednym gniazdem kontra atrapa agenta UDP, anonimizacja – żadna z wrażliwych wartości nie
przechodzi), `test_discovery_db.py` (API), `Discovery.test.tsx`.

## Dalej

- Skan z kontenera API działa (sieć `bridge`, NAT hosta) – **sprawdzone 13.11.2026 po aktualizacji do 0.73.0**: serwer domowy
  5,5 s, VPS (przez tunel WireGuard) 4,3 s, na obu UCG-Ultra, USW i U6+; raporty z kontenera 724 / 411 / 1234 wartości, bez adresów
  192.168.* i nazw urządzeń (U6+ zostaje – to model z `sysDescr`).
- Sposób B (wysyłka przyciskiem do serwera projektu) – razem z chmurą (`docs/24`).
- Zapamiętanie „raport przygotowany / wysłany” i „nie pokazuj więcej” – gdy będą pierwsze zgłoszenia.
