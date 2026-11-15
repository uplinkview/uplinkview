# Moduły (od 0.18.0)

**Ustawienia → Moduły** pozwala wyłączyć integracje, z których się nie korzysta:

| Moduł | Co obejmuje |
|-------|-------------|
| OPNsense API | Ustawienia → OPNsense, karta OPNsense na stronie urządzenia, źródło wykresu „Urządzenie w sieci (OPNsense)”, reguły „brama nie działa”, „usługa nie działa”, „utrata pakietów na łączu WAN” |
| UniFi | strony Klienci i Topologia, Ustawienia → Kontrolery UniFi, PoE na kartach switchy |
| Agenci serwerów | Ustawienia → Agenci serwerów, serwery z agentem na pulpicie, źródła wykresu „Serwer z agentem: …”, reguły „kontener”, „usługa”, „SMART”, „temperatura” |
| Kopia zapasowa z panelu | Ustawienia → Kopia zapasowa (kopie przed aktualizacją robione są zawsze) |

## Co robi wyłączenie

- pozycje modułu znikają z menu, z edytora wykresów i z formularza reguł alertów (wejście na adres modułu
  przekierowuje na pulpit);
- pętla modułu w kolektorze nie łączy się z niczym i niczego nie zapisuje;
- urządzenia modułu (serwery z agentem, urządzenia UniFi bez SNMP) nie pojawiają się na liście urządzeń, na pulpicie
  ani w alertach. Alerty reguł modułu się kończą;
- agent wysyłający raporty przy wyłączonym module dostaje odpowiedź „nie zapisano” i działa dalej po cichu;
- dodanie kontrolera UniFi, klucza OPNsense czy agenta zwraca komunikat „Moduł … jest wyłączony”.

**Nic nie jest kasowane.** Konfiguracja, urządzenia i historia zostają w bazie. Po ponownym włączeniu wszystko
wraca, a dane zbierają się od nowa.

## Zużycie zasobów

Wyłączony moduł oszczędza głównie miejsce w panelu. Pętle integracji bez konfiguracji i tak wykonują tylko jedno
małe zapytanie do bazy na cykl. Na obciążenie serwera wpływają przede wszystkim liczba urządzeń, interwał
odpytywania (`NETPULSE_POLL_INTERVAL`) i czas przechowywania metryk (`NETPULSE_RETENTION_DAYS`).

## Stan początkowy

Stan jest w `app_settings` (klucz `modules`). Kolektor zapisuje go przy pierwszym starcie wersji 0.18:

- **nowa instalacja**: UniFi, OPNsense API i agenci wyłączeni, kopia zapasowa włączona;
- **aktualizacja**: włączone jest to, co ma już konfigurację (np. dodany kontroler UniFi), więc nic nie znika.

Zmieniać moduły może tylko administrator. Ustawienie dotyczy całej instalacji.

Kod: `backend/netpulse/modules.py` (stan, `require_module`, `hidden_drivers`), `api/modules_api.py`
(`GET`/`PUT /api/modules`), panel: `frontend/src/lib/modules.ts`, pole `module` w `frontend/src/modules.tsx`.
Nowa integracja = nowy identyfikator w `MODULES` i oznaczenie jej stron w rejestrze modułów.
