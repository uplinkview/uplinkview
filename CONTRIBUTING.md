# Współtworzenie UplinkView

Dziękujemy za chęć pomocy! Zgłoszenia błędów, nowe urządzenia (raport z panelu: Ustawienia → Urządzenia → Raport
urządzenia) i pomysły przyjmujemy przez [GitHub Issues](https://github.com/uplinkview/uplinkview/issues).

## Licencja wkładu

UplinkView jest na licencji [GNU AGPL-3.0-only](LICENSE). Autor projektu chce zachować możliwość udzielania także
licencji komercyjnej (podwójne licencjonowanie) i rozwijania płatnej chmury. Dlatego zmiany w kodzie (pull requesty)
przyjmujemy na poniższych zasadach. Wysyłając pull request, potwierdzasz, że:

1. Wkład jest Twoim własnym dziełem albo masz prawo go przekazać (np. zgodę pracodawcy).
2. Udzielasz autorowi projektu UplinkView niewyłącznej, bezterminowej, nieodpłatnej i nieodwołalnej licencji
   na całym świecie do używania, zmieniania, rozpowszechniania i udzielania dalszych licencji na swój wkład –
   na licencji AGPL-3.0 **oraz na innych warunkach, także komercyjnych**.
3. Prawa autorskie do wkładu zostają przy Tobie, a wkład w repozytorium jest zawsze dostępny na licencji AGPL-3.0.

W opisie pull requesta dopisz zdanie: „Zgadzam się na warunki z CONTRIBUTING.md”.

## Zasady techniczne

- Każdy commit na `main` jest podpisany kluczem z `deploy/update-signers` – instalacje odrzucają niepodpisane
  aktualizacje. Twój pull request scala i podpisuje opiekun projektu.
- CI (`.github/workflows/ci.yml`) musi przejść: ruff, pytest, testy panelu, instalacja end-to-end.
- Nowy tekst w panelu: wpis w `frontend/src/i18n/pl.ts` i `en.ts`; nowy komunikat backendu: wpis w
  `backend/netpulse/messages.py`.
- Nowa zależność musi mieć licencję zgodną z AGPL-3.0 (MIT, BSD, Apache-2.0, LGPL, MPL-2.0 i podobne).
- Zrzuty z urządzeń tylko zanonimizowane (`backend/tools/walk2snmprec.py`) – bez adresów MAC, SSID i tras sieci domowej.
