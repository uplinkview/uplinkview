# Własne OID-y, przeglądarka MIB i profile urządzeń – propozycja

Status: **propozycja** (4.11.2026). Nic z tego nie jest jeszcze zrobione. Do decyzji użytkownika.

## Problem

Dziś każdy OID, który UplinkView odczytuje, jest wpisany w kodzie drivera (`backend/netpulse/drivers/*.py`). Żeby
pokazać na wykresie coś, czego driver nie zna (czujnik temperatury, licznik sesji, stan zasilacza, wartość z MIB-u
producenta), trzeba napisać kod i wydać nową wersję. Przy aplikacji instalowanej przez innych to nie wystarczy:
użytkownicy mają sprzęt, którego nie mamy.

Pytanie było: czy przebudować aplikację tak, żeby wykresy powstawały wprost z pobranych OID-ów?

## Odpowiedź w skrócie

**Nie zamiast obecnej budowy, tylko obok niej (hybryda).** Sam OID nie wystarcza do sensownego wykresu:

- **liczniki** (`ifHCInOctets`, Counter32/64) trzeba zamieniać na wartość na sekundę z obsługą przepełnienia
  i restartu urządzenia – kolektor już to robi dla portów,
- **indeksy tabel** (`.5`) nic nie znaczą bez połączenia z kolumną nazwy (`ifName`, `ifAlias`, opis czujnika),
- **jednostki i skale** różnią się między producentami (dziesiąte części stopnia, b/s albo Mb/s, procent albo ułamek),
- **znaczenie**: alerty (port down, przełączenie WAN, urządzenie offline), topologia LLDP, łącza WAN, szablony
  widgetów i pulpit publiczny muszą wiedzieć, *czym* jest wartość, a nie tylko gdzie leży.

Tak robią też Zabbix, LibreNMS i Grafana ze `snmp_exporter`: gotowe szablony dla znanych rzeczy plus możliwość
dodania własnego OID-u. Obecne drivery zostają, dochodzą trzy warstwy opisane niżej.

## Skąd brać MIB-y i OID-y

| Źródło | Co daje | Uwagi |
|---|---|---|
| MIB-y standardowe IETF (IF-MIB, HOST-RESOURCES, UCD-SNMP, ENTITY, ENTITY-SENSOR, BRIDGE, LLDP, POWER-ETHERNET) | to, co obsługuje prawie każde urządzenie | w net-snmp, paczce `snmp-mibs-downloader`, do skompilowania przez `pysmi` |
| Ubiquiti (UBNT-MIB, UBNT-UniFi-MIB) | VAP-y, radia, część stanu | strona pobierania UniFi |
| MikroTik (MIKROTIK-MIB) | czujniki, zdrowie, kolejki, PPPoE | strona MikroTika albo eksport z RouterOS |
| TP-Link Omada | zależnie od modelu | strona wsparcia modelu |
| Prometheus `snmp_exporter` (`generator.yml`, `snmp.yml`) | gotowe zestawy OID-ów z typami | **Apache 2.0** – można się wzorować |
| LibreNMS (`mibs/`, definicje YAML) | ogromny zbiór MIB-ów i definicji urządzeń | definicje na **GPLv3** – nie kopiować |
| oidref.com, mibs.observium.org | szybkie sprawdzenie, co znaczy OID | tylko do podglądu |

**Najważniejsze źródło to `snmpwalk` z prawdziwego urządzenia.** MIB mówi, co *może* istnieć; urządzenie
implementuje zwykle część (UniFi ma PoE w MIB-ach, ale go nie zwraca). Obecny sposób pracy – zrzut,
anonimizacja (`backend/tools/walk2snmprec.py`), fixture `.snmprec`, driver – zostaje i jest podstawą każdej warstwy.

## Warstwa 1 – własne OID-y na urządzeniu

Strona urządzenia → **Własne metryki** (albo Ustawienia → Urządzenia → urządzenie):

- pola: nazwa wyświetlana, **OID** (skalar albo kolumna tabeli), **typ** (wartość chwilowa / licznik → na sekundę /
  stan z mapą wartości, np. `1 = ok, 2 = błąd`), **jednostka**, **mnożnik** (np. `0.1`), dla tabel – **OID kolumny
  z nazwą wiersza** (np. opis czujnika); opcjonalnie filtr wierszy (wyrażenie na nazwie),
- przycisk **Sprawdź** – odczyt na żywo i podgląd kilku wierszy z wyliczoną wartością, zanim się zapisze,
- limit, np. 50 OID-ów na urządzenie i 500 wierszy na tabelę, żeby nie przeciążyć urządzenia ani bazy.

Zapis:

- nowa tabela `custom_oids` (migracja `0012`): urządzenie, nazwa, OID, typ, jednostka, mnożnik, OID nazwy wiersza,
  mapa stanów, włączona; poprzednie wartości liczników trzymane jak przy portach,
- wartości do istniejącej ogólnej tabeli `metrics` (jak dane agenta): `name = "custom_<id>"`, `key` = nazwa
  wiersza (dla skalara `""`); retencja i agregaty godzinowe jak dla `metrics`,
- kolektor SNMP odczytuje je w tym samym cyklu co 30 s, jednym `GET`/`GETBULK` na urządzenie.

Panel:

- edytor wykresu: nowe źródło **„SNMP – własne”** (wybór urządzenia i metryki, potem wiersze), działa też w widgetach
  `stat`, `bargauge`, `table`, `heatmap`, `state_timeline` (typ „stan”),
- alerty: reguła na metryce `custom_<id>` z progiem i filtrem wiersza w `match` (mechanizm już jest dla agenta),
- pulpit publiczny: nowe ścieżki w `resolve()` w `api/public.py`, nowy kształt w `layout_schemas.py`.

To największy zysk przy najmniejszej pracy: **dowolny sprzęt z SNMP da się wykreślić bez nowego drivera.**
Wersja: minor.

## Warstwa 2 – przeglądarka MIB

Na stronie urządzenia → **Przeglądaj SNMP**:

- UplinkView robi walk wybranej gałęzi (domyślnie: system, IF-MIB, HOST-RESOURCES, ENTITY-SENSOR, UCD, gałąź producenta
  z `sysObjectID`), z limitem czasu i liczby wartości,
- wynik jako drzewo z **nazwami i opisami z MIB-ów**: standardowe MIB-y w paczce (skompilowane przez `pysmi` do JSON-a
  przy budowaniu obrazu), MIB-y producenta wgrywane przez użytkownika (Ustawienia → MIB-y, kompilacja na serwerze),
- przy każdej wartości: typ z MIB-u (`Counter64`, `Gauge32`, `INTEGER` z wyliczeniem), jednostka z opisu,
  przycisk **Dodaj jako metrykę** – wypełnia formularz z warstwy 1 (typ, mapa stanów, kolumna nazwy wiersza dla tabel).

Dzięki temu użytkownik nie musi znać OID-ów. Wersja: minor. Zależy od warstwy 1.

Do sprawdzenia: licencje paczkowanych MIB-ów (standardowe IETF są swobodne; producentów – raczej tylko wgrywane
przez użytkownika, nie w repo).

## Warstwa 3 – profile urządzeń w YAML

Proste rzeczy producentów (rozpoznanie po `sysObjectID`/`sysDescr`, skalary i tabele czujników, CPU/RAM, ukrywanie
interfejsów, etykiety portów) opisane danymi zamiast kodu, np. `backend/netpulse/profiles/mikrotik.yaml`:

```yaml
match:
  sys_object_id: ["1.3.6.1.4.1.14988.1"]
hide_interfaces: ["lo", "bridge*"]
metrics:
  - name: temperature
    oid: 1.3.6.1.4.1.14988.1.1.3.100.1.3   # mtxrGaugeValue
    label_oid: 1.3.6.1.4.1.14988.1.1.3.100.1.2
    type: gauge
    scale: 0.1
    unit: "°C"
```

- profil korzysta z tego samego silnika co warstwa 1 – własne metryki to w praktyce „profil jednego urządzenia”,
- **logika złożona zostaje w Pythonie**: role portów i WAN, VAP-y UniFi, LLDP, liczenie przepływu portów,
- drivery przenosimy stopniowo, przy okazji kolejnego producenta (prawdziwy MikroTik, Omada), każdy na fixtures w CI,
- nowy model = jeden plik, także od społeczności (zgłoszenie z raportem z `docs/24-wykrywanie-propozycja.md`, część B).

Wersja: minor na każdy przenoszony driver. Najmniej pilne.

## Czego nie robić

- **Nie zastępować driverów surowymi OID-ami** – stracilibyśmy alerty, WAN, topologię i szablony.
- **Nie odczytywać całego drzewa SNMP co 30 s** – obciąża urządzenia (zwłaszcza AP i małe switche) i bazę.
- **Nie kopiować definicji z LibreNMS** (GPLv3).

## Kolejność (gdy zapadnie decyzja)

1. Warstwa 1 – własne OID-y (tabela, kolektor, źródło wykresu, alerty, pulpit publiczny), test na prawdziwym sprzęcie:
   np. temperatura z UCG Ultra albo czujniki z MikroTika CHR.
2. Warstwa 2 – przeglądarka MIB ze standardowymi MIB-ami, potem wgrywanie MIB-ów producenta.
3. Warstwa 3 – profile YAML, zaczynając od MikroTika przy weryfikacji fizycznego routerboardu.

## Pytania otwarte

- Czy własne metryki mają być też dostępne dla urządzeń bez SNMP (agent, Proxmox) – na razie tylko SNMP.
- Limity (liczba OID-ów, wierszy) – stałe czy ustawiane w panelu.
- Czy paczkować MIB-y producentów, czy tylko wgrywać – zależy od ich licencji.
