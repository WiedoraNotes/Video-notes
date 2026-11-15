# VN-01 — odporność importu wynikowego JSON silnika ASR (15.11.2026)

**Zakres:** lokalny, opcjonalny `whisper.cpp` w `videonotes/asr.py`. Jest to poprawka programistyczna bezpieczeństwa zapisu checkpointów, **nie odbiór rzeczywistego silnika/modelu, nagrania OBS ani komputera Windows**.

## Zachowanie po zmianie

1. Silnik kończy pracę i przekazuje ścieżkę do tymczasowego `result.json`. Przed odczytem odrzucany jest symlink, brak pliku i katalog.
2. Wspólny, limitowany odczyt `read_stable_local_json` ma domyślny **20 MiB** dla dotychczasowych importów i świadomie wybrany limit **32 MiB** dla ASR. Czyta najwięcej `limit+1` bajtów, dwukrotnie odczytuje ten sam deskryptor, porównuje SHA-256, wielkość, tożsamość inode i znaczniki zmian oraz sprawdza końcową ścieżkę. Nie ufa samemu `stat().st_size`.
3. Parser JSON odrzuca powtarzane klucze również w zagnieżdżonych obiektach, `NaN`, `Infinity`, `-Infinity`, złe bajty UTF-8, nadmiernie zagnieżdżone dane i zbyt duże liczby, zwracając zwykły `VideoNotesError` bez wyświetlania surowych danych.
4. Dopiero po całym poprawnym parsowaniu sprawdzane są czas segmentu, limit 24 h, tekst zgodny z Unicode (bez samotnych surrogate), maksymalnie 10 000 jednostek UTF-16 oraz poprawność offsetów. Poprawne segmenty zostają uporządkowane chronologicznie; powtórzenia tekstu w różnych czasach są zachowane.
5. Jeśli którekolwiek z tych ograniczeń zawiedzie, `parse_whisper_output` nie zwraca listy segmentów; istniejący projekt i jego checkpoint nie są modyfikowane przez sam importer. Wznowienie pracy pozostaje świadomą operacją właściciela.

## Weryfikacja

```sh
python -m unittest tests.test_asr tests.test_json_decoder_limits tests.test_mobile_import -v
python -m unittest discover -s tests -v
```

Regresje używają sztucznego pliku WAV/modelu i imitowanego wyniku narzędzia ASR. Sprawdzają podmianę odczytu, nielegalne dane JSON, limit bajtów, nazwy lokalne nieobecne w komunikatach błędu, 5 000/5 001 emoji, niepoprawne offsety i brak zmian pliku wejściowego. Prawdziwy model Whisper, WER/CER, wydajność na 2 h, obsługa uszkodzonego multitrack OBS, nagrania właściciela, fizyczny Windows i licencje **NIE były testowane**. VN-01-01/05 i cały VN-01 pozostają otwarte.

**Granica bezpieczeństwa:** dwie kontrolowane próbki bajtów i sprawdzenie atrybutów pliku znacząco zmniejszają ryzyko przypadkowej współbieżnej podmiany, lecz nie są blokadą dla złośliwego procesu ze swobodnym dostępem do tej samej pamięci masowej. Nie dodano sieci, modeli, mikrofonu, Netlify ani usług płatnych.
