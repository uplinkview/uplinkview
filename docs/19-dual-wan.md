# Dual WAN – dwa łącza internetowe i failover (0.19.0)

Router może mieć dwa (lub więcej) łącza do internetu, np. światłowód jako łącze główne i LTE jako zapasowe.
W trybie **failover** ruch idzie łączem głównym, a gdy ono padnie, router przełącza go na zapasowe.
UplinkView pokazuje, które łącze działa, którym idzie teraz ruch, kiedy nastąpiło przełączenie i jaka jest
dostępność (SLA) każdego łącza.

## Co jest w panelu

| Miejsce | Co pokazuje |
|---------|-------------|
| Widget **Aktywny WAN** | Porty WAN routera i ich stan. Zielona kropka: łącze jest w użyciu (idzie nim ruch). Czerwona: łącze nieaktywne – pusta to łącze zapasowe gotowe do przejęcia ruchu, pełna to awaria. Nad listą: „Teraz: …”, czyli łącze, którym idzie ruch. |
| Widget **Aktywne łącze WAN** | Wykres z osobną linią dla każdego WAN-u. Linia łącza jest rysowana tylko wtedy, gdy szedł nim ruch, więc po awarii WAN 1 linia WAN 2 zaczyna się w chwili przełączenia. Pod wykresem są pasy stanu każdego łącza (zielony – w użyciu, jasnoczerwony – zapas, czerwony – awaria) i lista ostatnich przełączeń. |
| Widget **SLA łączy WAN** | Dostępność każdego łącza w % za 24 godz., 7 albo 30 dni (przełącznik w karcie), liczba przerw, łączny czas przerw, najdłuższa przerwa, ile czasu łącze niosło ruch i ostatnia przerwa (albo trwająca). |
| Widget **Zużycie transferu** (od 0.82.0) | Ile danych pobrano i wysłano przez WAN **dziś** i **w tym miesiącu** (albo w okresie od wybranego dnia), słupki dzień po dniu, przy kilku łączach – podział na łącza. Opcjonalnie pakiet w GB (np. internet mobilny): pasek wykorzystania i prognoza na koniec okresu. Opis niżej: „Zużycie transferu”. |
| **Ustawienia → Łącza WAN** | Które porty routera są WAN 1, WAN 2… Kolejność to priorytet: WAN 1 to łącze główne. |

Widgety dodaje się jak inne: Dashboard → Edytuj pulpit → Dodaj widget. W ustawieniach widgetu można wybrać router
(gdy jest ich kilka), a dla wykresu pobieranie albo wysyłanie, zakres czasu i wysokość.

## Konfiguracja: które porty są WAN 1 i WAN 2

1. Port, który driver rozpoznaje jako WAN (na UCG Ultra `eth4`), UplinkView dodaje sam jako **WAN 1** przy pierwszym
   odczycie routera.
2. Drugie łącze dodajesz w **Ustawienia → Łącza WAN → Dodaj łącze**: router, port (np. `LAN 4 (eth3)`, jeśli ten port
   ustawiłeś w UniFi jako WAN 2) i nazwa (np. „LTE”). Strzałkami ustawiasz kolejność, potem **Zapisz**.
3. Port ustawiony jako łącze WAN dostaje w UplinkView rolę WAN. Jego ruch wlicza się do kafelków i wykresu ruchu WAN,
   trybu „Na żywo” i alertów progowych WAN, a na liście portów ma nazwę łącza.
4. Od pierwszego zapisu w panelu UplinkView nie dodaje już sam portów WAN, bo możesz celowo usunąć któryś port z listy.
   Usunięcie łącza kasuje jego historię i SLA.

**Podpowiedź z kontrolera (od 0.47.0).** Gdy kontroler UniFi zgłasza łącze WAN bramy, którego nie ma na liście
(np. nowo podłączony internet mobilny ustawiony w UniFi jako WAN 2 na porcie 4), na stronie Łącza WAN pojawia się
podpowiedź z numerem łącza w UniFi, portem i stanem oraz przyciskiem **Dodaj**. Port trafia na listę; potem sprawdź
kolejność i kliknij **Zapisz**. UplinkView zapamiętuje porty WAN zgłoszone przez kontroler (`app_settings`, klucz
`wan_detected:<id routera>`), API: `GET /api/wan/suggestions`.

Zmiany zapisuje tylko administrator. Stan łączy odświeża się w następnym cyklu kolektora (co 30 s).

## Skąd wiadomo, że łącze działa i że jest aktywne

Co cykl kolektora (30 s) UplinkView ustala dla każdego łącza dwie rzeczy.

**Sprawne (up).** Port ma link (`ifOperStatus` = up z SNMP), a kontroler UniFi, jeśli coś o łączu wie, nie zgłasza
awarii. UniFi sprawdza też, czy przez łącze jest internet, więc wykrywa awarię u operatora nawet wtedy, gdy kabel
jest podłączony i link jest „up”.

**W użyciu (active)** – którym łączem idzie ruch. Źródła informacji, od najważniejszego:

1. **Kontroler UniFi** (moduł UniFi włączony i kontroler dodany w Ustawienia → Kontrolery UniFi). Z `stat/device`
   bramy UplinkView czyta pola `wan1`/`wan2` (czy łącze działa), `uplink` (interfejs, którym idzie teraz ruch) i porty
   oznaczone `is_uplink`. Ta informacja jest ważna przez 90 s, potem UplinkView przechodzi na metodę 2.
2. **Ruch z SNMP** (zawsze dostępny). Jeśli sprawne jest tylko jedno łącze, to ono jest aktywne, nawet nocą bez ruchu.
   Jeśli sprawne są oba, aktywne jest to, którym idzie ruch: łącze zapasowe w trybie failover przenosi tylko małe
   pakiety kontrolne. Za aktywne uznawane jest łącze z ruchem od 50 kb/s i co najmniej 20% ruchu najbardziej
   obciążonego łącza. Dlatego przy równoważeniu obciążenia (load balance) aktywne są oba łącza naraz. Gdy w sieci
   jest cisza, zostaje łącze, które było aktywne wcześniej.

**Kilka routerów.** Kolejność łączy jest wspólna dla wszystkich routerów (od 0.46.0). Gdy WAN 1 jest na jednym
routerze, a WAN 2 na drugim, ruch niesie router z działającym łączem o najwyższym priorytecie: dopóki WAN 1 działa,
jest w użyciu, a WAN 2 na drugim routerze jest zapasem (źródło decyzji `priority`). Gdy WAN 1 przestanie działać
(brak linku, awaria wg kontrolera albo router nie odpowiada), w następnym cyklu ruch przejmuje WAN 2; po powrocie
WAN 1 ruch wraca na nie. Przełączenie między routerami widać na wykresie i w zdarzeniach jak każde inne.
Próbki dwóch routerów mają różne znaczniki czasu, więc przełączenie liczy się ze stanu łączy w czasie, a zmiany
bez pełnego cyklu odczytu pomiędzy (drugi router dowiaduje się o przełączeniu w kolejnym cyklu) to jedno przełączenie (od 0.46.1) – na wykresie jedna kreska.

Stany łącza: **w użyciu** (zielony), **nieaktywne – zapas** (czerwony pusty), **nie działa** (czerwony pełny),
**brak danych** (szary – router nie odpowiada na SNMP albo kolektor nie działa).

## Zużycie transferu (0.82.0)

Licznik dzienny i miesięczny dla portów z rolą WAN (te same porty co ruch WAN na pulpicie: WAN 1, WAN 2…).

- **Skąd bajty.** Każda próbka kolektora to średnia prędkość portu z 30 s, więc bajty = prędkość × 30 s ÷ 8, zsumowane
  po próbkach. Po pominiętym odczycie (przerwa do 2 min) kolektor dzieli przedział na części po 30 s
  (`rates.sample_times`), więc nic nie ginie, a suma zgadza się z UniFi (porównanie sum bajtów WAN z 13.11.2026: 0,1–1 %).
  **Ograniczenie:** po dłuższej przerwie w odczytach routera (router nie odpowiadał na SNMP, restart kolektora)
  kolektor zapisuje jedną próbkę, więc ruch z tej przerwy jest zaniżony; restart routera zeruje liczniki i ruchu
  z chwili restartu nie da się odtworzyć.
- **Dzień i miesiąc** liczone w strefie czasowej serwera (TZ), od północy.
- **Początek okresu**: 1. dzień miesiąca (miesiąc kalendarzowy) albo dowolny dzień 1–28, jak u operatora, który liczy
  pakiet np. od 15. dnia. Licznik okresu zaczyna od zera w tym dniu.
- **Pakiet** (opcjonalnie, GB, pobrane + wysłane): pasek wykorzystania (pomarańczowy od 80 %, czerwony od 100 %)
  i prognoza na koniec okresu z dotychczasowego tempa (od 2. dnia okresu).
- **Starsze dane**: surowe próbki są trzymane `retention_days` (domyślnie 30 dni); część okresu starsza niż one pochodzi
  z agregatu godzinowego (średnia × 3600 s).
- API: `GET /api/wan/usage?reset_day=1&device_id=` → `total_today`, `total_period`, `ports` (dziś i okres na port),
  `days` (każdy dzień okresu do dziś), `period_start`, `next_period_start`. Kod: `backend/netpulse/usage.py`,
  `api/wan.py`, panel `components/widgets/WanUsageWidget.tsx`. Na pulpicie publicznym widget działa z ustawionym
  routerem i dniem startu okresu.

## Jak liczone jest SLA

- Każda próbka (co 30 s) obowiązuje do następnej, najdłużej 90 s. Dłuższa luka to **brak danych**: nie liczy się
  ani do dostępności, ani jako przerwa. Panel podaje, ile czasu było bez danych.
- **Dostępność** = czas, w którym łącze było sprawne ÷ czas, dla którego są dane × 100%. Wynik nie jest zaokrąglany
  w górę, więc 99,999% pokazuje się jako 99,99%, a nie 100%. Kolor: zielony od 99,9%, pomarańczowy od 99%, poniżej czerwony.
- **Przerwa** to ciągły odcinek, w którym łącze nie działało. Liczba przerw, łączny czas, najdłuższa i ostatnia
  przerwa dotyczą wybranego okresu (24 godz., 7 albo 30 dni).
- Łącze zapasowe, które czeka bez ruchu, jest sprawne. Jego SLA to gotowość, a nie czas pracy. Czas pracy pokazuje
  pole „Niosło ruch”.

Historia jest trzymana tak długo jak inne metryki (`NETPULSE_RETENTION_DAYS`, domyślnie 30 dni).

## Pingi łączy i kolor łącza zapasowego (0.55.0)

**Pingi każdego łącza, także zapasowego.** Serwer UplinkView nie może sam pingować przez łącze zapasowe (ruch idzie
łączem aktywnym), więc pingi mierzy brama UniFi. W `stat/device` każda brama podaje dla każdego WAN-u opóźnienie
(`wan1.latency`, `wan2.latency`), dostępność (`availability`) i wyniki pingów do serwerów monitorujących
(`uptime_stats.WAN`/`WAN2.monitors`, typ `icmp`, np. `google.com`, `1.1.1.1`). Kolektor UniFi zapisuje je co cykl
do tabeli `metrics` dla urządzenia bramy:

| Metryka | Klucz | Co to jest |
|---------|-------|------------|
| `wan_latency_ms` | interfejs łącza (np. `eth4`) | opóźnienie łącza według bramy |
| `wan_availability_percent` | interfejs łącza | dostępność łącza według bramy |
| `wan_ping_ms` | `eth3 · google.com` | średni ping łącza do jednego serwera |

Na wykresie: źródło **Łącze WAN: ping bramy do internetu** (`wan_latency`: opóźnienie, dostępność) albo **Łącze WAN: ping bramy do serwera**
(`wan_ping`) – wybierasz bramę, potem łącze (np. „GSM (eth3)”) i kolor serii. Wymaga modułu UniFi i kontrolera.

**Inny kolor ruchu, gdy internet idzie łączem zapasowym.** W ustawieniach wykresu (`chart`) opcja „Inny kolor, gdy
internet idzie łączem zapasowym” (`wan_backup: true`). Wykres pobiera wtedy `/api/wan/history` i odcinki, w których
w użyciu było łącze inne niż WAN 1, maluje kolorem łącza zapasowego (pomarańczowy, tokeny `--chart-backup`,
`--chart-backup-2`; ECharts `visualMap` po czasie). Nad legendą pojawia się próbka „łącze zapasowe”. Pulpit
publiczny przepuszcza `/api/wan/history`, gdy jakiś wykres ma tę opcję.

## API

| Metoda i adres | Co zwraca |
|----------------|-----------|
| `GET /api/wan/status` | łącza z bieżącym stanem (`active`, `standby`, `down`, `unknown`), ruchem, czasem zmiany stanu i źródłem decyzji (`controller`/`traffic`/`priority`); `active_ids` – łącza w użyciu |
| `GET /api/wan/history?minutes=60` | punkty wykresu (`in_<id>`, `out_<id>` – ruch łącza tylko wtedy, gdy było aktywne), odcinki stanów (`segments`) i przełączenia (`switches`) |
| `GET /api/wan/sla?days=7` | dla każdego łącza: `availability`, `outages`, `down_s`, `longest_outage_s`, `active_s`, `unknown_s`, `recent_outages` |
| `GET /api/wan/links` | konfiguracja łączy |
| `PUT /api/wan/links` | zapis pełnej listy `{"links": [{"interface_id": 8, "name": "Światłowód"}, …]}` w kolejności (administrator) |

## Dla programisty

- Baza: `wan_links` (konfiguracja i bieżący stan, pola `ctrl_*` od kontrolera) i hypertable `wan_link_metrics`
  (`up`, `active`, `in_bps`, `out_bps` co cykl), migracja `0006_wan_links.py`.
- `backend/netpulse/wan.py` – czyste funkcje: `decide` (stan łączy w cyklu), `segments`, `compute_sla`, `switches`.
- `backend/netpulse/wan_links.py` – zapis w transakcji kolektora SNMP (`record`, `mark_unknown`) i dane od kontrolera
  (`apply_controller`, wywoływane przez `unifi_collector.py`).
- `backend/netpulse/unifi.py` – `parse_wans`: porty WAN bramy z `stat/device`. Starsze odpowiedzi nie mają `ifname`
  przy portach, wtedy port N to `ethN-1` (tak jest na UCG Ultra i UDM). `tools/probe2fixtures.py` zachowuje teraz
  pola `wan1`/`wan2`/`uplink` (bez adresów IP).
- Testy: `tests/test_wan.py` (logika, parser UniFi), `tests/test_wan_db.py` (kolektor na zrzucie UCG Ultra, awaria
  WAN 1 → WAN 2, API), panel: `frontend/src/pages/Wan.test.tsx`.

## Stan

**Sprawdzone na prawdziwym sprzęcie 11.11.2026 (0.65.9):** UCG Ultra z UniFi OS 6.0.17, WAN 1 = `eth4`, internet
mobilny jako WAN 2 („GSM”) na `eth3`, kontroler z kluczem API; dwie instancje UplinkView naraz (serwer lokalny i VPS).

- Awaria WAN 1 (kabel wyjęty na 27 min): przełączenie na GSM w pierwszym cyklu (≤ 30 s), alerty „Port WAN wyłączony”
  i „Przełączenie WAN: WAN 1 → GSM”, ruch zapisany na GSM bez przerw.
- Powrót: alert portu zakończony sam, „Przełączenie WAN: GSM → WAN 1”. Brama przerzuca ruch z powrotem dopiero po
  sprawdzeniu łącza (jeszcze ok. 30 s na GSM, gdy WAN 1 już działa).
- Kontroler: `wan1`/`wan2` mają `ifname`, `uplink` tylko `name` (`eth4`) – parser to obsługuje. Pingi bramy każdym łączem
  (`uptime_stats.WAN`, `WAN2`), też zapasowym: WAN 1 ok. 11 ms, GSM ok. 120–200 ms.
- Zrzut: `tests/fixtures/unifi_gateway_dual_wan.json` (zanonimizowany `stat/device` bramy, `probe2fixtures.device_fixture`),
  test `test_wan.py::test_real_ucg_ultra_dual_wan_from_controller`.
- Krótkie mignięcia (< 30 s) widać tylko wtedy, gdy trafi w nie odczyt – dwie instancje z innym momentem cyklu
  zobaczą różne mignięcia. Możliwa poprawka: `ifLastChange` (IF-MIB) między odczytami.
