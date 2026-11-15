# VN-07 — gotowy pakiet do fizycznego odbioru Windows (15.11.2026)

**Status:** procedura i syntetyczne dane wejściowe, **NIE dowód testów fizycznych**. VN-07-02/03/05 nadal otwarte. Pracuj wyłącznie na `Video-notes/develop` i oddzielnej becie KWN. Nie uruchamiaj testów funkcjonalnych KWN z zakresu masterplanu WPL. Nie przesyłaj prywatnych transkrypcji i nagrań do CI/GitHub.

## 1. Przygotowanie offline

Na fizycznym Windows 10/11 z aktualnym Pythonem, we własnej kopii repozytorium KWN:

```powershell
git switch develop
git pull --ff-only
git rev-parse HEAD
python -m unittest tests.test_vn07_acceptance_fixture tests.test_acceptance_evidence -v
python scripts/vn07_acceptance_fixture.py --output C:\KWN-VN07-SYNTHETIC-TEST
```

**Wymagany jest nowy katalog**, którego jeszcze nie ma. Generator nie nadpisuje istniejących plików ani katalogów, nie dotyka projektu, sieci, modelu ani mikrofonu. Daje siedem zasobów (w tym czterosekundowy WAV bez mowy) i `manifest.json` z SHA-256 każdego pliku. Dla wybranych plików porównaj SHA-256 z manifestem:

```powershell
Get-FileHash C:\KWN-VN07-SYNTHETIC-TEST\vn07-small.json -Algorithm SHA256
Get-FileHash C:\KWN-VN07-SYNTHETIC-TEST\vn07-large-50000.json -Algorithm SHA256
```

To sztuczne zdania, nie model ASR, więc nie wolno używać ich do oceny dokładności transkrypcji.

## 2. WEB-01: trzy przeglądarki na rzeczywistym Windows

Odłącz komputer od internetu i otwórz lokalny `web/index.html` kolejno w Chrome, Edge i Firefox, bez serwera, logowania i wtyczek. Dla każdej przeglądarki wykonaj całą sekwencję:

1. Wczytaj `vn07-small.json`; interfejs pokazuje **3 z 3 wypowiedzi**. Wybierz drugą wypowiedź, zmień tekst na `Test znaków: Zażółć & <tag>`, a następnie sprawdź, że przycisk eksportu blokuje **niezapisaną** edycję. Kliknij „Zachowaj poprawkę”, potem „Cofnij zmianę” i „Ponów zmianę”.
2. Pobierz faktyczne pliki TXT, SRT, VTT, JSON i `web-corrections.json`. Sprawdź na dysku, czy pobrane pliki są niepuste, zawierają zapisaną poprawkę i nie zmieniają oryginalnego `vn07-small.json`. W VTT `<tag>` i `&` mają być zakodowane jako tekst, a nie składnia znaczników.
3. Po otwarciu ponownie **tego samego źródła** wczytaj `vn07-corrections.json`; poprawka segmentu 1 ma zostać przywrócona. Sprawdź odmowę `vn07-foreign-corrections.json` bez zmiany źródła.
4. Zachowaj zapisaną poprawkę i spróbuj wczytać `vn07-duplicate-key.json` oraz `vn07-deeply-nested.json`. Jeżeli pojawi się pytanie o porzucenie dotychczasowych zmian, zaakceptuj je **wyłącznie dla syntetycznej sesji testowej**; po błędzie parsera stare dane i zapisane poprawki nadal muszą być obecne.
5. Wybierz WAV `vn07-silent-four-seconds.wav`; odtwarzacz ma pozostać w pauzie do ręcznego uruchomienia. Wybierz trzecią wypowiedź i przejdź do jej czasu ok. **3,0 s**. Zatrzymaj nagranie przy ok. **1,5 s** i wybierz wypowiedź z czasu nagrania. Zmień źródło transkrypcji i sprawdź, czy poprzedni WAV zostaje odłączony.

Odnotuj także, czy przeglądarka po odłączeniu sieci nie próbuje pobierać zasobów zdalnych. Brak widocznych żądań nie jest sam w sobie dowodem pełnego audytu ruchu.

## 3. WEB-02: 50 000 segmentów i dostępność

Wczytaj `vn07-large-50000.json`. Sprawdź `50000 z 50000`, limit **75 wierszy na stronę**, wyszukanie `znacznik-49999` i edycję znalezionego ostatniego segmentu. Zanotuj czas do interaktywności i obserwację zużycia RAM na tym konkretnym urządzeniu; nie przenoś czasów z GitHub-hosted runners jako wyników fizycznych.

Powtórz bez myszy: Tab, Shift+Tab, Enter, przejście między segmentami i przyciskami, zapis, cofnięcie, eksport. Z włączonym **NVDA** oceń odczyt nazw przycisków, etykiet edytora, ogłoszeń o błędach, aktywnego segmentu i informacji o liczbie wyników. Wykonaj też próbę przy powiększeniu 200% i na węższym oknie. Każde kryterium, którego człowiek nie sprawdził, pozostaje `NOT_RUN`.

## 4. HOST-01: osobny odbiór izolowanej bety Wiedora

Dopiero po zielonym CI hosta, zatwierdzonej synchronizacji dokładnego SHA kodu KWN i gotowym wdrożeniu Netlify testuj pod `https://develop--constant-app.netlify.app/apps/notatki-web/video-notes/` połączenie KWN z hostem: izolacja, powrót, CSP, cache, brak regresji innych modułów. Sprawdź `source-version.json`, identyfikator commita w aktywnym `build-info.json` i oddzielnie `main`. **Starsza beta i niescalone draft PR #212/#215 nie pozwalają uznać HOST-01 za PASS.**

## 5. Zachowanie dowodów bez publikowania nagrań

Lokalnie utwórz nowy prywatny rejestr:

```powershell
python scripts/vn_acceptance_evidence.py --init C:\KWN-VN07-EVIDENCE.json
python scripts/vn_acceptance_evidence.py --check C:\KWN-VN07-EVIDENCE.json
```

Po **realnym** teście wpisz datę, rzeczywisty SHA `develop`, identyfikator WEB-01/WEB-02/HOST-01, wyniki i wyłącznie link do zanonimizowanych metadanych. Nie zapisuj w tym pliku nazwisk, ścieżek nagrań, transkrypcji ani loginów. Walidator nie sprawdza autentyczności człowieka ani urządzenia; `SELF_REPORTED_PASS` wymaga niezależnej weryfikacji i **nie zamyka automatycznie VN-07 ani WEB-01/02/HOST-01**.

Dokładne definicje formalnych bramek: [VN_HARDWARE_ACCEPTANCE_20261107.md](VN_HARDWARE_ACCEPTANCE_20261107.md) i [VN_MANUAL_EVIDENCE.md](VN_MANUAL_EVIDENCE.md).
