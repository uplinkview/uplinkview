# Raport miesięczny (0.65.0)

Menu → **Raporty**: wybór miesiąca (bieżący – „do teraz” – i 12 poprzednich; domyślnie poprzedni pełny miesiąc),
podgląd w panelu i pobranie **PDF** (A4, do wysłania albo wydruku) lub **CSV** (do arkusza). Dostęp: każde konto,
także „podgląd” – raport tylko czyta dane.

## Co jest w raporcie

| Sekcja | Źródło | Zakres |
|--------|--------|--------|
| Urządzenia: dostępność %, czas niedostępności | `device_metrics_1h` (agregat godzinowy) | cały miesiąc, do 2 lat wstecz |
| Sprawdzenia: dostępność %, nieudane, śr./maks. opóźnienie | `check_metrics` (surowe) | ostatnie `RETENTION_DAYS` (30 dni) |
| Łącza WAN: pobrane / wysłane, dostępność (SLA), przerwy, najdłuższa | ruch: `interface_metrics_1h` portów z rolą `wan`; SLA: `wan_link_metrics` (surowe) | ruch – cały miesiąc, SLA – 30 dni |
| Alerty rozpoczęte w miesiącu: waga, czas trwania, urządzenie | `alerts` | cały miesiąc |

Gdy surowe dane nie obejmują całego miesiąca, raport podaje, od kiedy liczy sprawdzenia i SLA WAN (`raw_from`).
Podsumowanie u góry: średnia dostępność urządzeń i sprawdzeń (ważona liczbą próbek), dostępność pierwszego łącza WAN
z danymi, liczba alertów (krytyczne / ostrzeżenia). PDF pokazuje 40 najdłuższych alertów, CSV – wszystkie (do 500).

Miesiąc liczony jest w strefie czasowej instalacji (`TZ`). Ruch WAN to średnia godzinowa × godzina, więc to przybliżenie
(dokładność rzędu procent), nie licznik operatora.

## Formaty

- **CSV**: średnik, przecinek dziesiętny, UTF-8 z BOM (Excel po polsku otwiera bez importu). Jeden plik, sekcje
  oddzielone pustym wierszem, każda z nagłówkiem. Nazwa: `uplinkview-raport-RRRR-MM.csv`.
- **PDF**: `fpdf2`, czcionka DejaVu z obrazu (`fonts-dejavu-core` w `backend/Dockerfile`; własna: `NETPULSE_REPORT_FONT`
  i `NETPULSE_REPORT_FONT_BOLD`). Bez czcionki TTF raport powstaje Helvetiką bez polskich znaków.

## API

- `GET /api/reports/monthly?month=RRRR-MM` – JSON (podgląd w panelu),
- `GET /api/reports/monthly.csv?month=…`, `GET /api/reports/monthly.pdf?month=…` – pobranie (`Content-Disposition`).

Bez `month` – poprzedni pełny miesiąc; miesiąc z przyszłości – 422.

## Kod

- `backend/netpulse/report.py` – zbieranie danych (`build`), `to_csv`, `to_pdf`, formatowanie liczb po polsku.
- `backend/netpulse/api/reports.py` – trasy; PDF renderowany w wątku (`asyncio.to_thread`).
- Panel: `frontend/src/pages/ReportsPage.tsx` (grupa menu „Zdarzenia”).
- Testy: `tests/test_report.py` (bez bazy: zakres miesiąca ze zmianą czasu, CSV, PDF z czcionką i bez),
  `tests/test_report_db.py` (baza: dostępność, ruch i SLA WAN, sprawdzenia, alerty, pobrania).

## Dalej (do decyzji)

- Wysyłka raportu e-mailem pierwszego dnia miesiąca (kanał e-mail z powiadomień).
- Zapis raportów miesięcznych w bazie – wtedy sprawdzenia i SLA WAN nie tracą danych po 30 dniach.
