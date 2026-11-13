# Współtworzenie UplinkView

Dziękujemy za chęć pomocy! Zgłoszenia błędów, nowe urządzenia (raport z panelu: Ustawienia → Urządzenia → Raport
urządzenia) i pomysły przyjmujemy przez [GitHub Issues](https://github.com/uplinkview/uplinkview/issues).

## Zasady techniczne

- Każdy commit na `main` jest podpisany kluczem z `deploy/update-signers` – instalacje odrzucają niepodpisane
  aktualizacje. Twój pull request scala i podpisuje opiekun projektu.
- CI (`.github/workflows/ci.yml`) musi przejść: ruff, pytest, testy panelu, instalacja end-to-end.
- Nowy tekst w panelu: wpis w `frontend/src/i18n/pl.ts` i `en.ts`; nowy komunikat backendu: wpis w
  `backend/netpulse/messages.py`.
- Zrzuty z urządzeń tylko zanonimizowane (`backend/tools/walk2snmprec.py`) – bez adresów MAC, SSID i tras sieci domowej.
