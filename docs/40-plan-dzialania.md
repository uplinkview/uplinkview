# Plan działania (po analizie z 12.11.2026)

**Status: plan przyjęty do wiadomości, etapy startują po zgodzie użytkownika.** Powstał z analizy kodu
(wydajność wczytywania, bezpieczeństwo, wygląd) na wersji 0.65.9 i z odpowiedzi użytkownika:

- **Odbiorcy:** na początek hobbyści homelab, docelowo hobbyści i małe firmy.
- **Nazwa:** ✅ **UplinkView** (13.11.2026; domena uplinkview.com i konto `uplinkview` na GitHubie zarejestrowane).
- **Licencja:** ✅ AGPL-3.0, instalacja w całości darmowa, płatna tylko chmura (13.11.2026, 0.79.0; `docs/09`).
- **Wdrożenie:** samodzielne hostowanie, w przyszłości instalacja na serwerach albo chmura producenta
  z panelem do odczytu parametrów (`docs/39-chmura-propozycja.md`).

Etapy 1–5 nie zależą od nazwy. Nazwa i licencja wybrane – etap 6 (publikacja) może ruszyć.
Numery wersji są orientacyjne.

## Wnioski z analizy, z których wynika plan

### Wydajność wczytywania

| Co | Stan na 0.65.9 |
|----|----------------|
| Kompresja HTTP | brak w nginx i w API; pierwsze wejście ok. 1,1 MB, po gzip ok. 0,37 MB (wykresy 568 → 190 kB, biblioteki 294 → 91 kB, kod panelu 140 → 44 kB, style 48 → 10 kB) |
| Kompresja TimescaleDB | brak polityki kompresji hypertables |
| Pliki statyczne | serwuje Python (API), nie nginx; cache plików z `/assets` jest poprawny |
| Sesja | dwa zapytania do bazy przy każdym żądaniu API (`user_from_request`) |
| Logowanie | `verify_password` (argon2) działa synchronicznie w pętli API |
| Pulpit | kaskada: status logowania → moduły → pulpit → widget → ECharts |

Dobrze zrobione: podział paczki, strony ładowane na żądanie, ECharts tylko z potrzebnymi modułami,
agregaty godzinowe, indeksy (obiekt, czas).

### Bezpieczeństwo

Dobrze zrobione: argon2, sesje jako skrót tokenu, HttpOnly + SameSite, ochrona CSRF po Origin, role z domyślną
odmową, 2FA, szyfrowane sekrety, dziennik zdarzeń, biała lista pulpitu publicznego, updater bez portu.

Do poprawy, od najważniejszego:

1. Aktualizacje bez weryfikacji źródła – updater (dostęp do gniazda Dockera) instaluje to, co jest na `main`.
2. Aplikacja łączy się z bazą jako superużytkownik (`POSTGRES_USER`).
3. Niepełny Content-Security-Policy (brak `default-src`, `script-src`).
4. Limit logowań tylko po IP i w pamięci; słownik prób nie jest czyszczony.
5. Kontenery bez `cap_drop`, `no-new-privileges`, `read_only`.
6. Nieprzypięte wersje: `timescale/timescaledb:latest-pg17`, zależności Pythona z `>=` bez pliku blokady.
7. Brak pliku LICENSE.

### Wygląd

Panel jest nowoczesny i spójny – **bez przebudowy**, tylko dopracowanie (lista w etapie 3).

## Etap 1 – szybkie poprawki wydajności ✅ (0.67.0)

Zrobione 12.11.2026. Gzip: `deploy/proxy/nginx.conf` (sprawdzany w teście end-to-end CI). Kompresja bazy:
`netpulse/compression.py`, opis w `docs/13-migracje-bazy.md`. Pamięć sesji (`NETPULSE_SESSION_CACHE_S`, 10 s) i czyszczenie
jej przy zmianach kont: `api/security.py` (`forget_sessions`). Hasła w wątku: `hash_password_async`, `verify_password_async`.
Wstępne ładowanie wykresów: `Shell.tsx`. Przy okazji: limit logowań czyści nieużywane adresy (punkt z etapu 2).
Pliki statyczne dalej serwuje API (przez nginx z kompresją) – przeniesienie ich do nginx nie było potrzebne.

- Kompresja gzip w nginx dla paczki panelu i odpowiedzi JSON.
- Kompresja TimescaleDB na hypertables (dane starsze niż ok. 7 dni), także na istniejących bazach.
- Pamięć podręczna sesji w procesie API (kilkanaście sekund).
- Hashowanie hasła w wątku.
- Wstępne ładowanie pliku wykresów zaraz po zalogowaniu.

**Gotowe, gdy:** pierwsze wejście pobiera ok. 0,4 MB zamiast 1,1 MB, a rozmiar bazy po kilku dniach wyraźnie spada.

## Etap 2 – bezpieczeństwo przed pokazaniem światu ✅ (0.68.0 i 0.69.0)

Zrobione 12.11.2026 (opis: `docs/34-https.md`, „Utwardzenie”): pełny CSP, limit logowań na konto, utwardzenie kontenerów,
przypięty obraz bazy i plik blokady Pythona. Podpisane aktualizacje (0.69.0): commity na `main` podpisane kluczem SSH,
updater i `uplinkview update` sprawdzają podpis – `docs/41-podpisane-aktualizacje.md`. Aktualizacje idą dalej z `main` (nie z tagów
wydań) – podpis commita daje tę samą ochronę bez zmiany sposobu pracy. Osobna rola bazy odłożona – uzasadnienie w `docs/34-https.md`.

- Aktualizacje z podpisanych tagów wydań zamiast gałęzi `main`; updater odrzuca niepodpisany kod,
  `install.sh` instaluje ostatnie wydanie.
- Osobna rola bazy bez uprawnień superusera dla API i kolektora.
- Pełny Content-Security-Policy (skrypt motywu w `index.html` ze skrótem).
- Limit logowań także na login, z czyszczeniem starych wpisów.
- Utwardzenie kontenerów: `cap_drop`, `no-new-privileges`, `read_only` tam, gdzie się da.
- Przypięte wersje: obraz bazy na konkretny numer, plik blokady zależności Pythona.

**Gotowe, gdy:** CI przechodzi z nowym sposobem aktualizacji (`install.sh` → `uplinkview update`), a aktualizacja
serwera użytkownika działa bez ręcznych kroków.

## Etap 3 – dopracowanie wyglądu ✅ (0.66.0, widok na telefonie 0.76.1)

Zrobione 12.11.2026 przed etapami 1–2 (na prośbę użytkownika), opis: `docs/06-projekt-panelu.md` („Dopracowanie wyglądu”).
Telefon (mini-wykresy w kafelkach, pasek górny) i wersja w atrapie API – 0.76.1.

- Tabela urządzeń bez poziomego przewijania (widoczne przy 1440 px).
- Paski dostępności: kolor tylko dla okresów z prawdziwą awarią (dziś 99,4 % wygląda na ciągłe problemy).
- Mapa sieci: węzły z modelem, ruchem i liczbą klientów, układ także w poziomie.
- Telefon: pełne mini-wykresy w kafelkach, czytelniejszy pasek górny.
- Lewe menu: szybki stan sieci w wolnym miejscu.
- Puste widgety z podpowiedzią, co dodać.
- Paleta poleceń Ctrl+K (urządzenia, porty, klienci, ustawienia).
- Atrapa API pokazuje wersję 0.6.0 – poprawić przed zrzutami do README.

**Gotowe, gdy:** zrzuty pulpitu, mapy i widoku na telefonie nadają się do README bez retuszu.

## Etap 4 – język angielski ✅ (4a 0.74.0, 4b 0.75.0, 4c 0.76.0)

Podział i stan: `docs/44-jezyk-angielski.md` – 4a panel ✅ (0.74.0), 4b komunikaty z backendu, 4c powiadomienia, raport i Android.

- Przełącznik języka w panelu (na koncie), drugi plik tłumaczeń obok `i18n/pl.ts`.
- Kody błędów w API zamiast polskich tekstów w backendzie; tłumaczy je panel.
- Powiadomienia (e-mail, Telegram, ntfy), raport PDF/CSV i aplikacja Android w obu językach.
- Nazwa produktu w jednym miejscu w kodzie.

**Gotowe, gdy:** cały panel da się przejść po angielsku bez polskiego tekstu (test w CI wyłapuje brakujące klucze).

## Etap 5 – pierwsze 5 minut ✅ (0.73.0)

Zrobione 13.11.2026, opis: `docs/43-wykrywanie-urzadzen.md` (skan /24 w ok. 5 s, raport z anonimizacją, zgłoszenie na GitHubie).

- Wykrywanie urządzeń: skan podsieci z listą „co dodać” (część A z `docs/24-wykrywanie-propozycja.md`)
  w kreatorze pierwszej konfiguracji.
- Zanonimizowany raport urządzenia do pobrania (część B) – źródło zrzutów sprzętu, którego brakuje.

**Gotowe, gdy:** czysta instalacja w sieci użytkownika sama znajduje UCG, switch i AP, a dodanie ich to trzy kliknięcia.

## Punkt decyzyjny – nazwa i licencja

Bez nich etap 6 nie ruszy: nazwa z listy użytkownika, licencja kodu i model z `docs/09-licencje-propozycja.md`.

- **Nazwa ✅ (13.11.2026): UplinkView.** Wolne: domeny .com/.net/.org/.io/.app/.dev, nazwy na GitHubie, Docker Hubie,
  PyPI i npm; w TMview (EUIPO, USPTO, UKIPO, WIPO) brak znaku „UplinkView”. Słowo UPLINK jest jednak zarejestrowane
  wiele razy w klasach oprogramowania 9/42 – przed rejestracją własnego znaku albo płatną chmurą (etap 9) opinia
  rzecznika patentowego. Domena uplinkview.com zarejestrowana (ważna do 13.11.2027 – odnowić), konto GitHub `uplinkview`.
- **Licencja ✅ (13.11.2026):** GNU AGPL-3.0-only; wszystko, co instaluje się u siebie, darmowe i bez limitów, płatna tylko
  chmura (etap 9). Uzasadnienie, zależności i podwójne licencjonowanie: `docs/09-licencje-propozycja.md`.

## Etap 6 – publikacja (1.0.0)

- ✅ (0.78.0) Zmiana nazwy na UplinkView w panelu, dokumentacji, instalatorze, repozytorium (`uplinkview/uplinkview`) i aplikacji Android; istniejące instalacje aktualizują się dalej (stary katalog i polecenie `netpulse` działają). Nazwy wewnętrzne (pakiet, zmienne, wolumeny) bez zmiany – lista w `CLAUDE.md`.
- ✅ (0.79.0) Plik LICENSE (AGPL-3.0), link do kodu źródłowego w panelu, `CONTRIBUTING.md`.
- ✅ (0.79.1) README po angielsku (`README.md`) i po polsku (`README.pl.md`) ze zrzutami (`docs/img/`, skrypt `frontend/dev/screenshots.mjs`).
- Dokumentacja instalacji po angielsku.
- Publiczne demo tylko do odczytu, oparte na atrapie `frontend/dev/mock-api.mjs`.
- Gotowe obrazy w GHCR – instalacja bez budowania na serwerze użytkownika.
- Ogłoszenie na r/selfhosted i r/homelab, szablony zgłoszeń na GitHubie.

## Etap 7 – po publikacji, dla hobbystów (1.1–1.4)

Kolejność do korekty według próśb użytkowników:

1. Eksport metryk Prometheus i tokeny API.
2. Integracja z Home Assistant.
3. Test prędkości łącza według harmonogramu.
4. Nowy sprzęt ze zrzutów od użytkowników: Synology (`docs/27`), OPNsense/pfSense, prawdziwy MikroTik i Omada.
5. Własne OID-y i profile YAML (`docs/25-wlasne-oid-propozycja.md`).

## Etap 8 – dla małych firm (1.5–1.9)

- Logowanie SSO (OIDC – Authentik, Authelia).
- Raporty wysyłane e-mailem według harmonogramu; okna serwisowe w SLA WAN i sprawdzeniach.
- Analiza ruchu NetFlow/sFlow – „kto zużywa łącze”.
- Wiele lokalizacji w jednym panelu.
- Dłuższy audyt, eksport dziennika.

## Etap 9 – chmura producenta (2.0)

Pełny projekt: `docs/39-chmura-propozycja.md` (łącznik wychodzący, panel w chmurze, push, licencje i płatności,
etapy C0–C6). C0 warto zrobić przy okazji etapów 4 i 7; C1–C3 można zbudować wcześniej na własny użytek.

## Czego potrzeba od użytkownika

- **Teraz:** zgoda na start etapu 1.
- **Do końca etapu 5:** nazwa i licencja ✅ (13.11.2026).
- **Po każdym etapie:** `uplinkview update` na serwerze i informacja, czy działa.
- **Przed etapem 9:** odpowiedzi na pytania otwarte z `docs/39`.
