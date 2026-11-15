# Szczegóły urządzeń, portów i klientów, dostępność, kreatory i pulpity publiczne (0.20.0–0.23.0)

## Co jest w panelu

| Miejsce | Co pokazuje |
|---------|-------------|
| **Strona urządzenia** (`/devices/<id>`, klik w nazwę na karcie urządzenia) | Informacje (adres, model, firmware, czas pracy, ostatni odczyt), dostępność 24 godz. / 7 dni / 30 dni / rok i pasek ostatnich 30 dni, wykresy CPU i RAM oraz czasu odpowiedzi, tabela portów (stan, prędkość, ruch, PoE), sieci WiFi, podłączeni klienci (z kontrolera UniFi). |
| **Strona portu** (`/devices/<id>/ports/<id>`, klik w port) | Stan i prędkość, dostępność łącza (ile czasu port był podłączony), ruch, błędy i odrzucone pakiety, moc PoE w czasie i klienci podłączeni do tego portu (switch UniFi). |
| **Strona klienta** (`/clients/<MAC>`, klik w klienta) | Teraz: sieć, pasmo, sygnał, prędkość łącza, do czego jest podłączony. Historia: obecność w sieci (pasek), siła sygnału i prędkość łącza w czasie, historia połączeń (powrót po przerwie, przejście na inny AP, zmiana pasma). Klient rozłączony zostaje widoczny (pierwszy raz i ostatnio w sieci). |
| **Karty urządzeń** | Pod kartą „Dostępność 30 dni: 99,98%”. |
| **Zakres wykresów** | Doszły **30 dni** i **1 rok**. |
| **Kreator pierwszej konfiguracji** (`/setup`) | Otwiera się sam po założeniu konta. Powitanie → dodanie urządzeń z testem SNMP (ten sam formularz co w Ustawienia → Urządzenia) → integracje (moduły) → podsumowanie z dalszymi krokami. Pusty pulpit ma przycisk „Uruchom kreator konfiguracji”. |
| **Ustawienia → Dashboardy** | Własne pulpity: kreator nowego (szablon, widgety, widoczność), udostępnianie, wymiana linku, ustawienie domyślnego, zmiana nazwy, usuwanie. |
| **Przełącznik pulpitów** (strona Dashboard) | Pojawia się, gdy masz więcej niż jeden pulpit. Pulpit domyślny jest pod „/”, pozostałe pod `/dashboards/<id>`. |
| **Pulpit publiczny** (`/p/<token>`) | Bez logowania, tylko do odczytu, bez menu. Przycisk pełnego ekranu; `?kiosk=1` chowa też pasek z nazwą (telewizor, tablet na ścianie). |

## Dostępność i długie wykresy – skąd dane

- Dostępność urządzenia to udział udanych odczytów kolektora (`device_metrics.reachable`), portu – udział próbek,
  w których port był podłączony (`interface_metrics.oper_up`). „Brak odpowiedzi ok. X” to próbki bez odpowiedzi
  × interwał odpytywania. Dni liczone w strefie czasowej z `TZ` w `.env`.
- **Ciągłe agregaty TimescaleDB** (godzinowe): `interface_metrics_1h`, `device_metrics_1h`, `wifi_metrics_1h`
  (`backend/netpulse/aggregates.py`). Zakłada je `init_db` przy starcie kolektora; nowy agregat od razu dostaje całą
  zachowaną historię. Są „na żywo” – ostatnia godzina liczy się z surowych danych.
- Surowe metryki: `NETPULSE_RETENTION_DAYS` (domyślnie 30 dni). Agregaty: `NETPULSE_AGGREGATE_RETENTION_DAYS`
  (domyślnie 730 dni). Wykresy do 7 dni idą z surowych danych, dłuższe – z agregatów.
- Agregaty nie są w migracjach Alembic (to obiekty TimescaleDB, nie tabele z modeli). Błąd agregatu nie zatrzymuje
  startu – działa wszystko poza wykresami dłuższymi niż 7 dni.

## Historia klientów

Kolektor UniFi co cykl zapisuje stan każdego klienta w `client_metrics` (sygnał, prędkości, AP/switch, port, SSID,
pasmo) i pamięta klientów w `known_clients` (pierwsze i ostatnie widzenie). Migracja `0007`. Retencja jak inne
metryki. Przerwa dłuższa niż 3 cykle kolektora to rozłączenie.

## Pulpity publiczne – bezpieczeństwo

- Token w adresie: 32 losowe bajty. W bazie skrót SHA-256 (do wyszukania) i token zaszyfrowany (`EncryptedText`),
  żeby panel mógł pokazać link ponownie. Migracja `0008`.
- **Wymień link** – stary przestaje działać od razu. Przełączenie na prywatny unieważnia link; ponowne udostępnienie
  daje nowy. Opcjonalna data wygaśnięcia.
- **PIN** (4–12 cyfr, w bazie skrót Argon2). Po poprawnym PIN-ie przeglądarka dostaje klucz dostępu na czas sesji
  karty; zmiana PIN-u albo linku unieważnia klucz. Nieudane próby są limitowane (10 na 15 minut z jednego adresu).
- Osobne API tylko do odczytu `/api/public/dashboards/<token>` (`backend/netpulse/api/public.py`), bez ciasteczek
  sesji. Dane wychodzą wyłącznie przez `/data?path=…` i tylko te, których potrzebują widgety zapisane w tym pulpicie
  (biała lista budowana z układu w bazie, nie z żądania). Reszta API bez logowania zostaje zamknięta.
- Domyślnie ukryte: adresy IP i komunikaty błędów urządzeń, dane SNMP, nazwy hostów agentów.
- Odpowiedzi: `Cache-Control: no-store`, `X-Robots-Tag: noindex`, `Referrer-Policy: no-referrer`.
- Odświeżanie nie częściej niż co 10 s, tryb „Na żywo” (WebSocket) wyłączony.
- Nowy widget = jego ścieżki danych trzeba dopisać w `resolve()` w `api/public.py`, inaczej na pulpicie publicznym
  pokaże błąd (bezpieczna domyślna).

## Jak sprawdzić po aktualizacji

1. `uplinkview update`, potem w panelu klik w nazwę urządzenia na pulpicie → strona urządzenia, klik w port → strona portu.
2. Klienci → klik w klienta → strona klienta (historia rośnie od aktualizacji).
3. Zakres „30 dni” / „1 rok” na wykresie – pokaże dane od początku zachowanej historii.
4. Ustawienia → Dashboardy → Nowy dashboard → szablon „Wyświetlacz ścienny” → publiczny → Utwórz → otwórz link
   w oknie prywatnym przeglądarki (bez logowania) albo zeskanuj kod QR telefonem.
5. Kreator pierwszej konfiguracji można obejrzeć pod `/setup` (dodanie urządzenia, które już jest, zwróci błąd „już jest dodane”).
