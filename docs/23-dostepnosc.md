# Sprawdzanie dostępności (od 0.30.0)

Strona **Dostępność** (od 0.58.3 w Ustawieniach, `/settings/checks`; stary adres `/checks` przekierowuje): sprawdzenia, które UplinkView wykonuje sam, niezależnie od SNMP i agentów.

| Rodzaj | Co mierzy | Kiedy „niedostępne” |
|---|---|---|
| **Ping** | opóźnienie (średnia z 5 pakietów co 0,2 s), utrata pakietów w %, jitter | żaden pakiet nie wrócił, host nie istnieje |
| **HTTP(S)** | czas odpowiedzi, kod HTTP, dni do wygaśnięcia certyfikatu (https) | błąd połączenia, kod spoza oczekiwanych (domyślnie 200–399), brak tekstu na stronie |
| **Port TCP** | czas nawiązania połączenia | port zamknięty albo brak odpowiedzi w limicie czasu |

Ping do publicznego DNS (np. `8.8.8.8`) to **jakość łącza**: wzrost opóźnienia, utrata pakietów i jitter widać
zanim spadnie ruch WAN. Uwaga: niektóre sieci nie przepuszczają pingu do części adresów (u nas `1.1.1.1` nie
odpowiada nawet z serwera, `8.8.8.8` tak) – wtedy wybierz inny cel.

Od 0.64.0 także **DNS** (rozwiązywanie nazwy, czas, zgodność odpowiedzi) – opis w `docs/36-dns-i-potwierdzenie-danych.md`.

## Ustawienia sprawdzenia

- **Sprawdzaj co** – 30 s … 1 godz. (API przyjmuje 10–3600 s); **limit czasu** 1–30 s, krótszy niż odstęp.
- **HTTP**: oczekiwany kod (`200`, `200-399`, `2xx`, lista po przecinku), opcjonalny tekst na stronie (szukany
  w pierwszym megabajcie), weryfikacja certyfikatu – wyłącz dla samopodpisanych (Proxmox, router); datę wygaśnięcia
  UplinkView odczyta i tak (osobne połączenie TLS bez weryfikacji). Przekierowania są śledzone.
- **Sprawdź teraz** w formularzu wykonuje sprawdzenie od razu, bez zapisu.
- **Szybko dodaj** (od 0.30.3): ping do bramy każdego włączonego routera z listy urządzeń („Brama – UCG Ultra”:
  awaria w sieci domowej czy u dostawcy?), ping do publicznych DNS i strona www; gotowe sprawdzenia, których cel już
  jest sprawdzany, znikają z listy.

## Alerty

Ustawienia → Reguły alertów:

| Reguła | Opis |
|---|---|
| **Sprawdzenie dostępności nie przechodzi** (`check_down`) | domyślna (1 min, ostrzeżenie); pole „Tylko o nazwie” zawęża do sprawdzeń, np. `Internet*` |
| Metryka **Sprawdzenie dostępności: opóźnienie** (`check_latency_ms`) | próg w ms przez wybrany czas, osobno dla każdego sprawdzenia |
| Metryka **utrata pakietów (ping)** (`check_loss_percent`) | próg w % |
| Metryka **dni do wygaśnięcia certyfikatu** (`check_cert_days`) | domyślna „Certyfikat HTTPS wkrótce wygaśnie”: `< 14` dni |

Reguły sprawdzeń nie dotyczą urządzeń (bez wyboru urządzenia). Ciągłość warunku liczona jest z własnym odstępem
sprawdzenia, więc sprawdzenie co 5 min nie „gubi” danych w regule „przez 10 min”.

## Pulpit

- Wykres, liczba z mini-wykresem: źródło **Sprawdzenie dostępności** – `latency_ms`, `loss_percent`, `jitter_ms`,
  `availability_percent` (odsetek udanych sprawdzeń w kubełku), `cert_days`.
- Tabela i paski: kolekcja **Sprawdzenia dostępności** (`checks`) – `up`, `latency_ms`, `loss_percent`,
  `availability_percent` (z 24 h), `cert_days`; bez adresów celu (pulpit publiczny).
- Oś stanów: sekcja „Sprawdzenia dostępności” w edytorze (`items` z `kind: "check"`).

## Jak to działa

- `backend/netpulse/checks.py` – same sprawdzenia. Ping bez uprawnień roota: gniazdo `SOCK_DGRAM` + `IPPROTO_ICMP`
  (Docker domyślnie ustawia `net.ipv4.ping_group_range = 0 2147483647`, więc działa w kontenerze kolektora jako
  użytkownik `netpulse`); jądro liczy sumę kontrolną i identyfikator, odpowiedzi rozpoznajemy po numerze sekwencji.
  Bez zewnętrznej biblioteki.
  Gniazdo obsługujemy sami (`sendto` + `add_reader`): API działa na uvloop, który nie ma `loop.sock_sendto`
  (w 0.30.0 „Sprawdź teraz” dla pingu kończył się `NotImplementedError`; poprawione w 0.30.1).
- `backend/netpulse/checks_collector.py` – pętla w procesie kolektora: co 5 s wybiera sprawdzenia, których odstęp
  minął, wykonuje je równolegle (najwyżej 20), zapisuje wynik w `check_metrics` (hypertable, retencja jak inne
  metryki) i stan w `checks` (`status`, `status_since`, `last_error`, `last_latency_ms`).
- `backend/netpulse/api/checks.py` – `GET/POST /api/checks`, `PUT/DELETE /api/checks/{id}` (zmiany: administrator),
  `POST /api/checks/test`, `GET /api/checks/{id}/metrics?minutes=&offset=`. Migracja `0010`.
- Panel: `frontend/src/pages/ChecksPage.tsx`, `lib/checks.ts`; źródło `check` w `lib/layout.ts` i `chartSource.ts`.

Sprawdzone na serwerze 27–28.10.2026 w kontenerze kolektora: ping 8.8.8.8 i google.com (~15 ms, 0% utraty),
brama 192.168.1.1 (~1 ms), HTTPS github.com (certyfikat 33 dni), panel Proxmoxa `https://192.168.1.86:8006`
bez weryfikacji certyfikatu, port TCP 8006, zamknięty port, nieistniejący host, wygasły certyfikat.
