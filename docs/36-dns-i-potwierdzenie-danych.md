# DNS i potwierdzenie danych (0.64.0)

## Sprawdzenie DNS

Ustawienia → Dostępność → **Dodaj sprawdzenie**, rodzaj **DNS**.

| Pole | Znaczenie |
|------|-----------|
| Nazwa | nazwa do rozwiązania, np. `nas.lan`, `example.com`; dla PTR `34.1.168.192.in-addr.arpa` |
| Typ rekordu | A, AAAA, CNAME, MX, TXT, NS, PTR |
| Serwer DNS | puste = serwer systemu (w kontenerze kolektora – DNS Dockera, który pyta serwery hosta); np. `192.168.1.1`, `8.8.8.8` |
| Port | puste = 53 |
| Oczekiwana odpowiedź | opcjonalnie; wartości po przecinku, które muszą być w odpowiedzi. Adresy IP porównywane dokładnie (`192.168.1.3` ≠ `192.168.1.34`), dla MX wystarczy nazwa serwera poczty, dla TXT fragment tekstu (kilka – po średniku) |

Wynik: czas odpowiedzi (wykres i alert `check_latency_ms` jak dla innych sprawdzeń), stan i ostatnia odpowiedź
(`last_answer`, np. `192.168.1.34` albo `CNAME example.com, 192.0.2.10`). Niedostępne, gdy:

- serwer nie odpowiedział w limicie czasu,
- kod odpowiedzi to NXDOMAIN (nazwa nie istnieje), SERVFAIL, REFUSED…,
- brak rekordu danego typu,
- odpowiedź nie zawiera oczekiwanej wartości.

Alert „sprawdzenie nie przechodzi” (`check_down`) działa bez zmian.

### Kod

- `backend/netpulse/dnsquery.py` – własny klient DNS (RFC 1035), bez biblioteki: UDP, przy obciętej odpowiedzi (TC) to samo
  przez TCP, kompresja nazw, `missing_expected`.
- `checks.py` → `dns_check`, `run_check(kind="dns", dns_type=…, dns_server=…)`; oczekiwana odpowiedź w polu `keyword`,
  port serwera w `port`.
- Migracja `0016`: `checks.dns_type`, `checks.dns_server`, `checks.last_answer`.
- API: `dns_type`, `dns_server` w `CheckIn`/`CheckOut`, `last_answer`, `answer` w wyniku testu.
- Testy: `tests/test_dns_check.py` (atrapa serwera DNS na UDP i TCP).

## Potwierdzenie danych

Specyfikacja wymaga, żeby system pokazywał, które dane zostały rzeczywiście potwierdzone. UplinkView prowadzi rejestr
źródeł danych z poziomem:

| Poziom | Znaczenie |
|--------|-----------|
| `verified` – potwierdzone | sprawdzone na prawdziwym sprzęcie (zanonimizowany zrzut w `tests/fixtures`) albo mierzone przez sam UplinkView |
| `partial` – częściowo | część przypadków sprawdzona, reszta tylko na atrapie (np. MikroTik: system tak, czujniki, PoE i SFP nie) |
| `test` – dane testowe | tylko zrzuty syntetyczne według oficjalnych MIB albo atrapy API |

Gdzie to widać:

- **Ustawienia → System → Potwierdzenie danych** – pełna lista źródeł z opisem, na czym je sprawdzono.
- **Strona urządzenia** – plakietka „dane testowe” albo „częściowo potwierdzone” (najsłabszy poziom źródeł jego
  drivera; MikroTik: system potwierdzony, czujniki/PoE/SFP nie → „częściowo”). Potwierdzone urządzenia nie mają plakietki.
  Plakietka prowadzi do listy w Ustawieniach.

### Kod

- `backend/netpulse/verification.py` – `SOURCES` (jedyne miejsce z tą wiedzą), `device_level(driver)`.
  **Po sprawdzeniu źródła na prawdziwym sprzęcie zmień tam jego poziom i opis.**
- `Device.verification` → pole `verification` w `DeviceOut`; `GET /api/system/verification` (każdy zalogowany).
- Panel: `components/Verification.tsx` (`VerificationBadge`, `VerificationCard`).
- `tests/test_verification.py` pilnuje, że każdy driver (`DRIVERS`, `NON_SNMP_DRIVERS`) ma opisane źródło.
