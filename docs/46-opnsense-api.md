# OPNsense przez API (0.81.0)

SNMP (`docs/45-opnsense.md`) daje ruch portów, CPU, RAM i dysk, ale nie wie nic o bramach, usługach ani sieci za
OPNsense. Od 0.81.0 urządzenie OPNsense może mieć **klucz API** (Ustawienia → OPNsense, moduł „OPNsense API”).
Sprawdzone 14.11.2026 na OPNsense 26.7.9 w VirtualBox (192.168.1.135, `em1` = WAN z DHCP, `em0` = LAN 192.168.10.1,
DHCP z dnsmasq); zanonimizowane odpowiedzi: `backend/tests/fixtures/opnsense_api/`.

## Co daje API

| Dane | Punkt API (tylko GET) | Gdzie w UplinkView |
|------|-----------------------|--------------------|
| Wersja i aktualizacja | `core/firmware/status` (`product.product_version`, `product_latest`) | strona urządzenia, Ustawienia → OPNsense (plakietka „aktualizacja …”) |
| Bramy: stan, opóźnienie, utrata, jitter | `routes/gateway/status` | metryki `gateway_up`, `wan_latency_ms`, `wan_loss_percent`, `wan_jitter_ms`; wykres „Opóźnienie WAN”; alerty |
| Interfejsy: nazwa (WAN/LAN), port, adres, trasa domyślna | `interfaces/overview/interfaces_info` | strona urządzenia; przypisanie bramy do portu |
| Usługi | `core/service/search` | metryka `opnsense_service_up`; strona urządzenia; alert |
| Dzierżawy DHCP | `dnsmasq/leases/search`, potem `kea/leases4/search`, potem `dhcpv4/leases/search_lease` (ISC) | „Urządzenia w sieci” na stronie urządzenia |
| Tablica ARP | `diagnostics/interface/get_arp` (bez wpisów `permanent` – własne adresy OPNsense) | jw., urządzenia z adresem stałym |

Wersja i bramy są wymagane (bez nich test klucza się nie udaje). Pozostałe punkty są opcjonalne: brak uprawnień (403)
albo brak usługi (404) = pusta sekcja, nie błąd.

### Bramy

- Pomiar jest tylko dla bramy z **monitorowaniem** (System → Gateways → Configuration → odznaczyć
  „Disable Gateway Monitoring”, Monitor IP np. 8.8.8.8). Brama bez monitorowania ma w API `monitor: "~"` – UplinkView
  pokazuje ją jako „bez monitorowania” i nie zapisuje dla niej nic (stan „Online” w API to wtedy tylko domysł OPNsense).
- `status: "down"` albo `status_translated: "Offline"` = brama nie działa; `loss`/`delay` (ostrzeżenia dpingera) –
  działa.
- Brama → port: po adresie bramy na liście `gateways` interfejsu. Interfejs z trasą `default` = brama w użyciu
  („aktywna”).
- Metryki łącza (`wan_*`) mają klucz = port (`em1`), jak pomiary bramy UniFi, więc działa to samo źródło wykresu
  „Opóźnienie WAN” (serie: opóźnienie, utrata, jitter, dostępność) i te same reguły. `gateway_up` ma klucz = nazwa bramy.
- Stan bram trafia do Łączy WAN (`wan_links.apply_controller`, jak informacja z kontrolera UniFi): działa / nie działa
  i które łącze jest aktywne. Kolektor SNMP używa tego w następnym cyklu (aktywne łącze, alert przełączenia WAN).

### Usługi

Klucz usługi = `id` z API, nie `name`: dpinger występuje raz na bramę (`dpinger/WAN_DHCP`, `dpinger/:watcher:`)
z tym samym `name`.

### Ruch urządzeń w sieci (0.83.0)

Punkt `diagnostics/traffic/top/<id,id>` (identyfikatory sieci LAN: interfejsy z adresem, bez bramy i trasy domyślnej,
bez `lo*`) – OPNsense sam próbkuje ruch przez kilka sekund: 3–4 s przy ruchu, ok. 11 s bez ruchu (`status: "timeout"`,
puste rekordy), stąd limit czasu 30 s. Sprawdzone 14.11.2026 na 26.7.9 kontra licznik interfejsu
(`diagnostics/traffic/interface`):

- `cumulative_bytes_in|out` = bajty z **jednej sekundy** próbki → b/s = bajty × 8 (zgodność 98–100 %).
  `rate_bits_*` wychodzi stale o połowę za mało – nieużywane.
- `*_in` = ruch **do** adresu (urządzenie pobiera), `*_out` = **od** adresu (wysyła) – sprawdzone jednostronnym
  pobieraniem.
- Rekord z adresem z sieci LAN = ruch tego urządzenia. Rekord z adresem spoza sieci (internet) ma w `details`
  rozmówców z LAN – UplinkView odwraca kierunek i dzieli ruch proporcjonalnie do ich bajtów (`apply_traffic`).
  **Nie sprawdzone na prawdziwym ruchu do internetu** (testowa maszyna w LAN nie miała dostępu do sieci).
  Własny adres OPNsense jest pomijany.
- Każde znane urządzenie (DHCP/ARP) w mierzonej sieci dostaje wartość, także 0 – średnie na wykresie są uczciwe.

Zapis: metryki `client_down_bps` / `client_up_bps` w `metrics` na urządzeniu OPNsense, klucz = MAC. Panel: kolumny
„Pobiera” / „Wysyła” w „Urządzeniach w sieci” (sortowanie po ruchu), wykres pobierania 5 najaktywniejszych urządzeń
i źródło wykresu „Urządzenie w sieci (OPNsense)” (`lan_client`, serie `down_bps`/`up_bps`). To chwilowa próbka
co 30 s (bieżące obciążenie), nie suma bajtów. Brak uprawnień (403/404) = brak kolumn; błąd odczytu – komunikat
nad tabelą (`traffic` w `GET /api/opnsense/devices/{id}`).

## Alerty

Nowy zestaw reguł domyślnych (`DEFAULT_RULE_SETS` w `alerts.py`) – każda instalacja dostaje go sam po aktualizacji
do 0.81.0; reguły działają dopiero z włączonym modułem i kluczem API:

| Reguła | Rodzaj | Próg |
|--------|--------|------|
| OPNsense: brama nie działa | `gateway_down` (stan `gateway_up`, filtr = nazwa bramy) | 60 s, krytyczny |
| OPNsense: usługa nie działa | `opnsense_service_failed` (stan `opnsense_service_up`, filtr = id usługi) | 120 s, ostrzeżenie |
| Duża utrata pakietów na łączu WAN | metryka `wan_loss_percent` > 20 % | 300 s, ostrzeżenie |

Opóźnienie łącza (`wan_latency_ms`) to ta sama metryka co z bramy UniFi – reguła progowa działa dla obu.
Wyłączony moduł „OPNsense API” ukrywa rodzaje `gateway_down`, `opnsense_service_failed` i metrykę `wan_loss_percent`.

## Kod

- `backend/netpulse/opnsense.py` – klient (`httpx`, HTTP Basic klucz:sekret, `verify_tls` domyślnie wyłączone – OPNsense
  ma certyfikat samopodpisany) i parsery (czyste funkcje, testy `tests/test_opnsense.py`).
- `backend/netpulse/opnsense_collector.py` – co 30 s (`poll_interval`) dla każdego włączonego klucza: metryki w `metrics`,
  stan i ostatni odczyt (`snapshot`, JSONB) w `opnsense_apis`, łącza WAN. Błąd odczytu = `status = "down"` i `last_error`;
  ostatni udany odczyt zostaje.
- `backend/netpulse/api/opnsense.py` – `/api/opnsense/apis` (CRUD, tylko administrator, klucz i sekret nie wracają –
  tylko końcówka klucza), `/probe` (test bez zapisu), `/devices/{id}` (dane do strony urządzenia, każda rola).
- Tabela `opnsense_apis` (migracja 0020): jeden klucz na urządzenie, `api_key`/`api_secret` zaszyfrowane
  (`SECRET_COLUMNS`).
- Moduł `opnsense` (`modules.py`, `ADDED_LATER`): na instalacjach sprzed 0.81.0 startuje wyłączony, na nowej – jak
  inne integracje.
- Panel: `pages/settings/OpnsenseSettingsPage.tsx`, `pages/OpnsenseCard.tsx` (strona urządzenia), `lib/opnsense.ts`.

## Konfiguracja OPNsense

1. System → Access → Users → +: nazwa np. `uplinkview`, „Generate a scrambled password”, grupa `admins`.
2. Edycja użytkownika → API keys → + – pobiera się plik `key=…` / `secret=…` (sekret tylko w tym pliku).
3. Monitorowanie bramy (opóźnienie, utrata, alert awarii): System → Gateways → Configuration.
4. Dostęp od strony WAN: Firewall → Rules → WAN – Pass, TCP, źródło = serwer UplinkView, cel „This Firewall”,
   port panelu (zwykle 443). Protokół musi być TCP – przy „any” OPNsense nie przyjmuje portu docelowego.

UplinkView używa tylko odczytów (GET), ale z grupą `admins` klucz pozwala na wszystko. Ograniczone uprawnienia
(osobna grupa z samymi stronami statusu) – w etapie 2.

## Do zrobienia (zapisane 14.11.2026)

Lista z wiedzy o API OPNsense – **przed budową każdego punktu sprawdzić go sondą na prawdziwym OPNsense 26.7**
(tylko GET, dane logowania nie są wypisywane) i zapisać zanonimizowaną odpowiedź w `tests/fixtures/opnsense_api/`.
Kolejność według wartości dla użytkownika:

1. **Ruch na urządzenie w sieci** (`diagnostics/traffic/top`): ✅ część A (0.83.0, opis wyżej) – ruch na stronie
   urządzenia, historia, wykres. Część B: strona Klienci z danymi OPNsense dla użytkowników bez UniFi (`known_clients`)
   i sprawdzenie podziału ruchu do internetu, gdy maszyna w LAN będzie miała dostęp do sieci.
2. **DNS – Unbound**: zapytania, zablokowane przez listy blokad, najczęstsze domeny i klienci (jak Pi-hole);
   wykresy, alert przy nagłym skoku zapytań.
3. **IDS – Suricata** (`ids/service/query_alerts`): wykryte zdarzenia (sygnatura, źródło, cel, waga), alert przy
   groźnym zdarzeniu, lista na stronie urządzenia.
4. **VPN**: WireGuard (klienci, ostatni handshake, przesłane dane), OpenVPN (sesje), IPsec (tunele w górze/w dole);
   alerty „tunel nie działa” i „nowe połączenie” – jak VPN z UniFi (`docs/30-vpn.md`).
5. **Zapora**: liczba stanów względem limitu (ostrzeżenie przed przepełnieniem), liczniki reguł (ruch, blokady),
   dziennik zapory (ostatnie blokady, najczęściej blokowane adresy).
6. **Zdrowie systemu**: temperatury, mbufy, błędy interfejsów (dokładniej niż SNMP), komunikaty systemu (raporty
   awarii, ostrzeżenia konfiguracji), certyfikaty z datą ważności (alert przed wygaśnięciem), dynamiczny DNS
   (czy adres się zaktualizował), CARP (który OPNsense jest główny, alert przy przełączeniu).
7. **Historia ruchu – Insight / NetFlow** (gdy włączony w OPNsense): ruch według hostów, portów i protokołów,
   raporty „kto zużył najwięcej w miesiącu”.
8. **Akcje (zapis)** – na końcu i tylko po osobnej decyzji: restart usługi, zablokowanie urządzenia, aktualizacja.
   Wymagają uprawnień zapisu, potwierdzeń w panelu i wpisów w dzienniku zdarzeń.

Przy pierwszym z tych etapów także:
- minimalne uprawnienia użytkownika API zamiast `admins` (sprawdzić, które uprawnienia otwierają każdy punkt API),
- nazwy interfejsów z API (WAN/LAN) jako etykiety portów – kolektor SNMP nadpisuje dziś etykiety co cykl, trzeba
  to rozwiązać w kolektorze.

Bez sprzętu, nie sprawdzone: klaster CARP (dwa OPNsense), kilka bram WAN.
