# Zgodność z UniFi, prawdziwa prędkość WAN i testy prędkości bramy (od 0.70.0, 0.71.0, 0.85.0)

## Po co

Wykres ruchu pokazuje **średnią z 30 sekund** (tyle trwa cykl kolektora). Test prędkości z bramy trwa kilka–kilkanaście
sekund, więc 455 Mb/s wyglądało na wykresie jak ok. 100 Mb/s. Pomiar był poprawny (ilość danych się zgadzała), ale
liczby nie pokrywały się z tym, co pokazuje brama. Sprawdzone 12.11.2026 na UCG Ultra: trzy źródła – brama, serwer
lokalny i VPS przez tunel – opisywały ten sam ruch z różnicą poniżej 1 %, tylko w innym oknie czasu.

Od 0.70.0 są dwie rzeczy:

1. **Testy prędkości bramy** – wynik dokładnie taki, jaki podaje UniFi (zgodność 1:1).
2. **Szczyt ruchu WAN** – obok średniej zapisywana jest najwyższa prędkość z ok. 5 sekund.

## Zgodność wykresów z UCG Ultra (od 0.71.0)

Sprawdzone 13.11.2026 na samej bramie (SSH, tylko odczyt). Network na UCG Ultra trzyma historię w PostgreSQL
(`unifi-network`, port 5434, tabele `stats.stat_buckets_of_5_minutes|1_hour|8_hours|1_month`, wartości w CBOR):

- **WAN** (`wanBySite`, `wanBySiteByDevice`): w kubełku suma bajtów `rxBytes`/`txBytes` i najwyższa chwilowa prędkość
  `maxRxRateBps`/`maxTxRateBps` (bajty/s).
- **Porty** (`portBySiteByDevice`, `byPort`): same bajty – bez najwyższej prędkości. Bajty portów switcha są ułamkowe:
  UniFi rozkłada raporty urządzeń (co kilkadziesiąt sekund) na kubełki.
- **Wykres WAN na pulpicie UniFi rysuje średnią z kubełka** (`AVG_RX_RATE_BPS` w kodzie panelu); najwyższa prędkość jest
  tylko w dymku. Najdrobniejsza historia to 5 minut. Test prędkości 455 Mb/s (20:08) to na wykresie UniFi 26,2 Mb/s
  (kubełek 20:05) z najwyższą chwilową prędkością 663 Mb/s.

**Porównanie przed zmianą** (VPS, 13 h, 156 kubełków): sumy bajtów zgodne z UCG co do 0,1–1 % na WAN i na portach LAN
bramy i switcha. Różnice w pojedynczych kubełkach brały się z czasu, nie z pomiaru: odczyt kolektora co 30 s od chwili
startu przecinał granice kubełków, próbka miała czas odczytu (koniec przedziału), a wykres 24 h miał kubełki 288 s.

Od 0.71.0:

1. **Odczyty równo z zegarem** – kolektor czyta urządzenia o :00 i :30 (`rates.wait_for_slot`), więc każda próbka 30 s
   leży w całości w jednym kubełku 5-minutowym i godzinowym.
2. **Próbka w środku swojego przedziału** – czas wiersza w `interface_metrics` i `wifi_metrics` to środek przedziału
   między odczytami (`rates.sample_times`), a chwila odczytu to środek odpytywania (nie jego początek). Pominięty odczyt
   (60–120 s) dzieli się na części po 30 s, przyrosty błędów idą do ostatniej części (`collector.spread`).
3. **Kubełki wykresów z równej drabinki** – 30 s, 1, 2, 5, 10, 15, 30 min, 1 h (`aggregates.RAW_BUCKETS_S`, w panelu
   `bucketSeconds`): zakres 24 h = 5 minut, 7 dni = godzina, jak w UniFi.
4. **Linia = średnia z kubełka**, jak w UniFi – od 0.85.0 dla ruchu WAN zastąpiona prawdziwą prędkością z 5 s (niżej).
5. **Niemożliwa szybkość w jednym kierunku odrzuca całą próbkę** – router „dogania” zatrzymane liczniki, drugi kierunek
   z tego odczytu też jest zawyżony (12.11.2026: wysyłanie 75,9 Mb/s na łączu 50 Mb/s podniosło 5 minut z 1,6 do 9,2 Mb/s).

Granice zgodności: UplinkView liczy bajty z liczników SNMP z dokładnością do odświeżania licznika w urządzeniu (UCG Ultra
ok. 1 s). Na portach switcha UniFi sam rozkłada raporty na kubełki,
stąd pojedyncze kubełki mogą się różnić, choć suma się zgadza. Narzędzie porównania (kubełki z bazy bramy kontra
UplinkView) było jednorazowe, poza repo.

## Testy prędkości bramy

Kontroler UniFi podaje w `stat/device` bramy pole `speedtest-status`: pobieranie, wysyłanie, ping, czas testu, czas
trwania, serwer i interfejs łącza. UplinkView czyta to przy każdym odczycie kontrolera (`unifi.parse_speedtest`) i zapisuje
każdy **nowy** test do tabeli `metrics` na bramie, z czasem samego testu i kluczem = interfejs łącza (`eth4`):
`speedtest_down_bps`, `speedtest_up_bps`, `speedtest_ping_ms` (`unifi_collector.save_speedtest`). Ten sam wynik odczytany
ponownie trafia w ten sam wiersz (klucz główny), więc nie ma powtórek.

- Kontroler podaje **tylko ostatni test** – historia buduje się od aktualizacji do 0.70.0; wcześniejszych testów nie ma.
- Test nieudany, trwający albo bez prędkości jest pomijany.
- W panelu: źródło wykresu **„Łącze WAN: testy prędkości bramy”** (`speedtest`; urządzenie = brama, klucz = łącze; serie
  Pobieranie, Wysyłanie, Ping) i szablon **Dodaj widget → Internet → „Testy prędkości bramy”** (wykres słupkowy, 7 dni).
  Kafelek „ostatni test” to zwykły widget „Liczba” z tym źródłem, wartością „ostatnia” i własnym zakresem (np. 7 dni).
- Wymaga modułu UniFi i kontrolera z kluczem API. Bez zmian w bazie.

## Prawdziwa prędkość WAN – jedna linia (0.85.0)

Historia: 0.70.0–0.83.0 miały obok średniej osobne serie „Pobieranie – szczyt” / „Wysyłanie – szczyt” i „maks.” w dymku;
0.84.0 usunęła je razem z pomiarem (nieporozumienie). Użytkownik chciał **jednej linii na kierunek, która pokazuje
prawdziwy ruch**: pobieranie gry 100 GB albo krótki test prędkości ma być widać z prawdziwą prędkością i w czasie, kiedy szło.

Od 0.85.0:

- **Próbnik** `netpulse/wanrate.py` (pętla w kolektorze, `NETPULSE_WAN_SAMPLE_INTERVAL`, domyślnie 0,5 s, 0 = wyłączony)
  czyta same liczniki portów WAN (jedno małe zapytanie SNMP na router, limit czasu 0,8 s, milczący router pomijany 30 s).
- **Przedziały 5 s równo z zegarem** (`SlotTracker`): przyrost licznika między dwiema jego *zmianami* dzielony na przedziały
  proporcjonalnie do czasu – suma bajtów się zgadza przy każdym tempie odświeżania licznika (UCG Ultra ok. 1 s). Przedział
  zapisany, gdy w całości pokryty; luka ponad 60 s, reset licznika i prędkość ponad 1,1× portu zostawiają go pustym.
- **Tabela** `wan_rate_metrics` (migracja 0022, hypertable z kompresją i retencją jak inne metryki; `time` = początek
  przedziału) i agregat `wan_rate_metrics_1h` z **maksimum** godzinowym (`Aggregate(fn="max")`).
- **Wykres** (`/api/dashboard/traffic`, `/api/interfaces/{id}/metrics`): w każdym kubełku najwyższa prędkość z 5 s
  (`api/metrics.fine_series` – suma portów WAN z jednej chwili), a gdzie pomiaru nie ma (dane sprzed 0.85.0, port bez
  roli WAN, przerwa) – średnia z 30 s (`merge_fine`). Kubełki ruchu WAN mają drobniejszą drabinkę
  (`aggregates.FINE_BUCKETS_S`: 5, 10, 15 s): 15 min = 5 s, 1 h = 15 s, 24 h = 5 min, 7 dni = 1 h. Na krótkim zakresie
  i po przybliżeniu zaznaczeniem widać prędkość i czas trwania; na długim punkt to najwyższa prędkość w swoim przedziale
  (krótki skok nie znika, ale zajmuje cały kubełek – szczegóły po przybliżeniu). `interval_s` w odpowiedzi ≥ 30 s,
  żeby panel nie rysował luk między punktami średniej.
- Bajty (licznik zużycia transferu, raport) dalej z `interface_metrics` – maksima nie zawyżają sum.
- To świadome odejście od „wykres 1:1 jak UniFi” (UniFi rysuje średnią kubełka) – na prośbę użytkownika (14.11.2026).
- Zapisane wykresy z seriami `in_bps_max` / `out_bps_max` wczytują się jako Pobieranie / Wysyłanie (`RENAMED_METRICS`).

## API

- `GET /api/dashboard/traffic` – `in_bps`, `out_bps`: najwyższa prędkość z 5 s w kubełku (suma łączy WAN), bez pomiaru – średnia.
- `GET /api/interfaces/{id}/metrics` – to samo dla jednego portu WAN; inne porty – średnia.
- `GET /api/devices/{id}/agent-metrics?source=speedtest&key=<łącze>` – testy prędkości (`down_bps`, `up_bps`, `ping_ms`).
- `GET /api/devices/{id}/agent-keys` – łącza z testem z ostatnich 30 dni w polu `speedtest` (inne źródła: ostatnia godzina).

## Dla programisty

- Atrapa `frontend/dev/mock-api.mjs` zwraca przykładowe testy prędkości.

## Stan

**Pierwszy test na serwerach (12.11.2026, 0.70.0):** brama podała 576 / 51 Mb/s, ping 5 ms. Wynik testu zapisał się na obu
serwerach dokładnie (576,0 / 51,0 / 5). Szczyt: VPS 599 / 59 Mb/s (+4 % / +16 %), serwer domowy 341 / 36 Mb/s – za mało.
Przyczyna: na serwerze domowym jest też MikroTik z portem WAN, który nie odpowiadał; próbnik czekał na jego limit czasu
(2 s i ponowienie) przy każdym odczycie, więc bramę czytał co ok. 4 s zamiast co sekundę. Od 0.70.1 próbnik ma własny,
krótki limit czasu (0,8 s, bez ponowień), a router, który nie odpowiada, jest pomijany na 30 s (`READ_TIMEOUT_S`, `BACKOFF_S`).

Test prędkości: pola sprawdzone 12.11.2026 na prawdziwej bramie (UCG Ultra, wynik 455 / 51 Mb/s, ping 6 ms, 17 s) –
z tej odpowiedzi jest test `test_speedtest_from_real_controller_answer`. Szczyt: logika i zapis w testach; odświeżanie
liczników zmierzone na UCG Ultra (ok. 1 s). Od 0.85.0 do sprawdzenia na serwerze: pobieranie dużego pliku i test prędkości na wykresie 1 h i 24 h kontra brama.
