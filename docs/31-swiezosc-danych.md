# Świeżość danych – awaria urządzenia ≠ brak danych (0.59.0)

## Problem

Status urządzenia (`działa` / `brak odpowiedzi`) zapisuje w bazie kolektor: SNMP, UniFi, OPNsense albo raport
agenta. Jeśli kolektor przestał działać (kontener stoi, pętla integracji się zawiesiła, baza była niedostępna),
w bazie zostawał ostatni zapis i panel dalej pokazywał „działa” ze starym odczytem. Wymaganie ze specyfikacji
(rozdz. 25 i 30): *jeśli kolektor nie działał od 10 minut, status urządzenia ma być nieznany, a nie „działa” ani „down”*.

## Reguła

Każdy zapis statusu ustawia też `last_polled_at` (czas ostatniego werdyktu). Werdykt jest **nieaktualny**, gdy jest
starszy niż `max(120 s, 4 × NETPULSE_POLL_INTERVAL)` (przy 30 s to 2 minuty). Kod: `backend/netpulse/freshness.py`.

| Sytuacja | Pokazany stan |
|---|---|
| Kolektor odpytał, urządzenie odpowiedziało | działa |
| Kolektor odpytał, brak odpowiedzi | brak odpowiedzi |
| Kolektor nie wydał werdyktu od ponad 2 min | **brak aktualnych danych** (`status = "unknown"`, `stale = true`) |
| Nigdy nie odpytane | nieznany |

## API

- `GET /api/devices` i `/api/devices/{id}`: `status` = stan do pokazania, `stale` = dane nieaktualne,
  `last_status` = ostatni zapisany werdykt (np. „down” sprzed 10 min).
- `GET /api/dashboard/summary`: urządzenia z nieaktualnym werdyktem liczą się do `unknown`, nie do `up`/`down`.
- Tabele i paski (`/api/collections/devices`), topologia, agenci
  używają tej samej reguły (`Device.live_status`, w SQL `freshness.status_sql`).
- `GET /api/checks`: sprawdzenie, które nie wykonało się od `max(120 s, 4 × interval_s)`, ma `status = "unknown"`
  i `stale = true`.

## Alerty

- Urządzenie z nieaktualnym werdyktem **nie otwiera** alertu „nie odpowiada”.
- Otwarte alerty takiego urządzenia **trwają bez zmian**: brak danych to nie powrót do normy, więc nie przychodzi
  fałszywe „zakończony”. Kończą się dopiero po świeżym odczycie.
- Serwer z agentem, który przestał wysyłać raporty, kolektor co cykl potwierdza jako „brak odpowiedzi”
  (`mark_silent_agents`). Bez tego po 2 minutach zmieniłby się w „brak aktualnych danych”.

## Panel

Plakietka **„brak aktualnych danych”** (kolor ostrzegawczy) na kartach i w tabeli urządzeń, na stronie urządzenia
(z paskiem wyjaśnienia) i w Ustawieniach → Urządzenia. Podpowiedź: kiedy był ostatni odczyt i co wtedy pokazał.
Sprawdzenia dostępności mają taką samą plakietkę. Wspólne funkcje: `deviceState` i `staleHint` w
`frontend/src/components/widgets/DevicesWidget.tsx`.

## Jak sprawdzić na serwerze

1. Po `uplinkview update` panel działa jak dotąd (wszystkie urządzenia „działa”).
2. Zatrzymaj kolektor: `docker stop netpulse-collector-1`.
3. Po około 2 minutach karty urządzeń pokazują „brak aktualnych danych”, a podpowiedź mówi, kiedy był ostatni odczyt.
   Nie przychodzą powiadomienia „nie odpowiada” ani „zakończony”.
4. `docker start netpulse-collector-1` – po pierwszym cyklu (30 s) stan wraca do „działa”.
