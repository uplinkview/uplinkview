# Licencje pobierane z zewnętrznego serwisu – propozycja

## Decyzja (13.11.2026, wersja 0.79.0)

- **Model biznesowy: wszystko, co użytkownik instaluje u siebie, jest darmowe i bez limitów; płatna jest tylko chmura**
  (`docs/39-chmura-propozycja.md`: dostęp z zewnątrz, push na telefon, wiele sieci na jednym koncie). To odmiana modelu A
  z tego dokumentu – w instalacji **nie ma mechanizmu licencji** (klucze, tokeny, `licensing.py`, etapy L1–L4 poniżej
  odpadają). Limity i płatności chmury egzekwuje sama chmura po swojej stronie.
- **Licencja kodu: GNU AGPL-3.0-only** (plik `LICENSE` w katalogu głównym; `license` w `backend/pyproject.toml`
  i `frontend/package.json`, tekst licencji w obrazie `/app/LICENSE`). Każdy może używać, zmieniać i rozpowszechniać kod;
  kto udostępnia zmienioną wersję innym – także jako usługę przez sieć – musi udostępnić jej kod. Dlatego panel ma
  link „AGPL-3.0 · Kod źródłowy” (`components/SourceLink.tsx`, menu i strona logowania) – **fork z własnym repozytorium
  zmienia `SOURCE_URL`**.
- **„-only”, nie „-or-later”:** o przejściu na przyszłą wersję AGPL decyduje autor, nie FSF.
- **Podwójne licencjonowanie zostaje możliwe:** autor jest jedynym właścicielem praw do kodu, więc może dodatkowo
  udzielić licencji komercyjnej (np. firmie, która nie chce udostępniać zmian) i zamknąć kod usługi chmury
  (osobny program, nie część repozytorium). Żeby tak zostało, wkład z zewnątrz jest przyjmowany tylko na zasadach
  z `CONTRIBUTING.md` (autor wkładu zgadza się na licencjonowanie go także na innych warunkach).
- **Zależności:** sprawdzone 13.11.2026 – backend MIT/BSD/Apache-2.0 (fpdf2 LGPL-3.0, certifi MPL-2.0), panel MIT/Apache-2.0,
  czcionki Geist OFL-1.1, Android Apache-2.0 – wszystkie zgodne z AGPL. TimescaleDB: kompresja i ciągłe agregaty są
  na licencji Timescale (TSL), która pozwala używać ich we własnym produkcie (u siebie i w chmurze), zabrania tylko
  sprzedaży samej bazy TimescaleDB jako usługi. Nowa zależność = sprawdzić licencję.
- To nie jest porada prawna; przed sprzedażą licencji komercyjnej albo startem płatnej chmury warto, żeby umowę
  współtwórcy (`CONTRIBUTING.md`) i regulamin chmury przejrzał prawnik.

Reszta dokumentu to pierwotna propozycja mechanizmu licencji – zostaje dla historii i na wypadek, gdyby kiedyś
jakaś funkcja instalacji miała być płatna.

---

**Status (do 13.11.2026): tylko propozycja.**

## Po co to jest

UplinkView ma być aplikacją do samodzielnej instalacji przez innych (cel z `CLAUDE.md`), a później mieć
chmurę i aplikację mobilną. Jeśli część funkcji ma być płatna albo ograniczona, instalacja potrzebuje
sposobu, żeby dowiedzieć się, co jej wolno, bez grzebania w kodzie. Pomysł: **licencja jako podpisany
dokument wystawiany przez zewnętrzny serwis licencyjny**, który instalacja pobiera po wpisaniu klucza.

## Najważniejsza decyzja: model biznesowy (zanim cokolwiek zbudujemy)

Od niej zależy, czy w ogóle potrzebujemy tego mechanizmu i jak ostrego.

| Model | Co oznacza dla licencji |
|-------|-------------------------|
| **A. Całość darmowa, open source** | Licencji nie ma. Zostaje tylko ewentualny dobrowolny „klucz wspierającego”. |
| **B. Rdzeń darmowy, dodatki płatne** (propozycja) | Darmowo: monitoring sieci domowej do N urządzeń. Płatne: np. powiadomienia (e-mail, push), publiczne dashboardy, chmura i aplikacja mobilna, serwery Linux z agentem, więcej urządzeń. |
| **C. Całość komercyjna** | Licencja potrzebna do działania; brak klucza = tryb tylko do odczytu. |

Do rozstrzygnięcia też: **licencja samego kodu** (np. AGPL, BSL, własnościowa). Ma wpływ na to, jak
mocno wolno i warto zabezpieczać mechanizm. Dla kodu, który użytkownik hostuje sam i może czytać,
zabezpieczenia da się obejść, więc celem jest **uczciwość i wygoda, nie DRM**.

## Proponowane działanie

1. Użytkownik kupuje (albo dostaje) **klucz licencji** w serwisie.
2. W panelu: **Ustawienia → Licencja → wpisz klucz → Aktywuj**.
3. Instalacja wysyła do serwisu: klucz, losowy **identyfikator instalacji** (UUID tworzony przy pierwszym
   uruchomieniu, bez związku ze sprzętem) i wersję UplinkView. **Nic o sieci użytkownika** (adresy, nazwy,
   metryki, klienci).
4. Serwis odsyła **podpisany token** (Ed25519): plan, dozwolone funkcje, limity, data ważności, id instalacji.
5. Instalacja **weryfikuje podpis offline** kluczem publicznym wbudowanym w aplikację i zapisuje token w bazie.
6. Co ok. 24 h kolektor **odświeża** token. Brak internetu nie wyłącza niczego od razu (patrz „Gdy serwis jest
   niedostępny”).

### Przykładowa treść tokenu

```json
{
  "kid": "2026-1",
  "install_id": "5f0c…",
  "plan": "pro",
  "features": ["notifications", "public_dashboards", "cloud"],
  "limits": { "devices": 50, "controllers": 3 },
  "issued_at": "2026-10-25T10:00:00Z",
  "expires_at": "2027-10-25T00:00:00Z",
  "refresh_after": "2026-10-26T10:00:00Z"
}
```

`kid` pozwala wymienić klucz podpisujący bez łamania starszych instalacji (aplikacja zna kilka kluczy publicznych).

## Stany licencji w aplikacji

| Stan | Kiedy | Co się dzieje |
|------|-------|----------------|
| `free` | brak klucza | funkcje darmowe, limity planu darmowego |
| `valid` | ważny token | funkcje i limity z tokenu |
| `grace` | nie udało się odświeżyć albo token wygasł niedawno | wszystko działa jak w `valid`, w panelu dyskretne ostrzeżenie; okres karencji np. 30 dni |
| `expired` | po karencji | **powrót do `free`** |

**Zasada nadrzędna: licencja nigdy nie wyłącza zbierania danych i nie kasuje historii.** Degraduje tylko
nowe, dodatkowe funkcje (np. nie da się dodać urządzenia ponad limit, powiadomienia przestają wychodzić).
Użytkownik, który przestał płacić, dalej widzi swoją sieć i swoje dane.

## Gdy serwis jest niedostępny

- Weryfikacja podpisu jest **lokalna**, więc samo wyłączenie serwisu nic nie psuje.
- Odświeżanie nieudane → stan `grace`, ponawianie z odstępami (1 h, 6 h, 24 h).
- Instalacje bez dostępu do internetu: **plik licencji offline** (ten sam podpisany token, wgrywany w panelu
  albo kładziony w katalogu instalacji), ważny rocznie, bez odświeżania.
- Cofnięcie zegara systemowego: aplikacja zapamiętuje największy widziany czas i nie przedłuża tym ważności.

## Gdzie to stoi w kodzie (gdy kiedyś zdecydujemy się wdrażać)

- `backend/netpulse/licensing.py`: weryfikacja podpisu, stan licencji, funkcje `has_feature("notifications")`
  i `limit("devices")`; **jedno miejsce**, z którego korzysta reszta (kolektor, API, panel).
- Nowe tabele `license` (token, klucz, ostatnie odświeżenie, błąd) i `installation` (id instalacji). Nowe tabele
  powstają same przy `uplinkview update`, więc **nie wymagają migracji Alembic**.
- API: `GET /api/license` (stan, plan, limity, data), `POST /api/license/activate`, `POST /api/license/deactivate`.
  Tylko administrator.
- Panel: Ustawienia → Licencja oraz małe oznaczenia przy funkcjach płatnych. Panel pyta API o `features`, nie ma
  własnej logiki licencyjnej (zgodnie z zasadą „panel to klient API”).
- Odświeżanie w istniejącej pętli kolektora (podobnie jak automatyczne sprawdzanie aktualizacji).

## Serwis licencyjny: zbudować czy kupić

| Opcja | Plusy | Minusy |
|-------|-------|--------|
| **Gotowy serwis** (np. Keygen, Lemon Squeezy, Paddle) | płatności, VAT, faktury, panel klienta, API licencji od razu; mało pracy i utrzymania | zależność od dostawcy, opłaty, mniej kontroli nad formatem tokenu |
| **Własny** (np. mała usługa + Stripe) | pełna kontrola, własny format tokenu | trzeba utrzymać serwer, bezpieczeństwo klucza podpisującego, obsługę VAT i zwrotów |

**Rekomendacja:** zacząć od gotowego serwisu z API licencji, a w aplikacji zostawić cienką warstwę
(`licensing.py`), żeby dostawcę dało się zmienić. Klucz prywatny podpisujący nigdy nie trafia do repozytorium
ani do obrazu aplikacji.

## Prywatność i bezpieczeństwo

- Wysyłamy tylko: klucz licencji, id instalacji, wersję aplikacji. Opisane jawnie w panelu i dokumentacji.
- Połączenie tylko po HTTPS; adres serwisu jest ustawieniem (`NETPULSE_LICENSE_URL`), a **wyłączenie** go daje
  tryb w pełni offline.
- Klucz licencji w bazie jak inne sekrety (nie wraca w API; w odpowiedziach tylko ostatnie 4 znaki).
- Limit aktywacji na klucz (np. 3 instalacje) i możliwość dezaktywacji z panelu, żeby przenieść licencję na
  nowy serwer.
- Ograniczenie żądań do serwisu i brak ponawiania w pętli.

## Proponowane etapy (do decyzji, nie do wykonania teraz)

1. **L1 – szkielet bez serwisu:** `licensing.py`, tabele, weryfikacja podpisu na podstawie testowego klucza,
   Ustawienia → Licencja, `has_feature`/`limit` bez żadnych ograniczeń w funkcjach. Testowalne w całości w CI.
2. **L2 – serwis:** wybór dostawcy, aktywacja/odświeżanie/dezaktywacja, plik licencji offline.
3. **L3 – płatności i oferta:** plany, ceny, strona zakupu, maile z kluczem.
4. **L4 – egzekwowanie:** pierwsze funkcje i limity naprawdę sprawdzane (po decyzji, co jest płatne).

L1 można zrobić bez rozstrzygania modelu biznesowego i nic nie psuje; L4 dopiero po decyzji.

## Pytania otwarte

1. Który model biznesowy (A, B, C)? Czy w ogóle chcemy płatne funkcje?
2. Co dokładnie ma być płatne, a co zawsze darmowe (propozycja: sam monitoring i alerty w panelu darmowe,
   płatne kanały powiadomień, chmura, aplikacja mobilna, agent serwerów)?
3. Jaka licencja kodu?
4. Dostawca serwisu licencyjnego i waluta/VAT (sprzedaż do UE).
5. Długość karencji i okres ważności (miesięczna, roczna, dożywotnia)?
6. Czy dopuszczamy klucze testowe/próbne (np. 30 dni pełnych funkcji)?
7. Czy przy tej samej okazji robimy telemetrię użycia (domyślnie wyłączoną), czy zostajemy przy minimum?
