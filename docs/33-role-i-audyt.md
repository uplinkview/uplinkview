# Role kont i dziennik zdarzeń (0.61.0)

## Role

| Rola | Co może |
|---|---|
| **Administrator** | wszystko: urządzenia, reguły alertów, integracje, konta, kopie zapasowe, aktualizacje, pulpity publiczne |
| **Operator** | ogląda cały panel, potwierdza alerty |
| **Podgląd** | tylko ogląda; może zmienić własne hasło, interwał odświeżania i swoje pulpity |

Konta zakłada administrator w **Ustawienia → Konta** (login, hasło, rola). Pierwsze konto (kreator) jest administratorem.
Ostatniego administratora nie da się usunąć ani zdegradować, własnego konta nie da się usunąć. Zmiana roli albo hasła
innego konta wylogowuje je ze wszystkich sesji. Z wiersza poleceń: `uplinkview user add <login> --role operator`,
`uplinkview user list` pokazuje role.

Aktualizacja z wersji sprzed 0.61.0: dotychczasowe konta administratorów zostają administratorami, pozostałe dostają
rolę „Podgląd” (migracja `0014`).

### Jak to działa w API

- `api/security.py`: **domyślnie zakaz** – każda zmiana (POST/PUT/PATCH/DELETE) wymaga administratora, chyba że trasa
  jest w `ROLE_RULES` z niższą rolą. Szablon trasy pochodzi z `request.scope["route"].path`.
  **Nowa trasa dla operatora albo podglądu = wpis w `ROLE_RULES`** (`test_roles.py` sprawdza, że każdy wpis wskazuje
  istniejącą trasę).
- Odczyty (GET) są dla każdego zalogowanego, poza: konta i dziennik (`/api/users`, `/api/audit`), kopie zapasowe,
  zarządzanie agentami.
- `require_admin` / `AdminUser`, `require_operator` / `OperatorUser` – zależności FastAPI dla tras.
- Kolumna `users.is_admin` zostaje (zgodność z bazą sprzed migracji) i jest ustawiana razem z `role` przez `User.set_role`.

### Panel

- `lib/roles.ts`: `roleOf(user)`, `hasRole`, `useCan("operator")`.
- Podstrony Ustawień mają pole `role` w `modules.tsx` (bez niego – tylko administrator). Podgląd widzi: Konto,
  Dashboardy, Odświeżanie, System, Moduły i Aktualizacja (dwie ostatnie tylko do odczytu); operator widzi to samo.
- Przycisk „Potwierdź” przy alertach widzi operator i administrator.

## Dziennik zdarzeń

**Ustawienia → Dziennik zdarzeń** (tylko administrator): czas, konto, zdarzenie, adres IP, wynik. Filtry: wszystko /
zmiany / logowania / odrzucone (brak uprawnień i nieudane logowania), wyszukiwanie po koncie, adresie IP i ścieżce.

Zapisywane:
- logowanie, nieudane logowanie (także na nieznany login), wylogowanie, zmiana własnego hasła, założenie pierwszego konta
  (`api/auth_routes.py`),
- każda zmiana przez API zalogowanego konta – także odrzucona (403) albo błędna (422): metoda, szablon trasy,
  konkretna ścieżka, kod odpowiedzi (middleware `audit_changes` w `api/__init__.py`).

**Treść żądań nie jest zapisywana** – hasła, klucze API i community SNMP nie trafiają do dziennika. Pomijane są raporty
agentów i pulpit publiczny. Wpisy starsze niż rok są usuwane automatycznie (`audit.py`, `RETENTION`).

Tabela `audit_log` (migracja `0014`), kod: `netpulse/audit.py`, `api/users.py`, panel: `pages/settings/UsersPage.tsx`,
`AuditPage.tsx`, `lib/audit.ts`.

## Jak sprawdzić

1. Ustawienia → Konta → „Dodaj konto”, rola „Podgląd”.
2. Zaloguj się na to konto w innej przeglądarce (albo oknie prywatnym): w Ustawieniach nie ma Urządzeń ani Kont,
   przy alertach nie ma „Potwierdź”.
3. Na koncie administratora: Ustawienia → Dziennik zdarzeń – widać założenie konta i logowanie.
