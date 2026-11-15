# VN-00 — odczyt źródeł pomiaru WER/CER z kontrolą integralności (15.11.2026)

**Status:** wdrożony mechanizm stabilności wejść; **brak realnego benchmarku modelu Whisper lub faster-whisper na naturalnej mowie właściciela**. Nie oznacza VN-00-01 ani VN-00-02 jako DONE.

## Co poprawiono

Moduł `videonotes.quality` porównuje tekst źródłowej transkrypcji i wyników modelu. Dawniej pojedynczy odczyt `_read()` sprawdzał limit 300 000 bajtów przed i po odczycie, ale nie wykrywał zmiany pliku **bez zmiany rozmiaru** w trakcie pierwszego czytania. To mogło prowadzić do mieszania dwóch wersji zapisu w jednym wyniku WER/CER.

Odczyt korzysta teraz ze wspólnego `read_stable_local_json(..., max_bytes=300000)` — nazwa funkcji odnosi się do historycznych zastosowań, jednak jej warstwa odczytu operuje na dowolnych bajtach i **nie parsuje JSON**. Dwukrotnie czyta ten sam deskryptor pliku, potwierdza SHA-256 obu przebiegów, wielkość i tożsamość ścieżki, a następnie dopiero dekoduje tekst z dopuszczonym UTF-8 BOM. Odrzuca symlinki, podmianę/rośnięcie pliku i niepoprawne UTF-8.

Istniejące sprawdzenie wszystkich źródeł *po obliczeniu* metryk zostaje zachowane: źródło nie może zmienić się podczas oceny innego kandydata. **Wciąż obowiązuje limit 300 000 bajtów** oraz do 6000 słów — nie podniesiono go do 20/32 MiB i nie dodano automatycznego pobierania modeli.

## Testy regresyjne

```sh
python -m unittest tests.test_quality tests.test_asr_lab -v
python -m unittest discover -s tests -v
```

Testy podmieniają plik kandydata między dwoma odczytami zachowując **identyczny rozmiar**, wywołują wzrost pliku w trakcie czytania, sprawdzają raport bez prywatnego tekstu, prawidłowy i wadliwy UTF-8/BOM, zakaz nadpisania wcześniejszego raportu oraz zgodność dokładnych metryk.

To bezpieczeństwo źródeł tekstowych, a **nie** pomiar procesora, RAM, czasu inferencji, legalności modelu, WER/CER na naturalnej mowie ani odbiór na fizycznym Windows. Do formalnego zakończenia VN-00 pozostają naturalne próbki i ręczna transkrypcja referencyjna, realne modele, pomiary na tym samym PCM, weryfikacja praw i Windows offline. Nie zmieniono hosta Wiedora, staging, `main` ani płatnych usług.
