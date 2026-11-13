# Projekt panelu (krok 5) i kierunek rozwoju

Dokument opisuje, jak ma wyglądać i działać panel webowy oraz jak go budować, żeby dało się
go rozwijać (w stronę chmury, aplikacji mobilnej z powiadomieniami i widgetów) bez przepisywania.
Decyzje zapadły wspólnie z autorem projektu; zmiany zapisujemy tutaj.

## Założenia produktowe

- UplinkView ma być **pełnoprawną aplikacją webową**, którą każdy instaluje u siebie jedną komendą.
- Panel jest **tylko klientem API**. Wszystko, co robi panel, może zrobić też aplikacja mobilna
  albo chmura (to samo API, te same definicje widgetów).
- Sekcje panelu dochodzą z czasem – menu i ustawienia budujemy jako **rejestr modułów**, a nie na sztywno.

## Wygląd (ustalone)

- Motyw **ciemny i jasny** (domyślnie według systemu, ręczny przełącznik zapamiętany na koncie).
- Główny ekran: **pulpit z kartami** – pasek podsumowania i karty urządzeń z mini-wykresami.
- Menu nawigacji **po lewej**, zwijane do ikon; na telefonie chowane pod przyciskiem.

### Wygląd „Błękit” (od 0.58.0)

Wybrany z dwóch projektów na płótnie (fioletowy „Iris” i „Błękit”), układ bez zmian – zmieniły się kolory, font
i wykończenie. Wszystko przez tokeny w `frontend/src/index.css`, więc kolejną kolorystykę zmienia się w jednym miejscu.

- **Kolory (jasny / ciemny):** tło `#f3f6fa` / `#0a0f18` (chłodne szarości z nutą granatu), karty `#ffffff` / `#111827`,
  akcent niebieski `#1f6feb` / `#4c9bff`. Tekst w kolorze akcentu (linki, zaznaczenia) – token `--accent-text`
  (`text-accent-text`; `#1557c2` / `#8cc0ff`), bo czysty akcent na jasnoniebieskim tle `--accent-soft` miał za mały
  kontrast. Zielony, bursztynowy i czerwony tylko dla stanów – bez zmian znaczenia.
- **Wykresy:** numery kolorów zachowują znaczenie; 1 = akcent niebieski, **8 = błękit** `#0ea5e9` / `#5fd3ff`
  (druga seria i porównanie z „wczoraj”, wcześniej szary). Łącze zapasowe – pomarańcz.
- **Font:** Geist i Geist Mono w paczce (`@fontsource-variable/geist`, `…/geist-mono`; z polskimi znakami, bez internetu).
- **Menu:** w kolorze tła, aktywna pozycja to kafelek w kolorze karty z niebieską ikoną, wersja w niebieskiej plakietce.
  Od 0.58.1 grupy **Monitoring** (pulpit, mapa sieci; Dostępność od 0.58.3 w Ustawieniach), **Zdarzenia** (alerty z plakietką liczby
  niepotwierdzonych – po zwinięciu menu kropka), **Integracje** (od 0.58.4 sam Proxmox – pusta grupa znika) i **System**.
  Grupa to pole `group` w rejestrze `frontend/src/modules.tsx` (`NAV_GROUPS`; bez pola – Monitoring); nowa integracja
  = `group: "integrations"`. Grupa według przeznaczenia strony, nie źródła danych: Klienci (dane z UniFi) od 0.58.4
  w Monitoringu (Dashboard, Klienci, Mapa sieci); Integracje = strony osobnych systemów podglądanych przez UplinkView.
- **Karty** zaokrąglone 16 px (`rounded-2xl`), przyciski i pola 10 px; paski CPU/RAM w tabeli urządzeń – akcent.
- Ikony aplikacji (favicon, PWA) i `theme-color` – niebieskie.

### Nowy wygląd (od 0.42.0 do 0.57.x, wariant A „klasyczny jasny”)

Wybrany z trzech makiet (A klasyczny jasny, B grafitowe menu, C minimalny z menu u góry).

- **Kolory:** szarości i biel (Tailwind `zinc`), grafit jako akcent (przyciski, logo, zaznaczenia).
  Kolor tylko dla stanów: zielony – działa, bursztynowy – ostrzeżenie, czerwony – błąd. Ciemny motyw –
  te same zasady w odcieniach grafitu. Tokeny w `frontend/src/index.css`.
- **Wykresy – styl B (od 0.43.0, wybrany z makiet A grafit / B grafit + akcent / C stonowana paleta):**
  stonowane kolory o dawnym znaczeniu numerów – 1 niebieski akcent (pierwsza seria), 2 zielony, 3 fiolet,
  4 piaskowy = próg ostrzeżenia, 5 ceglasty = próg krytyczny, 6 róż, 7 łupek, 8 szary. Zapisane wykresy zachowują sens
  kolorów (0.43.1: w 0.43.0 kolor 2 był szary i „dobre” wartości wyglądały na wyłączone); nowe wykresy mają drugą serię
  w szarym 8.
  Stany (oś stanów, koło „działa/nie działa”) – osobne tokeny `--state-up|down|unknown`. Liczba w widgecie „liczba”
  w kolorze tekstu, kolor progu tylko po przekroczeniu. Karta wykresu: tytuł i bieżąca wartość pierwszej serii w nagłówku.
- **Font:** Inter dołączony do panelu (`@fontsource-variable/inter`, działa bez internetu), cyfry równej szerokości.
- **Menu:** na całą wysokość, logo na górze, grupy „Monitorowanie” i „System” (do 0.58.0; od 0.58.1 – patrz „Wygląd Błękit”).
  Pasek górny bez ramki, w kolorze tła; na telefonie przycisk menu z logo.
- **Pulpit domyślny** (`DEFAULT_LAYOUT`, szablon „Pełny”): pasek stanu → kafelki z mini-wykresem i szczytem →
  ruch WAN (8) + alerty (4) → tabela urządzeń (8) + dostępność (4). Nowe widgety: `status` (pasek
  „Sieć działa prawidłowo”), `alerts` (ostatnie alerty, aktywne na górze, bez pulpitu publicznego),
  `checks` (sprawdzenia z paskami dzień po dniu, 7 albo 30 dni; od 0.58.2 dzień ≥ 99,9 % zielony, < 99,9 % pomarańczowy, < 95 % czerwony); urządzenia mają `display: "cards" | "table"`
  (stare pulpity – karty). Kod: `components/widgets/OverviewWidgets.tsx`, `DevicesWidget.tsx`, `SummaryWidget.tsx`.
- **Dodawanie widgetu (od 0.44.0, makiety A + B):** okno z zakładkami *Według rodzaju* (grupy Przegląd, Internet i WAN,
  Urządzenie, Port, WiFi, Serwer, Dostępność, Własny) i *Według urządzenia* (pasujące widgety, kilka naraz albo „Cała sekcja”
  urządzenia), wyszukiwarka bez polskich znaków. Szablon pyta tylko o urządzenie, port albo sprawdzenie, ma opcje
  (linia prędkości łącza, porównanie z wczoraj), rozmiar i podgląd na żywo; „Więcej opcji” otwiera pełny edytor.
  Katalog: `frontend/src/lib/widgetTemplates.ts` (każdy szablon buduje zwykły widget – nowy szablon = wpis tam i teksty
  `tpl.<id>` w `pl.ts`), okno: `components/widgets/AddWidgetDialog.tsx`, miniatury `WidgetThumb.tsx`, kilka widgetów
  naraz na górze pulpitu – `addWidgets` w `layout.ts`. Typy do pełnego edytora są w grupie „Własny”.
- Zapisane pulpity zostają jak były – nowy układ pojawia się na pulpicie bez zapisanego układu,
  po „Przywróć domyślny” albo przy nowym pulpicie z szablonu „Pełny”.

## Układ aplikacji

```
┌──────────────────────────────────────────────────────────────┐
│ UplinkView   [odświeżanie ▾] [zakres czasu ▾]      Jan K. ▾    │  pasek górny
├────────────┬─────────────────────────────────────────────────┤
│ Dashboard  │                                                 │
│ Ustawienia │              widoki / widgety                   │
│   Konto    │                                                 │
│   Urządz.  │                                                 │
│   Odśw.    │                                                 │
│   Aktualiz.│                                                 │
└────────────┴─────────────────────────────────────────────────┘
```

- **Pasek górny:** kto jest zalogowany; rozwijane menu konta (Ustawienia konta, Wyloguj);
  globalny wybór interwału odświeżania i zakresu czasu.
- **Menu:** na start `Dashboard` i `Ustawienia`. W Ustawieniach: `Konto`, `Urządzenia`
  (dodawanie z testem SNMP, edycja, usuwanie), `Odświeżanie`, `Aktualizacja`.
- Nowa sekcja (Alerty, Topologia, Klienci WiFi…) = jeden wpis w rejestrze modułów
  (ścieżka, ikona, nazwa, wymagana rola) – bez zmian w układzie aplikacji.

## Widgety i personalizacja wykresów

Pulpit składa się z **widgetów**. Widget to `{ typ, konfiguracja }` zapisana jako JSON
(z numerem wersji schematu), więc ta sama definicja nadaje się później do aplikacji mobilnej.

| Typ widgetu       | Co pokazuje                                          |
|-------------------|------------------------------------------------------|
| `summary`         | podsumowanie sieci (urządzenia, ruch WAN, klienci)   |
| `device-card`     | karta urządzenia: status, mini-wykres, porty         |
| `traffic-chart`   | ruch na wybranych portach (in/out)                   |
| `device-chart`    | CPU, RAM, load urządzenia                            |
| `wifi-chart`      | klienci i ruch sieci WiFi                            |
| `port-table`      | tabela portów ze statusem i prędkością               |
| `wan_status`      | Aktywny WAN: porty WAN routera, które działa, którym idzie ruch (0.19.0) |
| `wan_chart`       | Aktywne łącze WAN: linia każdego WAN-u i pasy stanu, moment przełączenia (0.19.0) |
| `wan_sla`         | SLA łączy WAN: dostępność w %, liczba i czas przerw za 24 godz./7/30 dni (0.19.0) |

Widgety WAN opisuje `docs/19-dual-wan.md`.

Personalizacja wykresu (per widget): tytuł, źródło danych (urządzenie, port, metryka),
zakres czasu, typ (linia, obszar, słupki), kolory serii, jednostki (bit/s lub B/s),
wygładzanie, skala osi, własny interwał odświeżania. Układ pulpitu (kolejność, rozmiar,
dodawanie i usuwanie widgetów) edytowany przeciąganiem. Zapisywane **na koncie użytkownika**
w bazie (nie w przeglądarce), więc działa na każdym urządzeniu.

Od 0.53.0 treść widgetu dopasowuje się do rozmiaru karty (zapytania kontenerowe CSS: liczby, wskaźniki, koła, paski,
oś stanów i listy rosną z kartą), a legenda wykresu w małej karcie przechodzi na prawo, zwija się albo znika.
Od 0.54.0 swobodna siatka działa od 720 px szerokości siatki (laptop ma te same położenia co duży ekran), a dwie kolumny
łączą w pary tylko widgety z tego samego rzędu. Opis: `docs/29-responsywnosc-widgetow.md`.

## Odświeżanie

- Globalny interwał w pasku górnym: wyłączone, 5 s, 10 s, 30 s, 1 min, 5 min (domyślnie 30 s),
  plus przycisk „Odśwież teraz”. Zakres czasu wykresów (15 min – 7 dni) wybiera się na Dashboardzie.
  Każdy widget będzie mógł mieć własny interwał (etap 5e).
- Na razie wybór jest zapamiętywany w przeglądarce; zapis na koncie użytkownika dochodzi
  razem z personalizacją (5e).
- Odświeżanie wstrzymuje się, gdy karta przeglądarki jest w tle.
- Kolektor odpytuje urządzenia co `NETPULSE_POLL_INTERVAL` (domyślnie 30 s), więc odświeżanie
  częstsze niż interwał kolektora nie da nowych danych – panel to zaznaczy.
- Prawdziwe „na żywo” (jak w UniFi) to osobny tryb – patrz niżej, „Tryb Na żywo”.

## Dane na żywo – tylko wykresy kołowe (od 0.40.0)

**Od 0.45.0 (decyzja użytkownika po przeglądzie „Dashboard - Network”):** na żywo są też bieżące wartości, na które
patrzy się „teraz” – kafelki „Pobieranie / Wysyłanie WAN”, wartość w nagłówku wykresu (WAN, port, CPU/RAM urządzenia),
tabele i paski portów (ruch i stan portu) oraz liczby i wskaźniki CPU/RAM urządzenia SNMP. Historia wykresów, mapy,
SLA, oś stanów, ping, WiFi i PoE – dalej z bazy (co 30 s). Jeden wspólny kanał na stronę: `lib/liveHub.ts`
(jedno połączenie na urządzenie, ponowne łączenie co 5 s, `useLiveSample`, `useLiveDeviceSample` – tylko urządzenia
SNMP), ruch WAN – `lib/liveWan.ts` (suma portów łączy z `/api/wan/status`). Przełącznik „Na żywo / Wstrzymane”
w pasku górnym (`LiveToggle`, zapamiętany w przeglądarce, `netpulse.live`), znacznik `LiveBadge` przy wartościach na
żywo. Na pulpicie publicznym – bez kanału (wymaga logowania). Od 0.45.1: kanał łączy się tylko z działającymi
urządzeniami, a szybkość na żywo liczy `LiveRateTracker` (`rates.py`) od ostatniej *zmiany* licznika – UniFi odświeża
liczniki SNMP co kilka sekund i przy odczycie co 1,5 s co drugi pokazywał 0 (sprawdzone na prawdziwym UCG i USW).

**Od 0.72.0** na żywo są też: tabela portów na stronie urządzenia (ruch i stan każdego portu), strona portu (ruch
i stan), obciążenie kabli na mapie sieci (`withLiveEdges` w `lib/topology.ts`, `useLiveDeviceSamples` – układ mapy
liczony z odczytu API, żeby nie przerysowywać go co 1,5 s) i widget VPN (`/api/live/vpn`, opis w `docs/30-vpn.md`).
Granice sprzętu (zmierzone 13.11.2026): UCG Ultra odświeża liczniki WAN (`eth4`) i WireGuard co ~1 s, portów LAN
`eth0`–`eth3` co ~5 s, USW Lite 8 PoE co ~3 s – szybciej niż sprzęt się nie da, `LiveRateTracker` liczy od zmiany licznika.

Historia: 5f dodał przełącznik „Na żywo” przy wykresie ruchu WAN, 0.38.0 (na próbę) – porty WAN z obciążeniem,
tabelę portów urządzenia i wykres na stronie portu. Od 0.40.0 decyzją użytkownika **na żywo działają tylko wykresy
kołowe**; przełączniki przy wykresach, w tabeli portów i na stronie portu zostały usunięte.

- **Które wykresy (urządzenia SNMP):** jeden port („Obciążenie portu”, „Port: odbierane i wysyłane”), porty podłączone /
  odłączone, od 0.41.0 także **CPU, RAM i dyski** (serwer Linux przez SNMP); zapisane wykresy wszystkich portów sprzed
  0.40.0. Co ~1,5 s, w nagłówku znacznik „Na żywo” (tylko gdy próbka faktycznie coś podała).
- **Bez danych na żywo:** serwery z agentem (agent wysyła co 30 s, najczęściej co 10 s), Proxmox (sam liczy statystyki
  co ~10 s), stany urządzeń i sprawdzeń całej sieci (wynik cyklu kolektora i sprawdzeń) – odczyty z bazy.
- **API:** `/api/live/device?device=<id>` (WebSocket, ta sama sesja co reszta API; od 0.41.0, wcześniej
  `/api/live/ports`) – prędkość i stan (`ifOperStatus`) widocznych portów, CPU i RAM tym samym driverem co kolektor
  (`read_health`), dyski (`read_disks`, driver `linux`); `api/live.py`. Wspólne odpytywanie co ~1,5 s, niezależnie od
  liczby wykresów; tylko gdy ktoś ogląda; bez zapisu do bazy. Limit 40 połączeń. CPU z UCD-SNMP-MIB urządzenie
  przelicza samo co kilka sekund, więc zmienia się rzadziej niż ruch.
- **Bez połączenia** (pulpit publiczny – WebSocket wymaga logowania – albo zerwane połączenie) wykres pokazuje odczyty
  kolektora i nie ma znacznika.
- **Uwagi:** jeśli switch odświeża liczniki SNMP rzadziej niż co sekundę, wartości mogą skakać. Obciążenie liczone
  względem prędkości portu (np. 1 Gb/s), nie pakietu u operatora.

## Aktualizacja jednym kliknięciem

Decyzja: **osobny kontener `updater`**. Samo API nie dostaje dostępu do Dockera.

```
panel ──(admin)──► API ──(sieć wewnętrzna, token)──► updater ──► docker compose pull/up
                    │                                  │
                    └──── sprawdza wersję ◄────────────┘ źródło wydań
```

1. API sprawdza najnowsze wydanie w **źródle aktualizacji** i porównuje z zainstalowaną wersją.
   Źródło jest ustawieniem (`NETPULSE_UPDATE_SOURCE`), domyślnie wydania GitHub; później można
   wskazać własny serwer (chmura, subskrypcje) o tym samym formacie manifestu
   (`wersja`, `lista zmian`, `obrazy`).
2. Zakładka **Ustawienia → Aktualizacja** pokazuje: zainstalowana wersja, dostępna wersja,
   lista zmian i przycisk **Aktualizuj** (tylko administrator, z potwierdzeniem).
3. Kliknięcie → API zleca updaterowi aktualizację; panel pokazuje postęp i po restarcie
   usług sam się odświeża.
4. Updater nasłuchuje wyłącznie w sieci wewnętrznej Dockera, wymaga tokenu, potrafi tylko
   ustalone akcje (sprawdź, zaktualizuj, status), a obrazy bierze wyłącznie ze skonfigurowanego źródła.
5. Przed aktualizacją: kopia bazy (`pg_dump`) i możliwość powrotu do poprzedniej wersji, gdy
   nowa nie wystartuje.

Uwaga bezpieczeństwa: dostęp do gniazda Dockera jest równoważny uprawnieniom roota na
serwerze. Dlatego jest wyłącznie w małym, osobnym kontenerze z minimalną powierzchnią,
a ustawienie można wyłączyć (`NETPULSE_UPDATER=off`) – wtedy panel pokazuje tylko komunikat
o nowej wersji i komendę `uplinkview update`.

Warunek wstępny: **gotowe obrazy w rejestrze (GHCR)** zamiast budowania na serwerze użytkownika.

## Przygotowanie pod chmurę, aplikację mobilną i powiadomienia

Nie budujemy tego teraz, ale unikamy decyzji, które by to blokowały:

- **API-first:** panel używa tylko publicznego API; schemat OpenAPI służy do generowania
  klientów (mobilny, chmura). API dostanie prefiks wersji (`/api/v1`) przed pierwszym wydaniem publicznym.
- **Logowanie dla aplikacji mobilnej:** dziś sesja w ciasteczku (przeglądarka). Dojdą
  **tokeny dostępu** (osobne dla urządzeń/aplikacji, do odwołania w panelu) obok ciasteczek.
- **Zdarzenia i powiadomienia:** alerty (krok 8) i „dostępna aktualizacja” trafiają do
  jednego modelu **zdarzeń**; kanały dostarczania to wymienne wtyczki: w panelu, e-mail/webhook,
  push do aplikacji mobilnej (przez przekaźnik w chmurze).
- **Identyfikator instalacji:** każda instalacja ma losowy `instance_id` – potrzebny do
  późniejszego powiązania z chmurą, bez wysyłania czegokolwiek bez zgody użytkownika.
- **Role:** dziś każde konto jest administratorem; model użytkownika ma już `is_admin`,
  dojdzie rola tylko-do-odczytu (np. do wyświetlacza na ścianie).
- **Bez telemetrii:** instalacja niczego nie wysyła na zewnątrz poza sprawdzaniem wydań.

## Dopracowanie wyglądu (0.66.0)

Etap 3 planu z `docs/40-plan-dzialania.md` – bez zmian w API i bazie, sam panel.

- **Tabela urządzeń bez przewijania w bok.** Karta tabeli jest kontenerem zapytań (`@container`): nazwa bierze resztę
  szerokości i skraca się wielokropkiem, a w wąskiej karcie znikają kolejno paski CPU/RAM (same liczby zostają,
  poniżej 560 px), czas pracy (640 px) i adres IP (480 px). Stałe `HOST_COL`, `UPTIME_COL`, `NAME_CELL` w `DevicesWidget.tsx`.
- **Paski dostępności kolorują tylko dni z prawdziwą awarią.** Dzień jest zielony od 99 % (`DAY_OK_PERCENT`, do ok. 14 min
  przerwy), pomarańczowy poniżej 99 %, czerwony poniżej 95 %. Wcześniejszy próg 99,9 % barwił dzień po jednym zgubionym
  pingu. Dymek paska podaje przybliżony czas przerwy (`dayTitle`, `downMinutes`).
- **Mapa sieci.** Węzeł ma plakietki: ruch na kablu w stronę bramy (`uplinkTraffic` – z danych kabli, bez zmian w API),
  liczba klientów WiFi i po kablu; węzeł „Internet” – ruch łącza WAN. Układ poziomy (`layoutTopology(…, "horizontal")`):
  warstwy od lewej do prawej, numery portów nad kablem. Domyślny kierunek z kształtu sieci (`preferredOrientation`:
  więcej warstw niż urządzeń obok siebie i ekran od 1024 px = poziomo), przycisk na mapie przełącza i zapamiętuje wybór
  w przeglądarce (`netpulse.topology.orientation`).
- **Skrót stanu sieci w menu** (`SidebarStatus` w `Sidebar.tsx`): to samo zdanie co pasek stanu na pulpicie, liczba
  urządzeń online i ruch WAN – na każdej stronie; prowadzi do alertów, gdy coś nie działa. Zwinięte menu: kropka
  w kolorze stanu. Logika zdania przeniesiona do `lib/status.ts` (menu nie ładuje pliku widgetów).
- **Puste widgety z podpowiedzią** (`EmptyHint` w `ui.tsx`): czego nie ma, dlaczego i link „dodaj” (na pulpicie publicznym
  bez linku). Urządzenia (brak urządzeń / filtr rodzajów nic nie zostawia), PoE (brak kontrolera UniFi), sprawdzenia,
  paski, tabela i oś stanów bez danych. Widget nie znika już z siatki w trybie edycji. **Nowy widget, który może być
  pusty = `EmptyHint`, nie `return null`.**
- **Paleta poleceń Ctrl+K** (⌘K na Macu; też pole „Szukaj…” w pasku górnym): strony i podstrony Ustawień (według roli
  i modułów), urządzenia, porty i klienci. Szuka bez polskich znaków, każde słowo zapytania musi pasować (nazwa, opis,
  adres IP, MAC, nazwa techniczna portu), strzałki + Enter. Kod: `lib/palette.ts` (czyste funkcje, testy),
  `components/CommandPalette.tsx` – osobny plik pobierany przy pierwszym otwarciu; porty i klientów pobiera dopiero
  wtedy (porty: jedno zapytanie na urządzenie, do 40 urządzeń). **Nowa strona w rejestrze modułów trafia do palety sama.**
- Atrapa `frontend/dev/mock-api.mjs` pokazuje wersję z `package.json` i realistyczną dostępność (pojedyncze dni z awarią).

### Widok na telefonie (0.76.1)

Ostatni punkt etapu 3:

- **Pasek górny mieści się w 360 px** (wcześniej 402 px przy ekranie 375 px – konto wychodziło za krawędź). Poniżej 640 px
  nie ma przełącznika motywu ani listy interwału odświeżania: oba są w menu konta (`UserMenu`, część `sm:hidden`),
  obok został sam przycisk „odśwież teraz”. Avatar bez strzałki. Przełącznik „Na żywo” ma podpis od 400 px szerokości
  (węższy ekran – sama kropka). Miejsce zostaje na plakietkę aktualizacji.
- **Mini-wykresy w kafelkach podsumowania na całą szerokość.** Kafelek węższy niż 240 px (dwa w rzędzie na telefonie)
  rysuje mini-wykres pod liczbą (`.np-sum-row` w `index.css`, `@container` kafelka) – obok liczby ściskał się do kilku
  pikseli albo znikał przy dłuższej wartości („8,52 Mb/s”). Linia rozciąga się na szerokość (`preserveAspectRatio="none"`).
- Atrapa API: wersja „dostępnej aktualizacji” to następna wersja minor zamiast 9.9.9, raport miesięczny i raport urządzenia
  podają bieżącą wersję z `package.json` – zrzuty do README bez retuszu.

## Technologia

| Warstwa       | Wybór                                                                 |
|---------------|-----------------------------------------------------------------------|
| Aplikacja     | React 19 + TypeScript, Vite, React Router                             |
| Wygląd        | Tailwind CSS, motyw ciemny/jasny przez zmienne CSS, ikony Tabler      |
| Dane          | TanStack Query (odświeżanie, cache), klient generowany z OpenAPI      |
| Wykresy       | Apache ECharts                                                        |
| Układ pulpitu | react-grid-layout (przeciąganie i zmiana rozmiaru widgetów)           |
| Tłumaczenia   | i18n od początku (domyślnie polski, angielski później)                |
| Dostarczanie  | Node tylko w etapie budowania obrazu; gotowe pliki serwuje kontener API |

### Ładowanie na żądanie (od 0.36.1)

- Każda strona z rejestru `frontend/src/modules.tsx` to osobny plik JS (`page(() => import(…), "Nazwa")` →
  `React.lazy`), `Suspense` w `Shell.tsx` pokazuje „Ładowanie…” przy pierwszym wejściu. Plik pulpitu pobierany
  od razu po starcie (pierwszy ekran po zalogowaniu). Nowa strona = wpis przez `page()`, nie zwykły import.
- Leniwie też: edytor widgetów (`WidgetEditDialog` – dopiero w trybie edycji), pulpit publiczny, ECharts
  (`PanelChart`, przy pierwszym wykresie).
- `vite.config.ts` (`codeSplitting`): biblioteki React/router/TanStack w pliku `vendor`, ikony w `icons` – po
  aktualizacji UplinkView przeglądarka ma je w pamięci (API wysyła `/assets` jako `immutable`).
- Efekt: kod startowy 795 kB → ok. 100 kB (+ `vendor` 294 kB, raz na zawsze); po kompresji 222 kB → ok. 130 kB
  razem z bibliotekami. Podgląd zbudowanej wersji: konfiguracja `panel-build` w `.claude/launch.json`
  (`npm --prefix frontend run preview`, API z atrapy).

## Etapy budowy (krok 5)

| Etap | Zakres                                                                                     |
|------|--------------------------------------------------------------------------------------------|
| 5a ✅ | Szkielet aplikacji: pasek górny, menu, motyw, ekran logowania z kreatorem, wbudowanie w obraz API |
| 5b ✅ | Dashboard: pasek podsumowania, karty urządzeń, wykres ruchu, interwały odświeżania          |
| 5c ✅ | Ustawienia: Konto (zmiana hasła), Urządzenia (dodaj/edytuj/usuń z testem SNMP), Odświeżanie |
| 5d   | Aktualizacja: sprawdzanie wersji, kontener updater, przycisk Aktualizuj (wymaga obrazów GHCR) |
| 5e   | Personalizacja: edytor widgetów, układ pulpitu, opcje wykresów zapisywane na koncie         |
| 5f   | Tryb „Na żywo”: WebSocket, ruch WAN co 1–2 s, wykres w czasie rzeczywistym (kolejność względem 5d/5e do ustalenia) |

Przed pierwszym wydaniem publicznym dodatkowo: migracje bazy (Alembic), prefiks `/api/v1`,
obrazy w GHCR i README dla obcych użytkowników.

## Pomysły na później (backlog)

Rubryka na pomysły, które jeszcze nie mają etapu. Dopisujemy tu nowe pomysły, a gdy któryś
dojrzeje, dostaje numer etapu w tabeli wyżej. Kolumna „Zgłoszone” pozwala wrócić do tematu,
gdy ktoś zapyta „co jeszcze chcieliśmy zrobić”.

| Pomysł | Opis | Gdzie w panelu | Zgłoszone |
|--------|------|----------------|-----------|
| Wskaźnik siły hasła ✅ wdrożone (2026-10-25, podpowiedź bez twardej reguły) | Przy ustawianiu i zmianie hasła pokazuje na żywo, czy hasło spełnia wymagania: liczba znaków, cyfry, wielkie litery, znaki specjalne (każdy warunek jako ✓/✗ pod polem, plus pasek siły). Ten sam komponent w kreatorze pierwszego konta i w Ustawienia → Konto. | Kreator konta, Ustawienia → Konto | 2026-10-24 |
| Monitorowanie serwerów Linux | Serwer jako urządzenie w panelu: CPU, RAM, dyski, obciążenie, sieć. Etap 1 przez SNMP (`snmpd`), etap 2 własny agent z usługami systemd, kontenerami Docker i SMART. | Dashboard (karty), Ustawienia → Urządzenia, alerty | 2026-10-24 |
| Alerty w panelu | Reguły z progami (np. ruch, błędy, CPU/RAM, zajętość dysku, port down, urządzenie offline), lista aktywnych i historii alertów, wskaźnik w pasku górnym. To rozwinięcie etapu 8. | Pasek górny (dzwonek), nowa sekcja Alerty, Ustawienia → Alerty | 2026-10-24 |
| Stan serwera UplinkView | Parametry maszyny, na której działa aplikacja: CPU, RAM i swap, obciążenie, dyski (zajętość, miejsce pod bazę), czas pracy, temperatura, rozmiar bazy, stan usług UplinkView. Z historią na wykresach. | Dashboard (karta „Serwer”), Ustawienia → System | 2026-10-25 |
| Kreator dashboardów: prywatny i publiczny ✅ wdrożone (0.23.0, opis: `docs/20-szczegoly-i-pulpity.md`) | Kreator tworzenia własnych dashboardów (nazwa lub szablon, wybór i układ widgetów, widoczność). **Prywatny** widzi tylko administrator po zalogowaniu, **publiczny** otwiera się pod osobnym adresem bez logowania (tylko do odczytu, np. wyświetlacz ścienny, podgląd dla domowników). | Dashboard (lista i przełącznik dashboardów), Ustawienia → Dashboardy, publiczna strona poza powłoką aplikacji | 2026-10-25 |
| Powiadomienie o aktualizacji w pasku górnym ✅ wdrożone (2026-10-25) | Po automatycznym, cyklicznym sprawdzeniu wydań (bez klikania „Sprawdź”) pasek górny pokazuje wyraźną informację, że jest nowa wersja (np. plakietka „Dostępna aktualizacja 0.7.0” z linkiem do Ustawienia → Aktualizacje), żeby użytkownik nie przegapił, gdy zapomni zajrzeć. Wymaga cyklicznego sprawdzania po stronie API (np. co kilka godzin) i zapamiętania wyniku; można dać „odłóż/ukryj tę wersję”. W Ustawienia → Aktualizacje przełącznik **„Automatycznie sprawdzaj aktualizacje”** (domyślnie włączony; po wyłączeniu nic nie jest odpytywane i pasek nie pokazuje plakietki, zostaje ręczne „Sprawdź”) oraz wybór częstotliwości sprawdzania; ustawienie na poziomie instalacji, nie konta, bo sprawdza API. Po wprowadzeniu alertów (etap 8) ta sama informacja trafi też do dzwonka. | Pasek górny, Ustawienia → Aktualizacje | 2026-10-25 |

### Propozycje z przeglądu projektu (2026-10-25)

Pomysły zebrane po etapach 5–7, poza pozycjami z tabeli wyżej. Nic z tego nie jest jeszcze zaplanowane;
kolejność rekomendowana jest na końcu.

**Niezawodność i bezpieczeństwo**

- **Migracje Alembic.** Dziś zmiana kolumny w istniejącej tabeli wymaga `uplinkview reset` (utrata historii).
  Blokuje też agenta Linux i część alertów. Największy dług techniczny.
- **Kopia zapasowa i przywracanie z panelu.** Updater robi kopię bazy przy aktualizacji, ale nie ma przycisku
  „pobierz kopię” ani „przywróć”.
- **Szyfrowanie sekretów w bazie.** Community SNMP, klucze SNMPv3 i klucz API UniFi leżą jawnym tekstem;
  wystarczy klucz szyfrujący z `.env`.
- **Role: administrator i tylko do odczytu.** Pole `is_admin` już jest; brakuje zaproszeń domowników i widoku bez zmian.
- **Dziennik zdarzeń (audit log).** Kto dodał urządzenie, zmienił hasło, uruchomił aktualizację. Przyda się też
  przy dashboardach publicznych.

**Dane i monitoring**

- ✅ (0.20.0) **Strona szczegółów urządzenia:** porty, PoE, klienci, wykresy CPU i RAM, historia dostępności w jednym widoku.
- ✅ (0.20.0 port, 0.21.0 klient) **Strony szczegółów portu i klienta.** Historia ruchu i błędów portu; dla klienta czas połączenia i sygnał w czasie
  (klienci są dziś tylko zdjęciem stanu, bez historii).
- ✅ (0.20.0) **Dostępność (uptime) w procentach** z `device_metrics.reachable`, np. „switch 99,98% w 30 dni”.
- ✅ (0.20.0, godzinowe) **Agregaty długoterminowe.** Ciągłe agregaty TimescaleDB (godzinowe, dobowe) dałyby wykresy na rok przy małej bazie
  (surowe dane trzymamy 30 dni).
- **Raport tygodniowy:** zużycie WAN, najwięcej ruchu, awarie, najsłabszy sygnał; opcjonalnie mailem.
- **Wykrywanie nowych urządzeń w sieci:** skan 192.168.1.0/24 ze SNMP i propozycja „dodaj to urządzenie”.
- **Test prędkości łącza** (cyklicznie) i opóźnienie do internetu (ping do 1.1.1.1 i bramy). SNMP tego nie daje.

**Alerty i powiadomienia**

- ✅ (0.9.0 webhook, 0.25.0 ntfy i e-mail) **Kanały powiadomień:** e-mail, webhook, Telegram/ntfy. Opis: `docs/21-powiadomienia.md`.
- ✅ (0.25.0) **Ciche godziny i grupowanie** (awaria switcha nie powinna dać dwudziestu wiadomości).
- **Nowy klient w sieci** (nieznany MAC) i „spadek liczby klientów WiFi do zera” jako typy alertów.

**Panel i obsługa**

- **Wyszukiwarka globalna** (urządzenie, port, klient po nazwie, IP albo MAC).
- **Eksport do CSV** z wykresu i listy klientów.
- **Interfejs po angielsku** (i18n jest przygotowane), ważne, jeśli ktoś inny ma to instalować.
- ✅ (0.22.0) **Kreator pierwszej konfiguracji:** po założeniu konta „dodaj pierwsze urządzenie, community, test”, zamiast komendy w terminalu.
- **PWA** (instalowalna na telefonie) przed prawdziwą aplikacją mobilną.

**Integracje i sprzęt**

- **Eksport do Prometheus/OpenMetrics** (Grafana dla tych, którzy ją mają).
- **Home Assistant** (integracja albo MQTT): stan sieci i klientów w automatyzacjach.
- **MikroTik i Omada** (etap 9): popularne w homelabach, ale wymagają sprzętu do testów.
- **Zarządzanie PoE z panelu** (włącz/wyłącz port, restart odbiornika). Pierwszy zapis do sieci zamiast samego odczytu,
  więc wymaga najpierw ról i dziennika zdarzeń.

**Jakość kodu i wydania**

- **Testy w przeglądarce (Playwright)** dla głównych ścieżek: testy komponentów nie wykryją np. nakładania się elementów mapy sieci.
- **Automatyczne wydania:** tag, changelog i notatki wersji z commitów, żeby plakietka aktualizacji pokazywała sensowne opisy.
- **Dokumentacja użytkownika końcowego** osobno od notatek projektowych w `docs/`.

**Rekomendowana kolejność:** Alembic → kanały powiadomień (e-mail/webhook/ntfy) → strona szczegółów urządzenia →
kopia zapasowa z panelu → test prędkości i ping. Pierwsze odblokowuje resztę, drugie czyni alerty użytecznymi,
trzecie jest najbardziej widoczne w codziennym użyciu.

### Szczegóły: kreator dashboardów (prywatny i publiczny)

- **Kreator (kroki):** 1) nazwa i szablon wyjściowy (np. „Pełny przegląd”, „Tylko ruch WAN”, „Status urządzeń”,
  „Wyświetlacz ścienny”, pusty); 2) wybór i układ widgetów z rejestru widgetów (ten sam co w etapie 5e);
  3) widoczność: **Prywatny** (tylko administrator) albo **Publiczny** (bez logowania) z opcjami prywatności;
  4) podsumowanie z linkiem do skopiowania i kodem QR. Edycja później tym samym kreatorem.
- **Publiczny dashboard:** adres w osobnej przestrzeni (np. `/p/<losowy-token>`), strona bez menu i paska
  użytkownika, tylko odczyt. Link z nieodgadywalnym tokenem, który można w każdej chwili **unieważnić lub wymienić**,
  opcjonalna data wygaśnięcia i opcjonalne hasło (PIN). Tryb ekranu pełnego bez elementów sterujących
  (wyświetlacz ścienny, telewizor), z odświeżaniem nie częściej niż co 10 s.
- **Bezpieczeństwo (to jest sedno pomysłu):**
  - Osobny, **tylko do odczytu** interfejs API dla publicznych dashboardów (np. `/api/public/dashboards/{token}`),
    który zwraca wyłącznie dane widgetów wybranych w tym dashboardzie. Nie korzysta z ciasteczek sesji
    i nie wystawia pozostałego API. Lista dozwolonych widgetów jest jawna (biała lista), a nowe widgety są
    domyślnie niedostępne publicznie, dopóki ktoś ich nie oznaczy.
  - **Opcje prywatności publicznego widoku:** ukryj adresy IP i MAC, nazwy sieci WiFi i opisy portów,
    zaokrąglij wartości, nie pokazuj błędów urządzeń. Domyślnie wszystko ukryte. Publiczny widok nigdy nie
    pokazuje community, haseł, tokenów, wersji oprogramowania ani informacji o aktualizacjach.
  - **Globalny wyłącznik** w Ustawienia → Dashboardy: „Zezwalaj na dashboardy publiczne”, **domyślnie wyłączony**.
    Dopóki nie jest włączony, kreator oferuje tylko prywatne.
  - Ograniczenie liczby żądań (per adres i per token), pamięć podręczna odpowiedzi (kilka sekund), żeby publiczny
    link nie obciążał serwera ani bazy; nagłówki `noindex`, `Cache-Control`, `Referrer-Policy: no-referrer`;
    osadzanie w `<iframe>` tylko po jawnym włączeniu (`frame-ancestors`).
  - Dziennik: kto, kiedy i który dashboard upublicznił, wymienił token albo wyłączył. Ostrzeżenie w kreatorze,
    że **publiczny link ujawnia dane o sieci każdemu, kto go ma**, oraz że panel nie powinien być wystawiony
    wprost do internetu: dostęp z zewnątrz tylko przez VPN albo reverse proxy z HTTPS.
- **Prywatny dashboard:** dostępny po zalogowaniu wyłącznie dla administratora. Gdy pojawią się role (tylko do
  odczytu), prywatny może być współdzielony z wybranymi użytkownikami; to osobna decyzja.
- **Model danych:** nowa tabela `dashboards` (nazwa, właściciel, widoczność, token publiczny, ustawienia
  prywatności, wygaśnięcie, skrót hasła, JSON z układem i widgetami w wersjonowanym schemacie z etapu 5e).
  Nowa tabela powstaje sama przy `uplinkview update` (bez migracji Alembic). Ten sam model posłuży aplikacji
  mobilnej i widgetom.
- **Zależności:** etap 5e (rejestr widgetów, edytor układu, zapis na koncie), etap 5f (tryb „Na żywo” może
  napędzać wyświetlacz ścienny), ograniczanie liczby żądań w API (nie ma go jeszcze).
- **Decyzje do podjęcia:** czy publiczny link ma być chroniony tylko tokenem, czy domyślnie także hasłem;
  które widgety mogą być publiczne w pierwszej wersji (na start np. podsumowanie, ruch WAN, liczba klientów
  WiFi, stan urządzeń bez adresów); czy dopuścić wiele publicznych dashboardów naraz; czy dashboard główny
  (domyślny po zalogowaniu) też jest jednym z dashboardów kreatora.

### Szczegóły: stan serwera UplinkView

- **Skąd dane:** kontener czyta `/proc` (CPU, RAM, obciążenie, czas pracy pokazują wartości całego serwera,
  nie kontenera), `/sys` (temperatura, jeśli system ją udostępnia) i zajętość dysku. Bez SNMP i bez agenta.
- **Historia:** próbka co cykl kolektora (30 s) do **nowej tabeli** metryk systemowych (nowa tabela powstaje
  sama przy `uplinkview update`, więc nie wymaga migracji Alembic); wykresy i interwały jak na Dashboardzie.
- **Zakres:** CPU %, obciążenie 1/5/15 min, RAM i swap, dyski (root i dysk z danymi Dockera), czas pracy,
  temperatura, rozmiar bazy i jej przyrost, czas ostatniego cyklu kolektora, stan usług (api, kolektor, baza,
  updater). Stan kontenerów podaje `updater` (jedyny z dostępem do Dockera) w osobnej akcji tylko do odczytu.
- **Panel:** karta „Serwer” na Dashboardzie (CPU, RAM, dysk z paskiem zapełnienia) i podstrona
  Ustawienia → System ze szczegółami i wykresami.
- **Ograniczenia:** inne dyski niż ten z Dockerem widać tylko po dodatkowym zamontowaniu (tylko do odczytu);
  temperatury nie ma na części maszyn wirtualnych.
- **Powiązania:** pierwszy krok do pozycji „Monitorowanie serwerów Linux” (ten sam model danych posłuży innym
  serwerom), ostrzeżenia typu „dysk > 90%” wejdą w alerty (etap 8). Pomysł z rozmowy o błędzie „brak miejsca
  na dysku” przy aktualizacji.

### Szczegóły: alerty w panelu

- **Reguła** = metryka + warunek + próg + czas trwania + ważność. Przykłady: „ruch WAN pobierania
  > 800 Mb/s przez 5 min”, „błędy na porcie rosną”, „CPU > 90% przez 10 min”, „RAM > 85%”,
  „dysk > 90%”, „port przeszedł w stan down”, „urządzenie nie odpowiada 2 minuty”,
  „spadek liczby klientów WiFi do 0”.
- **Stany alertu:** wyzwolony → potwierdzony (przez użytkownika) → zakończony, z historią
  (kiedy, jak długo, jaka wartość szczytowa). Histereza i minimalny czas trwania, żeby krótkie
  skoki nie sypały alertami.
- **Panel:** dzwonek w pasku górnym z licznikiem niepotwierdzonych aktywnych (potwierdzony alert go nie zapala), sekcja **Alerty** (aktywne i historia,
  filtr po ważności i urządzeniu), formularz reguł w Ustawienia → Alerty z gotowymi szablonami
  („urządzenie offline”, „port down”, „wysokie CPU”). Z poziomu wykresu: „utwórz alert z tego
  progu” (linia progu rysowana na wykresie).
- **Silnik:** ocena reguł po każdym cyklu kolektora, na ogólnych metrykach (wymóg wstępny jak przy
  serwerach Linux), żeby ta sama reguła działała dla sieci i dla serwerów. Zapis zdarzeń w jednym
  modelu zdarzeń, wspólnym z powiadomieniami o aktualizacjach.
- **Powiadomienia:** w panelu (od razu), potem kanały jako wtyczki: e-mail, webhook, push do aplikacji
  mobilnej (przez chmurę). Ciche godziny i grupowanie, żeby awaria switcha nie dała dwudziestu wiadomości.
- **Decyzje do podjęcia:** czy progi mają być bezwzględne, czy też względem normy (np. „2× więcej niż
  zwykle o tej porze”); czy reguły domyślne włączać od razu po instalacji (np. offline i port down).
- **Zależności:** migracje Alembic i ogólna tabela metryk (jak w opisie serwerów Linux), model
  zdarzeń i tokenów pod aplikację mobilną.

### Szczegóły: wskaźnik siły hasła

- **Dziś:** backend wymaga tylko minimum 10 znaków (wcześniej 8) (`backend/netpulse/auth.py`, `MIN_PASSWORD`),
  a panel pokazuje błąd dopiero po wysłaniu formularza.
- **Warunki do pokazania:** długość (np. min. 8, zalecane 12), cyfra, wielka litera, mała litera,
  znak specjalny. Lista warunków i progi mają być w jednym miejscu, żeby dało się je zmienić.
- **Decyzja do podjęcia:** czy to tylko podpowiedź dla użytkownika (zalecane na start,
  bo nie blokuje długich haseł z samych słów), czy twarda reguła egzekwowana także w backendzie
  (wtedy te same reguły w `auth.py` i w panelu, a `uplinkview user passwd` stosuje je również).
- **Wskazówka techniczna:** komponent `PasswordRequirements` w `frontend/src/components/`,
  czysta funkcja oceny hasła w `src/lib/` z testami; teksty w `src/i18n/pl.ts`.
  Dostępność: wyniki warunków ogłaszane czytnikom ekranu (`aria-live="polite"`), nie tylko kolorem.

### Szczegóły: monitorowanie serwerów Linux

Rozszerzenie UplinkView z urządzeń sieciowych na serwery. Cel: sieć i serwery w jednym lekkim panelu,
z tą samą instalacją jednym linkiem. Dwa etapy, od najtańszego.

**Etap A – SNMP (`snmpd` na serwerze).**
- Kolektor już czyta UCD-SNMP-MIB (CPU, RAM, load) i IF-MIB (interfejsy). Dochodzi `kind = server`
  oraz driver `linux`: dyski i partycje (HOST-RESOURCES-MIB `hrStorage` albo UCD `dskTable`),
  swap, liczba procesów, czas pracy.
- W panelu: karta serwera na Dashboardzie (CPU, RAM, dysk z paskiem zapełnienia) i dodawanie
  w Ustawienia → Urządzenia (typ „Serwer Linux”, podpowiedź, jak włączyć `snmpd`).
- Wygoda: opis konfiguracji `snmpd` (tylko odczyt, tylko z adresu serwera UplinkView) w dokumentacji.
- Ograniczenia SNMP: brak kontenerów, usług systemd, SMART i temperatur (poza tym, co wystawi `snmpd`).

**Etap B – własny agent (`netpulse-agent`).**
- Mały program lub kontener na monitorowanym serwerze, czyta `/proc` i `/sys`, wysyła metryki do UplinkView
  przez HTTPS z tokenem instalacji (**push**: działa za NAT-em, bez otwierania portów na serwerze, pasuje do chmury).
- Zakres: CPU (także na rdzeń), RAM i swap, dyski (zajętość, IO), sieć, temperatury, SMART,
  stan usług systemd, kontenery Docker (stan, zasoby). Bez logów i śledzenia procesów – to ma pozostać lekkie.
- Instalacja agenta jednym poleceniem pokazywanym w panelu (token wygenerowany w Ustawieniach, do odwołania).
- Odczyt kontenerów wymaga dostępu do gniazda Dockera: tylko do odczytu i opcjonalnie (podobne ryzyko jak updater).

**Wymagania wstępne w architekturze (zrobić przed etapem B, najlepiej razem z migracjami Alembic):**
- Ogólna tabela metryk (urządzenie, nazwa, etykiety, wartość) jako hypertable, obok dzisiejszych tabel
  z ustalonymi kolumnami (`interface_metrics`, `device_metrics`). Dyski, kontenery i usługi nie mieszczą się w stałych kolumnach.
- Alerty (etap 8) projektować od razu na ogólnych metrykach, żeby obejmowały sieć i serwery
  („dysk zapełniony w 90%”, „serwer nie odpowiada”, „kontener zatrzymany”).
- Model tokenów dostępu (już zaplanowany pod aplikację mobilną) obejmuje też tokeny agentów.

**Kolejność:** etap A po 5e (prawie bez nowej infrastruktury, od razu pokazuje, jak serwer wygląda w panelu),
etap B po alertach, przed albo razem z chmurą.
