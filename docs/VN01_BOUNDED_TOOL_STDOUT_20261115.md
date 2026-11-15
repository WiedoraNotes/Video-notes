# VN-01/VN-06 — ograniczanie stdout FFmpeg/FFprobe w trakcie procesu (15.11.2026)

## Dlaczego zmiana jest potrzebna

Dotychczasowe `videonotes.media._run()` uruchamiało `subprocess.run(..., stdout=tempfile.TemporaryFile())` i sprawdzało limit **2 MiB** dopiero po **zakończeniu procesu**. Błędne narzędzie lub wadliwy plik mogły generować na dysku bardzo duży plik tymczasowy, aż do zakończenia lub timeoutu, mimo że odpowiedź i tak była potem odrzucana.

## Nowy mechanizm

- Uruchomienie narzędzia bez powłoki, z wyłączonym stdin i stderr kierowanym do DEVNULL. Dziecko ma osobną grupę/sesję procesów.
- Odrębny czytnik pobiera stdout porcjami do 64 KiB, utrzymując w pamięci nie więcej niż 2 MiB. Gdy następna porcja przekracza limit, **przerywa odczyt w trakcie działania**, uruchamia sprzątanie grupy procesu i zwraca ogólny `VideoNotesError` bez słów, ścieżek ani stderr.
- Limit czasu jest pilnowany również podczas odczytu i przed zakończeniem pracy, zamiast czekać na sam koniec narzędzia. Proces błędny lub zawieszony nie może opóźniać obliczeń ponad ustawiony timeout z wyjątkiem krótkiego czasu porządkowania.
- Normalne, krótkie odpowiedzi FFprobe zachowują ten sam kontrakt `CompletedProcess`: `returncode=0`, `stdout` po poprawnym dekodowaniu ścisłym UTF-8, `stderr=""`. FFMpeg z zapisem WAV na dysk nie zmienia lokalizacji pliku ani algorytmu ekstrakcji.

## Nowe testy

```sh
python -m unittest tests.test_media tests.test_audio_formats tests.test_pipeline -v
python -m unittest discover -s tests -v
```

Rzeczywisty lokalny proces Python generuje ponad 2 MiB prywatnego tekstu, a potem próbuje spać 10 sekund. Nowa implementacja musi odmówić bez czekania na ten sen. Inne testy sprawdzają dokładnie 2 MiB, timeout działającego dziecka, kod niezerowy i nieujawnianie stderr. Dotychczasowe scenariusze ze FFmpeg, dwoma ścieżkami OBS-podobnego MKV, 121-minutowym OGG/Opus i checkpointami nadal obowiązują.

**Granica odbioru:** to nie jest test prawdziwego sprzętu Windows/AV, legalnego publicznego instalatora, rzeczywistego pełnego nagrania OBS ani jakości transkrypcji. Źródło modelu ASR i warunki licencji nie zostały zmienione; żadna faza nie otrzymuje automatycznie PASS. Sposób ucinania grup procesów na Windows ma zależność od systemowego `taskkill /T`; nie zakładać udowodnionego ubicia dowolnego wrogiego procesu potomnego.
