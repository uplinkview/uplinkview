# Wykrywanie urządzeń i zgłaszanie specyfikacji – propozycja

Status: części A i B **zrobione w 0.73.0** (13.11.2026, decyzja użytkownika) – opis wdrożenia: `docs/43-wykrywanie-urzadzen.md`.
Sposób wysyłki: A (plik + link do zgłoszenia). Sposób B (wysyłka do serwera projektu) dalej czeka na chmurę.

## Problem

Kupowanie każdego urządzenia, żeby dodać jego pełne wsparcie (driver producenta), jest kosztowne. Potrzebny jest
sposób, żeby system sam znajdował urządzenia w sieci i żeby użytkownicy mogli łatwo przekazać „specyfikację”
urządzenia, którego UplinkView jeszcze dobrze nie zna.

Ważne: nieznane urządzenie już dziś działa – driver ogólny (IF-MIB) obsługuje każde urządzenie z SNMP (porty,
ruch, błędy, stan). Driver producenta dokłada tylko szczegóły (nazwy portów, CPU, WiFi, czujniki).

## Część A – wykrywanie urządzeń w sieci

Ustawienia → Urządzenia → **Wykryj** (także jako krok kreatora `/setup`):

- skan wskazanej podsieci (np. `192.168.1.0/24`): ping (jest już w `netpulse/checks.py`), potem SNMP
  `sysDescr`, `sysObjectID`, `sysName` z podanym community albo danymi v3,
- lista wyników: adres, nazwa, producent, wykryty driver, oznaczenie „ogólny – brak pełnej specyfikacji”,
  „już w UplinkView”,
- **użytkownik zaznacza, co dodać** – bez automatycznego dodawania na start (w domu SNMP mają też drukarki,
  telewizory, NAS-y); automat jako opcja później, np. „dodawaj nowe routery i switche”,
- skan w tle w kolektorze albo API, z limitem równoległości i czasu; wyniki ważne kilka minut.

Wersja: minor. Korzysta z istniejących `snmp`/`drivers` (wybór drivera po `sysObjectID`/`sysDescr`).

## Część B – „Pomóż dodać to urządzenie” (raport specyfikacji)

Uzupełnione 4.11.2026: pełny przepływ od użytkownika do wydania nowej wersji.

### Kiedy UplinkView proponuje raport

Na stronie urządzenia komunikat „UplinkView zna to urządzenie tylko częściowo” i przycisk **Przygotuj raport**, gdy:

- pasuje tylko driver ogólny (`generic`) albo ogólny `linux` przy `sysObjectID` spoza net-snmp,
- `sysObjectID` nie występuje w żadnym fixture ani profilu,
- producent jest znany, ale model lub wersja firmware nie (lista znanych modeli przy driverze / profilu).

Komunikat można ukryć dla urządzenia („nie pokazuj więcej”).

### Co robi UplinkView u użytkownika

1. **Zrzut SNMP** ważnych gałęzi: system, IF-MIB, HOST-RESOURCES, ENTITY, ENTITY-SENSOR, UCD, BRIDGE, LLDP
   i gałąź producenta z `sysObjectID`. **Dwa zrzuty w odstępie ok. 60 s** – widać, które wartości to liczniki.
2. **Limity**: liczba wierszy na tabelę (tablice MAC, ARP, trasy, sesje skracane do kilku wierszy), łączny czas
   i rozmiar; plik spakowany.
3. **Anonimizacja od razu na serwerze użytkownika** – jak `backend/tools/walk2snmprec.py`: MAC-i, adresy IP, SSID,
   numery seryjne, `sysName`, `sysContact`, `sysLocation`, `ifAlias`; community i klucze v3 nigdy nie trafiają do
   raportu. Testy anonimizacji w CI (żadna wartość z listy wrażliwych nie przechodzi).
4. **Formularz**: co to za urządzenie (model, firmware, jeśli UplinkView ich nie odczytał), uwagi użytkownika,
   np. „port 5 to WAN”, „to NAS z dwoma dyskami w RAID 1”.
5. **Podgląd całej treści przed wysłaniem** i wyraźna zgoda.

Raport zawiera też: wersję UplinkView, wybrany driver, `sysObjectID`, `sysDescr` (zanonimizowany), czas zrzutu.

### Jak raport trafia do właściciela

| Sposób | Plusy | Minusy |
|---|---|---|
| **A. Plik do pobrania + link do gotowego zgłoszenia na GitHubie** (szablon issue „Nowe urządzenie”, pola wypełnione z raportu) | bez serwera, za darmo, jawne, od razu | użytkownik potrzebuje konta GitHub i sam dołącza plik (link ma limit długości), zgłoszenie publiczne |
| **B. Przycisk „Wyślij do UplinkView”** – mały serwis pośredniczący (funkcja serverless z aplikacją GitHub) zakłada zgłoszenie w prywatnym repo | jedno kliknięcie, bez konta, raporty prywatne | serwis do utrzymania, polityka prywatności, zgoda, ochrona przed spamem i limit zgłoszeń |
| C. E-mail | prosty | trudny do obsługi, łatwo coś zgubić |

**Rekomendacja:** najpierw **A**. **B** razem z chmurą i po decyzji o modelu biznesowym
– automatyczna wysyłka danych z cudzej sieci wymaga zgody i ustalenia
administratora danych. UplinkView zapamiętuje, że raport dla urządzenia został przygotowany / wysłany.

### Co dzieje się u właściciela

1. Zgłoszenie z etykietą `nowe-urządzenie` (szablon w `.github/ISSUE_TEMPLATE/`).
2. Raport → fixture `backend/tests/fixtures/<model>.snmprec` (zrzut już zanonimizowany, przed dodaniem do repo
   jeszcze raz sprawdzony narzędziem).
3. Rozpoznanie i obsługa: profil YAML (`docs/25-wlasne-oid-propozycja.md`, warstwa 3 – najszybciej) albo driver
   w Pythonie, gdy potrzebna logika (role portów, WAN, WiFi); test drivera na fixture w CI.
4. Wydanie nowej wersji (patch dla nowego modelu znanego producenta, minor dla nowego producenta), wpis
   w macierzy zgodności (`docs/26-plan-testow-sprzetu.md`, etap 5).
5. Zgłoszenie zamknięte z informacją „obsługiwane od wersji X.Y.Z”.

### Co dzieje się u użytkownika po aktualizacji

Panel pokazuje „dostępna aktualizacja”; po `uplinkview update` (albo z panelu) urządzenie z driverem `auto` **samo**
dostaje nowy driver – wybór drivera odbywa się przy każdym odczycie (`poll_device`). Komunikat o raporcie znika.
Historia ruchu portów zostaje (te same `ifIndex`).

### Ryzyka i ograniczenia

- **Jeden raport nie zawsze wystarczy** – ten sam model na innym firmware zachowuje się inaczej, część rzeczy widać
  tylko pod obciążeniem. Potrzebna możliwość dopytania zgłaszającego (komentarze w zgłoszeniu) i drugiego raportu.
- **Rozmiar** – gałąź producenta może mieć dziesiątki tysięcy wartości; limity z punktu 2.
- **Anonimizacja musi być pewna** – podgląd przed wysłaniem i testy w CI; w razie wątpliwości wartość usuwamy.
- **Czas reakcji** – do wydania nowej wersji użytkownik ma tylko driver ogólny. Lukę zmniejszają własne OID-y
  (`docs/25-wlasne-oid-propozycja.md`, warstwa 1).
- **Zgłoszenia publiczne (A)** – zrzut to dane, nie kod; w szablonie zgoda na użycie zrzutu w repo jako fixture.

## Taniej niż kupowanie sprzętu

Routery wirtualne z SNMP w VirtualBoxie, jak MikroTik CHR (`mikrotik-chr.snmprec`): OpenWrt x86, pfSense,
OPNsense, VyOS. Sprzęt fizyczny potrzebny głównie do PoE, czujników i WiFi.

## Kolejność (gdy wrócimy)

1. Część A (wykrywanie) – od razu przydatne dla każdej instalacji.
2. Część B (raport) – korzysta z tego samego odczytu SNMP.
3. Szablon zgłoszenia na GitHubie i strona właściciela (fixture, profil/driver, wydanie).
4. Wysyłka do serwera projektu (sposób B) – razem z chmurą.
