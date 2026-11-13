# Chmura producenta – propozycja architektury (etap 9)

**Status: tylko propozycja (12.11.2026). Nic z tego nie jest wdrożone. Nie wdrażać bez decyzji użytkownika.**
Dokument daje pełny obraz etapu 9 z planu działania: łącznik wychodzący, panel w chmurze, powiadomienia push,
licencje i płatności. Łączy się z `docs/09-licencje-propozycja.md` (licencje) i `docs/38-aplikacja-android.md`.
Nazwa „UplinkView” jest tu robocza – domeny i nazwy usług powstaną po wyborze nazwy produktu.

## Cel w jednym zdaniu

Użytkownik instaluje UplinkView u siebie jak dotąd, a po sparowaniu z kontem w chmurze widzi swoją sieć (albo
kilka sieci) z dowolnego miejsca i dostaje powiadomienia na telefon – **bez otwierania portów na routerze,
bez VPN i bez przenoszenia historii pomiarów do chmury**.

## Najważniejsza decyzja: co trzyma chmura

SNMP działa tylko w sieci lokalnej, więc coś zawsze musi stać u użytkownika. Różnica jest w tym, gdzie leżą dane.

| Wariant | Jak działa | Plusy | Minusy |
|---------|-----------|-------|--------|
| **1. Tunel** (jak Home Assistant Cloud) | Chmura tylko przekazuje żądania panelu do instalacji. Nic nie przechowuje. | Prywatność, mały koszt, cały panel działa od razu (panel jest wyłącznie klientem API). | Gdy instalacja nie działa, w chmurze nie widać nic. Brak widoku wielu sieci naraz. |
| **2. Skrót stanu** | Instalacja co minutę wysyła mały skrót (stan urządzeń, aktywne alerty, łącza WAN). | Lista wszystkich sieci na jednym ekranie, push, alarm „instalacja zamilkła”. | Sam skrót nie zastąpi panelu. |
| **3. Wszystko w chmurze** (jak Domotz, Auvik) | U klienta tylko sonda, baza i panel w chmurze. | Klient nie utrzymuje serwera. | Wielodostępna baza metryk, duży koszt i odpowiedzialność za dane, przebudowa kolektora. |

**Rekomendacja: 1 + 2 razem.** Skrót stanu daje ekran „moje sieci” i push, tunel daje pełny panel wybranej
instalacji. Historia pomiarów zostaje u użytkownika. Wariant 3 (sonda bez lokalnego panelu) to możliwy późniejszy
produkt dla firm obsługujących wielu klientów – architektura poniżej go nie blokuje, bo łącznik i konta
organizacji są te same.

## Obraz całości

```
   SIEĆ UŻYTKOWNIKA                                   CHMURA PRODUCENTA
 ┌──────────────────────────────┐                ┌─────────────────────────────────────┐
 │ kolektor ─ baza ─ API ─ proxy│                │  brama łączników (WSS)               │
 │              ▲               │   wychodzące   │      │                               │
 │              │ HTTP (sieć    │   WSS :443     │  API chmury ── PostgreSQL ── Redis   │
 │              │ wewnętrzna)   │ ─────────────► │      │                               │
 │        kontener „cloud”      │                │  panel chmury (moje sieci, konto)    │
 │        (łącznik, moduł)      │                │  + ten sam panel UplinkView przez tunel│
 └──────────────────────────────┘                │      │                               │
                                                 │  push (FCM / APNs) ─► telefon        │
   telefon / przeglądarka ── HTTPS ────────────► │  płatności (dostawca zewnętrzny)     │
                                                 └─────────────────────────────────────┘
```

Instalacja nigdy nie przyjmuje połączeń z internetu. Jedyny ruch to jedno wychodzące połączenie WebSocket
po TLS na port 443 – przechodzi przez każdy domowy router i CGNAT (łącze GSM też).

## Część A – łącznik wychodzący

### Gdzie stoi

Nowy moduł `cloud` (Ustawienia → Moduły, domyślnie wyłączony) i nowy kontener `cloud` w `docker-compose.yml`.
Osobny kontener, a nie pętla w API, bo:

- restart API przy aktualizacji nie zrywa od razu zdalnej sesji – łącznik zgłasza „trwa aktualizacja”,
- łącznik ma dostęp tylko do `http://api:8000`, nie do bazy, kluczy ani gniazda Dockera,
- wyłączenie modułu = kontener nie łączy się z niczym.

Kod: `backend/netpulse/cloud/` (ten sam obraz co API i kolektor, polecenie `netpulse cloud`).

### Parowanie (bez przepisywania długich kluczy)

1. Ustawienia → Chmura → „Połącz z kontem”. Instalacja tworzy parę kluczy Ed25519 (prywatny zostaje w wolumenie
   `netpulse_keys`) i identyfikator instalacji (ten sam `install_id`, którego chce `docs/09`).
2. Panel pokazuje krótki kod (np. `KRZT-4821`, ważny 10 min) i kod QR.
3. Użytkownik wpisuje kod w panelu chmury (albo skanuje QR telefonem), wybiera nazwę sieci i organizację.
4. Chmura zapisuje klucz publiczny instalacji. Od tej chwili łącznik loguje się podpisem (wyzwanie–odpowiedź);
   nie ma hasła ani tokenu, który mógłby wyciec z chmury i posłużyć do podszycia się pod instalację.
5. Rozłączenie: przycisk po obu stronach. Po stronie instalacji działa także bez internetu.

### Protokół

Jedno połączenie WSS, w nim ramki z numerem strumienia:

| Ramka | Kierunek | Do czego |
|-------|----------|----------|
| `hello` / `challenge` / `auth` | obie | logowanie podpisem, wersja UplinkView i protokołu |
| `snapshot` | instalacja → chmura | skrót stanu co 60 s (część B) |
| `event` | instalacja → chmura | alert otwarty / zakończony – od razu, bez czekania na skrót |
| `req` / `res` / `body` | chmura → instalacja → chmura | żądanie HTTP panelu przekazane do lokalnego API, odpowiedź strumieniem |
| `ws_open` / `ws_msg` / `ws_close` | obie | „Na żywo” (`/api/live/device`) przez tunel |
| `ping` / `pong` | obie | podtrzymanie; brak odpowiedzi 90 s = rozłączone |
| `license` | chmura → instalacja | podpisany token licencji (część D) |

Ponowne łączenie z rosnącym odstępem i losowym rozrzutem (5 s → 5 min), żeby po awarii chmury wszystkie
instalacje nie wróciły w tej samej sekundzie.

### Kto jest kim po stronie instalacji

Żądanie z chmury nie używa lokalnego hasła ani lokalnej sesji. Chmura dokleja do każdego żądania **krótkie
poświadczenie** (podpis chmury, ważne 60 s): identyfikator konta w chmurze, rola, `install_id`. Łącznik
sprawdza podpis kluczem publicznym chmury wbudowanym w aplikację i przekazuje żądanie do API nagłówkiem, któremu
API wierzy tylko z kontenera `cloud`. W `api/security.py` dochodzi drugi rodzaj tożsamości obok sesji
z ciasteczka („konto chmury”), z rolą nadaną lokalnie.

Zasady, których chmura nie może zmienić:

- **Rolę kont chmury ustawia administrator lokalnie** (Ustawienia → Chmura): domyślnie `viewer` (tylko odczyt).
  `operator` i `admin` trzeba włączyć świadomie.
- **Zawsze zablokowane przez chmurę**, niezależnie od roli: aktualizacja, kopie zapasowe (tworzenie, pobranie,
  przywrócenie), konta i hasła lokalne, 2FA, certyfikaty, moduły, samo ustawienie chmury. To są operacje,
  którymi przejęta chmura mogłaby przejąć serwer – zostają dostępne tylko z sieci lokalnej.
- Każde żądanie z chmury trafia do Dziennika zdarzeń z dopiskiem „przez chmurę” i nazwą konta chmury.
- Wyłącznik lokalny działa natychmiast (zamknięcie połączenia), także gdy chmura nie odpowiada.

## Część B – panel w chmurze

### Co widzi użytkownik

1. **Moje sieci** – lista instalacji z organizacji: nazwa, stan (działa / problemy / brak połączenia od…),
   liczba urządzeń online, aktywne alerty, łącze WAN (aktywne, zapasowe), wersja UplinkView.
2. **Otwórz panel** – pełny panel wybranej instalacji przez tunel: te same pulpity, wykresy i ustawienia
   (w granicach roli), co w sieci domowej.
3. **Konto i organizacja** – członkowie, role, urządzenia do powiadomień, plan i płatności.

### Skrót stanu – dokładnie co wychodzi z instalacji

Lista jest zamknięta i pokazana w Ustawienia → Chmura (z podglądem ostatniego wysłanego skrótu):

- liczba urządzeń: razem, działa, nie odpowiada, bez aktualnych danych,
- urządzenia: nazwa, rodzaj, stan, od kiedy (nazwy można zastąpić numerami – przełącznik „ukryj nazwy”),
- aktywne alerty: tytuł, waga, od kiedy,
- łącza WAN: nazwa, stan, które aktywne, bieżące pobieranie i wysyłanie,
- wersja UplinkView, czy jest dostępna aktualizacja, czas ostatniego odczytu kolektora.

**Nie wychodzą:** adresy IP i MAC, klienci sieci, SSID, community i klucze, historia pomiarów, topologia,
treść dziennika zdarzeń. Jeden skrót to kilka kB na minutę.

### Jak panel działa przez tunel

Panel już dziś umie przekierować swoje zapytania pod inny adres (`setPublicDashboard` w `lib/api.ts` robi to dla
pulpitu publicznego). Tryb chmury używa tego samego mechanizmu: zapytania `/api/...` idą do bramy, która
wysyła je tunelem do właściwej instalacji.

- **Każda instalacja pod własną subdomeną** (`<id>.app.<domena>`, certyfikat wildcard). Przeglądarka traktuje
  je jak osobne strony, więc ewentualny błąd XSS w danych jednej sieci nie sięga do innej ani do konta chmury.
- Pliki panelu (JS, CSS) serwuje chmura w wersji zgodnej z instalacją – tunelem idą tylko dane. Chmura trzyma
  paczki panelu kilku ostatnich wersji; starsza instalacja dostaje komunikat „zaktualizuj UplinkView”.
- Ograniczenia tunelu (do ustalenia w testach): rozmiar odpowiedzi, liczba równoległych żądań, liczba
  połączeń „Na żywo”. Pobieranie kopii zapasowych jest zablokowane i tak (patrz część A).

### Gdy instalacja zamilknie

Chmura widzi przerwane połączenie. Po 5 minutach bez łączności wysyła push „Sieć X nie łączy się z chmurą”.
To jest funkcja, której instalacja sama z siebie dać nie może: **nadzór nad samym monitoringiem** (brak prądu,
awaria serwera, awaria internetu bez łącza zapasowego).

### Budowa chmury

Ten sam stack co UplinkView, żeby nie utrzymywać dwóch technologii:

| Usługa | Rola | Uwagi |
|--------|------|-------|
| `gateway` | trzyma połączenia łączników, przekazuje żądania | asyncio; stan połączeń w Redis, żeby dało się uruchomić kilka kopii |
| `cloud-api` | konta, organizacje, instalacje, push, licencje, płatności | FastAPI + PostgreSQL |
| `cloud-web` | panel chmury i paczki panelu UplinkView | React, wspólne komponenty z `frontend/` |
| `postgres`, `redis` | dane kont i kolejki | bez TimescaleDB – chmura nie trzyma metryk |

Osobne repozytorium (prywatne), wdrożenie na start jednym `docker compose` na serwerze w UE. Jedno połączenie
WSS i jeden skrót na minutę na instalację to bardzo małe obciążenie; realne koszty rosną dopiero z ruchem
przez tunel (wykresy, „Na żywo”). Ile instalacji udźwignie jeden serwer – do zmierzenia w etapie C2, nie zgaduję.

### Dane w chmurze

| Tabela | Zawartość |
|--------|-----------|
| `accounts` | e-mail, hasło (argon2), 2FA / klucze dostępu (passkey), język |
| `organizations`, `memberships` | organizacja, członkowie i role (`owner`, `admin`, `member`, `viewer`) |
| `installations` | organizacja, nazwa, klucz publiczny, wersja, ostatnie połączenie, plan |
| `snapshots` | ostatni skrót stanu każdej instalacji (jeden wiersz, nadpisywany) |
| `cloud_alerts` | alerty z ramek `event`, 90 dni – do listy w aplikacji i historii push |
| `push_devices` | telefon, platforma, token FCM/APNs, ustawienia powiadomień |
| `subscriptions`, `license_tokens` | plan, stan płatności u dostawcy, wystawione tokeny |
| `audit` | logowania, parowania, zmiany ról, otwarcia panelu przez tunel |

## Część C – powiadomienia push

### Droga powiadomienia

1. Silnik alertów w instalacji otwiera alert (jak dziś).
2. Nowy rodzaj kanału w `notifications.py`: **„Aplikacja mobilna (chmura)”** – obok webhooka, Telegrama, ntfy
   i e-maila. Obowiązują go te same reguły: ciche godziny, okna serwisowe, grupowanie po topologii.
3. Łącznik wysyła ramkę `event`. Chmura zapisuje alert i wysyła push do telefonów członków organizacji, którzy
   mają tę sieć włączoną.
4. Stuknięcie w powiadomienie otwiera alert w aplikacji (dane przez tunel).

### Aplikacja mobilna

- Drugi sposób logowania obok obecnego „adres serwera + hasło”: **konto chmury** (przeglądarka systemowa,
  OAuth z PKCE). Po zalogowaniu lista sieci, wybór jednej, reszta ekranów bez zmian – te same zapytania API,
  tylko przez tunel. Widget „Ruch WAN” zaczyna działać poza domem.
- Android: Firebase Cloud Messaging. **Do sprawdzenia na telefonie testowym** (Samsung S10+ bez konta Google):
  FCM wymaga Usług Google Play, konto Google nie powinno być potrzebne, ale trzeba to potwierdzić. Zapas:
  UnifiedPush / ntfy dla telefonów bez Usług Google.
- iOS: osobna aplikacja i APNs – wymaga płatnego konta Apple Developer. Poza zakresem pierwszej wersji.
- Prywatność: treść powiadomienia przechodzi przez serwery Google/Apple. Przełącznik „powiadomienia bez
  szczegółów” wysyła samo „Nowy alert w sieci X”, a treść aplikacja pobiera sama.

### Rodzaje powiadomień w pierwszej wersji

Alert otwarty, alert zakończony (opcjonalnie), instalacja nie łączy się z chmurą, przełączenie na łącze
zapasowe, dostępna aktualizacja UplinkView (opcjonalnie). Ustawienia na telefon i na sieć: wagi alertów, ciche
godziny telefonu.

## Część D – licencje i płatności

**Decyzja 13.11.2026 (`docs/09`):** instalacja jest w całości darmowa (AGPL-3.0), płatna jest tylko chmura –
token licencji w instalacji nie jest potrzebny, plan i limity sprawdza chmura u siebie. Poniższy opis tokenu zostaje
na wypadek zmiany decyzji.

Mechanizm z `docs/09` zostaje (podpisany token, weryfikacja offline, karencja, zasada „licencja nigdy nie wyłącza
zbierania danych”), ale chmura upraszcza go dla większości użytkowników:

- **Konto chmury jest posiadaczem licencji.** Sparowana instalacja dostaje token ramką `license` – bez
  wpisywania klucza. Token odświeża się tym samym połączeniem.
- **Klucz wpisywany ręcznie i plik licencji offline** zostają dla instalacji bez chmury (firmy z siecią
  odciętą od internetu).
- Limity planu chmury (liczba sieci, członków, telefonów) egzekwuje chmura u siebie. W instalacji `licensing.py`
  sprawdza tylko funkcje lokalne, jeśli jakiekolwiek będą płatne.

### Naturalna granica płatności

Chmura kosztuje producenta co miesiąc (serwery, push, ruch), instalacja lokalna – nic. Stąd propozycja spójna
z modelem B z `docs/09`:

| Poziom | Dla kogo | Co zawiera |
|--------|----------|-----------|
| **Lokalny** | każdy | cały UplinkView u siebie, bez ograniczeń funkcji monitoringu |
| **Chmura osobista** | hobbysta | 1–2 sieci, zdalny panel, push, alarm „instalacja zamilkła” |
| **Chmura dla firm** | mała firma, informatyk obsługujący klientów | wiele sieci, organizacja z rolami, SSO, raporty e-mailem, dłuższa historia alertów |

Ceny, okres próbny i to, czy cokolwiek lokalnego ma być płatne – to decyzje użytkownika (pytania otwarte).

### Płatności

Rekomendacja jak w `docs/09`: dostawca działający jako sprzedawca (Paddle, Lemon Squeezy) – bierze na siebie VAT
w UE, faktury i zwroty. Chmura dostaje od niego zdarzenia (webhook: opłacono, anulowano, nieudana płatność)
i zmienia plan organizacji. Dane kart nigdy nie przechodzą przez serwery producenta. Nieudana płatność →
karencja → powrót do planu darmowego; zdalny dostęp i push przestają działać, instalacja lokalna działa dalej.

## Bezpieczeństwo – model zagrożeń

| Zagrożenie | Zabezpieczenie |
|------------|----------------|
| Ktoś podszywa się pod instalację | logowanie podpisem klucza, który nigdy nie opuszcza serwera użytkownika |
| Ktoś podszywa się pod chmurę | TLS + poświadczenia żądań podpisane kluczem chmury; klucz publiczny wbudowany w aplikację, z `kid` do wymiany |
| **Przejęcie chmury** (najgroźniejsze: dostęp do wszystkich sieci naraz) | domyślnie tylko odczyt; operacje krytyczne zawsze zablokowane przez tunel; klucz podpisujący w KMS/HSM, nie na dysku serwera; wyłącznik lokalny; dziennik po stronie instalacji, którego chmura nie może wyczyścić |
| Przejęcie konta chmury | 2FA obowiązkowe dla roli wyższej niż odczyt, klucze dostępu (passkey), powiadomienie o nowym logowaniu, lista sesji |
| Jedna sieć atakuje drugą przez panel | osobna subdomena na instalację, ścisły CSP |
| Zalanie bramy połączeniami | limit połączeń na instalację i adres, limit żądań i transferu na plan |
| Podsłuch przez producenta | uczciwie: chmura rozszyfrowuje TLS, więc technicznie widzi dane przechodzące tunelem. Nie zapisuje ich i nie loguje treści. Sekrety (community, klucze API) i tak nie wracają w API. Szyfrowanie od przeglądarki do instalacji to możliwy późniejszy etap. |

Przed startem płatnej usługi: zewnętrzny test bezpieczeństwa bramy i łącznika.

## Wymagania prawne i organizacyjne (poza kodem)

- Podmiot, który sprzedaje usługę (działalność albo spółka) – potrzebny do umowy z dostawcą płatności.
- RODO: producent przetwarza dane kont (e-mail) i skróty stanu. Potrzebne: polityka prywatności, regulamin,
  umowa powierzenia dla klientów firmowych, serwery w UE, procedura usunięcia konta i danych.
- Stała obsługa: monitoring chmury (własny UplinkView nadaje się do tego dobrze), kopie bazy kont, strona
  stanu usługi, kontakt do zgłoszeń. Chmura to zobowiązanie do dostępności, którego produkt lokalny nie ma.

## Etapy

| Etap | Zakres | Jak sprawdzić |
|------|--------|---------------|
| **C0 – przygotowanie w UplinkView** | `install_id`, tożsamości inne niż sesja z ciasteczka w `api/security.py`, kody błędów zamiast polskich tekstów, panel z konfigurowalnym adresem API | CI; wspólne z etapami 4 i 7 planu (angielski, tokeny API) |
| **C1 – łącznik i brama** | parowanie, logowanie podpisem, tunel żądań HTTP, wyłącznik, wpisy w dzienniku | panel serwera domowego otwarty przez testową bramę na VPS |
| **C2 – skrót stanu i „Moje sieci”** | konta, organizacje, lista sieci, alarm „instalacja zamilkła”, pomiar obciążenia | dwie instalacje (dom + maszyna testowa) na jednym koncie |
| **C3 – pełny panel przez tunel** | subdomeny, paczki panelu wg wersji, „Na żywo” przez tunel, role i blokady | przejście całego panelu poza siecią domową |
| **C4 – push i aplikacja** | kanał „Aplikacja mobilna”, FCM, logowanie kontem chmury w aplikacji Android | alert testowy na telefonie na danych komórkowych |
| **C5 – licencje i płatności** | L1–L3 z `docs/09`, token przez łącznik, plany, dostawca płatności | zakup w trybie testowym dostawcy |
| **C6 – start usługi** | regulamin, polityka prywatności, test bezpieczeństwa, strona stanu, zamknięte testy z kilkoma użytkownikami | – |

C0 jest tanie i warto je zrobić przy okazji wcześniejszych etapów planu. C1–C3 można zbudować i używać
samemu (na obecnym VPS) bez żadnej decyzji o płatnościach – dają zdalny dostęp do własnej sieci bez VPN.

## Co warto uwzględnić już teraz, żeby później nie przerabiać

1. **Kody błędów w API** (etap 4 planu) – aplikacja i panel chmury będą tłumaczyć je same.
2. **Tożsamość żądania jako pojęcie** w `api/security.py`: sesja, token API (etap 7), konto chmury – jeden
   interfejs z rolą, zamiast zakładania wszędzie, że użytkownik = wiersz `users`.
3. **Adres API w panelu w jednym miejscu** (`lib/api.ts`) – już prawie jest dzięki pulpitowi publicznemu.
4. **Nazwa produktu w jednej stałej** – domeny chmury i identyfikator aplikacji mobilnej zależą od nazwy;
   identyfikatora aplikacji Android nie da się zmienić po publikacji w sklepie.

## Pytania otwarte

1. Czy zgadzasz się na wariant 1 + 2 (tunel + skrót stanu, historia zostaje u użytkownika)?
2. Czy cokolwiek w instalacji lokalnej ma być płatne, czy płatna jest tylko chmura?
3. Domyślna rola kont chmury: tylko odczyt (propozycja) czy operator?
4. Czy nazwy urządzeń mogą domyślnie trafiać do skrótu stanu, czy domyślnie mają być ukryte?
5. Push: wystarczy Android na start, czy iOS jest warunkiem wypuszczenia usługi?
6. Kto prowadzi sprzedaż (forma działalności) i od kiedy – to wyznacza najwcześniejszy termin C5.
7. Czy C1–C3 budujemy wcześniej na własny użytek (zdalny dostęp bez VPN), czy dopiero po etapie 8 planu?
