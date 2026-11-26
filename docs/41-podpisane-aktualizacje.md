# Podpisane aktualizacje (od 0.69.0)

Usługa aktualizacji ma dostęp do Dockera, czyli pełną kontrolę nad serwerem, i instaluje kod z GitHuba. Bez podpisów
przejęcie konta na GitHubie oznaczałoby przejęcie każdej instalacji UplinkView. Od 0.69.0 aktualizacja musi być
**podpisana kluczem, którego na GitHubie nie ma**.

## Jak to działa

1. Każdy commit wypychany na `main` jest podpisany kluczem SSH (`git commit -S`, format podpisu `ssh`).
2. W repozytorium jest plik `deploy/update-signers` z **kluczem publicznym** (format `allowed_signers` programu `ssh-keygen`).
3. Przed zmianą kodu updater (`git_ops.verify_commit`) i polecenie `uplinkview update` (`verify_update` w `scripts/netpulse`)
   sprawdzają podpis ostatniego commita ze źródła: `git verify-commit` z listą kluczy **z zainstalowanej wersji**.
4. Podpis nieprawidłowy albo go brak → aktualizacja nie rusza, nic się nie zmienia. W panelu (Ustawienia → Aktualizacja)
   zamiast przycisku instalacji jest komunikat „Aktualizacja w źródle nie ma prawidłowego podpisu UplinkView”.

Podpis ostatniego commita obejmuje całą historię przed nim (każdy commit zawiera skrót poprzedniego), więc jeden wystarcza.
Instalowany jest dokładnie ten commit, którego podpis sprawdzono – nie nazwa gałęzi, która mogłaby się w międzyczasie przesunąć.

## Przed czym chroni, a przed czym nie

| Sytuacja | Skutek |
|----------|--------|
| Ktoś przejmuje konto GitHub i wypycha złośliwy kod | odrzucone – nie ma klucza, nie podpisze |
| Złośliwy commit sam dopisuje swój klucz do `deploy/update-signers` | odrzucone – liczy się lista z wersji już zainstalowanej |
| Podpis innym, nieznanym kluczem | odrzucone |
| Commit zrobiony w przeglądarce na GitHubie (edycja pliku, „Merge” w PR) | odrzucone – GitHub podpisuje własnym kluczem, nie naszym |
| Ktoś przejmuje komputer z kluczem prywatnym | **nie chroni** – może podpisać cokolwiek |
| Pierwsza instalacja (`install.sh` z GitHuba) | **nie chroni** – nie ma jeszcze zaufanej listy kluczy; chroni kolejne aktualizacje |
| Pierwsza aktualizacja ze starszej wersji do 0.69.0 | bez sprawdzania – stary updater nie zna podpisów |
| Cofnięcie `main` do starszej, podpisanej wersji | updater nie instaluje wersji starszej niż zainstalowana (to nie jest „aktualizacja do przodu”) |

## Klucz

- Klucz prywatny: `~/.ssh/netpulse_signing` na komputerze, z którego wypychane są zmiany (bez hasła – podpisuje nim
  Claude Code przy każdym commicie). **Nie trafia do repozytorium ani na GitHub.** Odcisk: `SHA256:ot30ehVY0LfA/NKmpL/dxDhrcth6DMwR0/licVN5JGw`.
- **Zrób kopię klucza prywatnego w bezpiecznym miejscu** (menedżer haseł, nośnik offline). Po jego utracie nie da się
  wydać aktualizacji, którą przyjmą istniejące instalacje – każda wymagałaby ręcznego kroku (patrz „Gdy klucz przepadnie”).
- Podpisywanie jest ustawione tylko w tym repozytorium (`git config --local`): `gpg.format ssh`, `user.signingkey`,
  `commit.gpgsign true`. Na nowym komputerze: skopiować klucz do `~/.ssh/` i ustawić to samo.
- Żeby GitHub pokazywał przy commitach „Verified”: Settings → SSH and GPG keys → New SSH key → typ **Signing key**,
  wkleić `~/.ssh/netpulse_signing.pub`. Nie jest to potrzebne do działania aktualizacji.

### Wymiana klucza

Nowy klucz wprowadza aktualizacja podpisana **starym**: dopisać nowy klucz publiczny do `deploy/update-signers` (stary
zostawić), wypchnąć podpisane starym. Gdy instalacje się zaktualizują, kolejne commity można podpisywać nowym, a stary
usunąć z pliku w późniejszej wersji. Instalacja, która przeskoczy wersję przejściową, odrzuci aktualizację – dlatego stary
klucz warto trzymać w pliku długo.

### Gdy klucz przepadnie albo wycieknie

Na każdym serwerze jednorazowo, jako root, podmienić zaufaną listę na nową i zaktualizować:

```bash
cd /opt/uplinkview && sudo git fetch origin main && sudo git show origin/main:deploy/update-signers | sudo tee deploy/update-signers
sudo uplinkview update
```

Ten krok wymaga dostępu do serwera – i o to chodzi: sam GitHub nie wystarczy, żeby zmienić zaufany klucz.

Na starszej instalacji katalog to `/opt/netpulse`.

**Historia:** 26.11.2026 (0.87.1) pierwszy klucz `netpulse-release` przepadł razem z systemem (brak kopii `~/.ssh`)
i został zastąpiony nowym. Instalacje 0.87.0 i starsze odrzucają 0.87.1 i nowsze, dopóki nie wykona się powyższego
kroku – to samo widać w CI przy commicie 0.87.1 (test „Aktualizacja z panelu” cofa się o jeden commit). **Klucz trzymać
też w kopii zapasowej poza komputerem.**

## Własne źródło aktualizacji

Kto ustawia `NETPULSE_UPDATE_REPO` na własny fork, nie ma podpisów UplinkView. Do wyboru:

- `NETPULSE_UPDATE_VERIFY=off` w `deploy/.env` (wyłącza sprawdzanie; zmienić może tylko ktoś z dostępem do serwera), albo
- własny klucz w `deploy/update-signers` forka i podpisywanie własnych commitów.

## Zasady dla pracy nad UplinkView

- **Każdy commit na `main` musi być podpisany** – niepodpisany zablokuje aktualizację wszystkim instalacjom do czasu
  wypchnięcia kolejnego, podpisanego. Sprawdzenie przed wypchnięciem: `git log --format='%h %G? %s' -3` (`G` = dobry podpis).
- Nie edytować plików ani nie scalać PR w przeglądarce na GitHubie (commit dostaje podpis GitHuba, nie nasz).
- Test end-to-end w CI instaluje wersję o jeden commit starszą i aktualizuje ją z panelu do bieżącej – od 0.69.0 przechodzi
  więc tylko wtedy, gdy bieżący commit ma prawidłowy podpis.

## Kod i testy

`updater/netpulse_updater/git_ops.py` (`SIGNERS_FILE`, `signature_required`, `verify_commit`), `job.py` (faza `fetch`),
`scripts/netpulse` (`verify_update`), obraz updatera z `openssh-keygen`. Testy na tymczasowych kluczach:
`backend/tests/test_updater.py` (podpisana wersja, brak podpisu, obcy klucz, podmiana listy, wymiana klucza, wyłączenie)
i `test_scripts.py` (`verify_update`).
