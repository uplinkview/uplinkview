# VPN użytkowników zdalnych (od 0.57.0)

UplinkView pokazuje, kto jest połączony z serwerem VPN bramy UniFi (WireGuard, a także OpenVPN / L2TP, jeśli kontroler
je zgłasza): od kiedy, skąd, ile przesłał i z jakim ruchem. Dane daje kontroler UniFi (moduł UniFi, klucz API), więc
nie trzeba nic ustawiać – wystarczy skonfigurowany kontroler w Ustawienia → UniFi.

## Skąd dane

Kolektor UniFi co cykl (30 s) czyta z kontrolera (sprawdzone na UCG Ultra, Network 10.x):

| Adres | Co daje |
|-------|---------|
| `rest/networkconf` | serwery VPN: sieci z `purpose = "remote-user-vpn"` (nazwa, typ, port, podsieć) |
| `v2/api/site/<site>/wireguard/users` | skonfigurowani klienci WireGuard (nazwa, adres w tunelu) |
| `stat/remoteuservpn` | trwające połączenia: klient, adres publiczny, czas połączenia, bajty i bieżący ruch |

`rx` w `remoteuservpn` = od klienta (jego wysyłanie), `tx` = do klienta (jego pobieranie); szybkości (`rx_rate`,
`tx_rate`) są **już w b/s** i tak je UplinkView zapisuje. Do 0.71.1 były mnożone ×8 (wykresy, widget i alerty VPN pokazywały
prędkość 8 razy za dużą) – sprawdzone 13.11.2026 na UCG Ultra: 30 MB przez tunel WireGuard to w kontrolerze 66,8 Mb/s
przy ok. 9 MB/s (72 Mb/s) w liczniku `wg show`. Migracja 0019 dzieli zapisaną historię `vpn_down_bps|vpn_up_bps` przez 8. Brak serwera VPN = żadnych dalszych zapytań. Błąd odczytu VPN nie psuje reszty odczytu kontrolera.

**Prędkość w historii z przyrostu bajtów (0.85.5).** `rx_rate`/`tx_rate` to wartość z ok. 1 s – dobra dla widgetu na żywo
(średnio zgodna z jądrem bramy: 44,0 / 44,5 kb/s w 39 s), ale jeden odczyt co 30 s przy ruchu w porywach trafia raz w szczyt,
raz w ciszę. Porównanie 14.11.2026 (tunel WG-VPS `wgsrv2`, 10 min, liczniki `/sys/class/net/wgsrv2/statistics`): port `wgsrv2`
z SNMP i bajty klienta z kontrolera zgodne co do bajta (3,029 / 1,388 MB), historia `vpn_down_bps|vpn_up_bps` −53 % / −27 %.
Od 0.85.5 `vpn.snapshot` liczy prędkość z różnicy `down_bytes`/`up_bytes` od poprzedniego zdjęcia (ta sama sesja – `since`,
licznik nie spadł, przerwa ≤ 150 s, `RATE_MAX_GAP`); inaczej – wartość z kontrolera.

## Gdzie zapisuje

- **Stan** (kto jest połączony, od kiedy, skąd, ostatni transfer) – zdjęcie w `app_settings` pod `vpn:<id kontrolera>`
  (`backend/netpulse/vpn.py`). Klient, który się rozłączył, zostaje z czasem ostatniego połączenia i ostatnim transferem.
- **Metryki** w ogólnej tabeli `metrics`, na urządzeniu bramy, klucz = nazwa klienta:
  `vpn_connected` (1/0 dla każdego znanego klienta), `vpn_down_bps`, `vpn_up_bps` (tylko w trakcie połączenia).
  Bez migracji bazy.

## W panelu

- **Widget „VPN”** (Dodaj widget → Internet i WAN → Klienci VPN): serwery, klienci z kropką stanu, „połączony od”,
  adres w tunelu i adres publiczny, przesłane dane, bieżący ruch ↓↑. W ustawieniach: wszyscy klienci albo tylko połączeni.
  Na pulpicie publicznym bez adresów (ani publicznego, ani w tunelu).
- **Źródło wykresu „Klient VPN”**: brama → klient; serie: pobieranie, wysyłanie, połączony (1/0).
- **Zdarzenia**: „Połączenie VPN: <klient>” w kafelku „Zdarzenia”.
- **Alert „Nowe połączenie VPN”** (`vpn_connect`, informacja, domyślnie włączony): trwa 10 minut, bez powiadomienia
  o końcu. Nowe połączenie = próbka `vpn_connected` 1 po próbce 0 (przerwa w odczytach dłuższa niż 150 s się nie liczy).

## Na żywo (0.72.0)

Kontroler odświeża `stat/remoteuservpn` (bajty i prędkość) co ok. 1 s (zmierzone na UCG Ultra), więc widget VPN nie
czeka na cykl kolektora: WebSocket `/api/live/vpn` (`VpnLiveHub` w `api/live.py`) co ~1,5 s czyta trwające sesje ze
wszystkich włączonych kontrolerów (tylko gdy ktoś ogląda, bez zapisu do bazy) – `{time, ok, users: [...]}`. Panel
(`useLiveVpn` w `lib/liveHub.ts`, `withLiveVpn` w `lib/vpn.ts`) łączy to z `/api/vpn`: klient z próbki = połączony
z bieżącą prędkością i transferem, połączony w `/api/vpn`, a nieobecny w próbce = rozłączony, nowy klient jest dopisany.
`ok = false` (żaden kontroler nie odpowiedział, moduł UniFi wyłączony) = widget zostaje przy odczycie kolektora.
Przełącznik „Na żywo” w pasku górnym wstrzymuje też ten kanał; na pulpicie publicznym go nie ma. Historia (wykres, alert
„Nowe połączenie VPN”) dalej z kolektora co 30 s.

API: `GET /api/vpn` (`backend/netpulse/api/vpn.py`); `stale = true`, gdy ostatni odczyt jest starszy niż 3 minuty –
wtedy nikt nie jest pokazywany jako połączony.

## Interfejs, który znika z SNMP

Interfejs WireGuard bramy (`wgsrv1`) jest w SNMP tylko w trakcie połączenia. Wcześniej panel pokazywał wtedy ostatni
stan („działa”). Od 0.57.0:

- driver UniFi daje mu rolę `vpn` i nazwę sieci VPN (np. „WG-Home”);
- kolektor ustawia każdemu interfejsowi, którego nie ma w odczycie, stan `notPresent` (bez próbek – więc bez alertu
  „port nie działa” i bez fałszywego skoku ruchu po powrocie);
- panel pokazuje na stronie urządzenia „brak sesji” (VPN) albo „nieobecny”; od 0.65.1 tabela i paski portów na pulpicie
  (kolekcja `ports`) pomijają taki interfejs – wraca sam, gdy pojawi się w odczycie (nowa sesja).
