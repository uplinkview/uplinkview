# Instalacja i aktualizacja UplinkView

## Instalacja (jedna komenda)

Na serwerze Ubuntu:

```bash
curl -fsSL https://raw.githubusercontent.com/uplinkview/uplinkview/main/install.sh | sudo bash
```

Skrypt:
1. instaluje Dockera (jeśli go nie ma),
2. pobiera UplinkView do `/opt/uplinkview`,
3. tworzy `/opt/uplinkview/deploy/.env` z losowym hasłem do bazy,
4. instaluje polecenie `netpulse`,
5. uruchamia usługi: baza (TimescaleDB), kolektor, API.

Pierwsza instalacja trwa kilka minut (pobieranie obrazów i budowanie).

## Dodanie urządzeń

Najwygodniej w panelu: **Ustawienia → Urządzenia → Dodaj urządzenie**. Formularz obsługuje SNMP v1,
v2c i v3, sprawdza połączenie i pokazuje, co wykryto (typ, model, liczba portów), a urządzenia można
też edytować, tymczasowo wyłączyć albo usunąć. Zapisane community i hasła SNMPv3 nigdy nie wracają do
przeglądarki: przy edycji puste pole oznacza „zostaw zapisane”.

To samo z terminala:

```bash
uplinkview device add "UCG Ultra" 192.168.1.1 --community public
uplinkview device add "USW Lite 8 PoE" 192.168.1.2 --community public
uplinkview device add "U6+" 192.168.1.3 --community public
uplinkview device list
```

Przed dodaniem UplinkView sprawdza połączenie SNMP i pokazuje, co wykrył.
Samo sprawdzenie, bez dodawania:

```bash
uplinkview probe 192.168.1.2 --community public
```

## Sprawdzenie, że działa

- `uplinkview status` – stan usług (db, collector, api)
- `uplinkview device list` – status urządzeń i czas ostatniego odczytu
- `http://IP-serwera:PORT` – panel (Dashboard z kartami urządzeń)
- `http://IP-serwera:PORT/docs` – interaktywne API; np. `GET /api/devices/1/interfaces`
  pokazuje porty z bieżącym ruchem (`in_bps`, `out_bps` w bitach/s)

Metryki ruchu pojawiają się po drugim odczycie (ok. 1 minuty po dodaniu urządzenia),
bo przepływ liczony jest z różnicy liczników.

## Aktualizacja

Z panelu: **Ustawienia → Aktualizacja** (szczegóły, bezpieczeństwo i kopie bazy: [`07-aktualizacja-z-panelu.md`](07-aktualizacja-z-panelu.md)). Z terminala:

```bash
uplinkview update
```

Pobiera najnowszą wersję z GitHuba, pokazuje listę zmian, przebudowuje i restartuje
usługi. Dane i konfiguracja zostają. Jeśli nie ma nic nowego – nic nie robi
(wymuszenie: `uplinkview update --force`).

## Pozostałe polecenia

| Polecenie                 | Co robi                                 |
|---------------------------|-----------------------------------------|
| `uplinkview status`         | stan kontenerów                         |
| `uplinkview logs`           | logi wszystkich usług (Ctrl+C kończy)   |
| `uplinkview logs collector` | logi tylko kolektora                    |
| `uplinkview restart`        | usługi od nowa z aktualnym `.env`       |
| `uplinkview device remove ID` | usunięcie urządzenia z historią       |
| `uplinkview cleanup`        | zwolnienie miejsca: nieużywane obrazy i cache budowania (baza zostaje) |
| `uplinkview reset`          | wyczyszczenie bazy (urządzenia i historia), konfiguracja zostaje |
| `uplinkview user list`      | konta panelu                            |
| `uplinkview user passwd NAZWA` | nowe hasło (np. zapomniane)          |
| `uplinkview version`        | zainstalowana wersja                    |
| `uplinkview uninstall`      | usunięcie UplinkView                      |

## Miejsce na dysku

Budowanie obrazów (panel w Node + backend w Pythonie) potrzebuje kilku GB wolnego miejsca. Dlatego
`install.sh` i `uplinkview update` sprawdzają je **przed** zmianą czegokolwiek:

- poniżej 4 GB: automatycznie usuwają nieużywane dane Dockera (stary cache budowania i obrazy),
  a baza z historią metryk i konfiguracja nie są ruszane,
- poniżej 2 GB po sprzątaniu: zatrzymują się z komunikatem i podpowiedzią, **bez żadnej zmiany**
  (po zwolnieniu miejsca wystarczy ponowić `uplinkview update`),
- po udanej aktualizacji usuwają cache budowania starszy niż 72 godziny (świeży zostaje, więc
  kolejna aktualizacja jest szybka).

Ręcznie: `uplinkview cleanup`. Gdy dysk jest duży, ale system używa tylko jego części (domyślny układ
LVM w Ubuntu Server): `sudo vgs`, a jeśli `VFree` pokazuje wolne miejsce,
`sudo lvextend -r -l +100%FREE /dev/mapper/ubuntu--vg-ubuntu--lv`.

Jeśli budowanie nie powiodło się z innej przyczyny po pobraniu kodu, usługi działają dalej na
poprzedniej wersji, a po usunięciu przyczyny trzeba uruchomić `uplinkview update --force`
(zwykły `update` powie, że masz już najnowszą wersję).

## Konfiguracja

Plik `/opt/uplinkview/deploy/.env`:

| Zmienna                   | Domyślnie | Opis                              |
|---------------------------|-----------|-----------------------------------|
| `NETPULSE_PORT`           | 8000      | port panelu (HTTP)                |
| `NETPULSE_HTTPS_PORT`     | 8443      | port panelu (HTTPS, od 0.62.0)    |
| `NETPULSE_TLS_NAMES`      | (z instalatora) | adresy w certyfikacie HTTPS |
| `NETPULSE_POLL_INTERVAL`  | 30        | co ile sekund odpytywać urządzenia |
| `NETPULSE_RETENTION_DAYS` | 30        | ile dni trzymać metryki           |
| `NETPULSE_COMPRESS_AFTER_DAYS` | 7    | po ilu dniach baza kompresuje metryki (0 = bez kompresji) |
| `NETPULSE_WAN_SAMPLE_INTERVAL` | 0.25 | co ile sekund czytać liczniki portów WAN do wykresu prawdziwej prędkości co 5 s (0 = sama średnia z 30 s) |

Progi kontroli miejsca (zmienne środowiskowe polecenia, nie `.env`): `NETPULSE_MIN_FREE_MB` (domyślnie
2000), `NETPULSE_WARN_FREE_MB` (4000), `NETPULSE_KEEP_BUILD_CACHE_HOURS` (72), np.
`sudo NETPULSE_MIN_FREE_MB=1000 uplinkview update`.

Cache budowania obrazów (od 0.28.1): po każdej aktualizacji zostaje cache z ostatnich 72 godzin, ale razem nie
więcej niż `NETPULSE_BUILD_CACHE_MAX` (domyślnie `2gb`; dla aktualizacji z panelu – w `.env`). Wcześniej przy wielu
aktualizacjach w krótkim czasie cache potrafił urosnąć do kilku GB. Ręczne sprzątanie: `sudo docker builder prune -af`
(baza i dane zostają, następna aktualizacja zbuduje się raz dłużej).

Po zmianie: `sudo uplinkview restart` (od 0.71.1 tworzy kontenery od nowa z aktualnym `.env`; w starszych wersjach
zmiany wczytywał dopiero `sudo uplinkview start`).

Czasy w `uplinkview device list` są pokazywane w strefie ze zmiennej `TZ` (domyślnie `Europe/Warsaw`).

## Baza ze starszej wersji

Jeśli na serwerze była wcześniej inna (testowa) wersja UplinkView, polecenia mogą zgłosić:
„Baza danych pochodzi ze starszej, niezgodnej wersji UplinkView”. Wtedy:

```bash
uplinkview reset
```

Usuwa urządzenia i historię metryk, zostawia `.env`. Potem dodaj urządzenia ponownie.

## Logowanie

Od wersji 0.2 panel i API wymagają logowania. Zaraz po instalacji otwórz
`http://IP-serwera:PORT` – panel poprosi o założenie konta administratora (kreator, tylko raz).
Szczegóły: [`05-api-i-logowanie.md`](05-api-i-logowanie.md). Zapomniane hasło:
`uplinkview user passwd admin`.

> Nie wystawiaj portu panelu bezpośrednio do internetu – do dostępu z zewnątrz użyj VPN
> albo reverse proxy z HTTPS.
