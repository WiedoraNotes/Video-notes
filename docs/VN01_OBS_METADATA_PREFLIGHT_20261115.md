# VN-01 — FFprobe i bezpieczna identyfikacja ścieżek OBS (15.11.2026)

**Cel:** błędny tekst w kontenerze wideo nie może prowadzić do niejawnej podmiany znaków nazwy ścieżki audio ani przerwania zapisu projektu wyjątkami `UnicodeEncodeError` / `RecursionError`. Poprawka dotyczy wyłącznie lokalnego przetwarzania i testów syntetycznych.

## Wprowadzona walidacja

1. `videonotes.media._run` odczytuje tekst narzędzi przez **ścisły UTF-8**. Wadliwe bajty (np. `FF FE`) dają kontrolowany błąd bez cytowania nazw plików, mowy, stderr i wartości metadanych. Nie są po cichu zastępowane znakiem `U+FFFD`.
2. `probe()` odrzuca etykiety audio zawierające NUL lub samotny surrogate `U+D800–U+DFFF`. Teksty `codec_name`, `tags.language` i `tags.title` mają wspólny limit 256 jednostek UTF-16, jak w kontraktach desktop/WWW; poprawne polskie znaki i emoji są akceptowane.
3. Silnie zagnieżdżony (w tym nieznany) JSON z FFprobe oraz wynik powodujący `RecursionError` lub `OverflowError` jest zgłaszany jako `VideoNotesError` przed wyborem ścieżki audio i przed tworzeniem katalogu nowego projektu.

## Weryfikacja

```sh
python -m unittest tests.test_media tests.test_audio_formats tests.test_pipeline -v
python -m unittest discover -s tests -v
```

Nowe regresje sztucznie podstawiają odpowiedzi FFprobe z niedozwolonymi znakami, 15 000 poziomów JSON i zbyt długimi metadanymi. Oddzielny test uruchamia realny proces Python, aby wykryć zły UTF-8 i sprawdzić poprawny tekst PL. Sprawdza się także, że po nieudanym preflight katalog projektu nie istnieje.

Istniejące testy z rzeczywistym FFmpeg/FFprobe oraz syntetycznymi wielościeżkowymi MKV obejmują prawidłowy wybór i odczyt audio. **Brak odbioru prawdziwego długiego OBS MP4/MKV na komputerze właściciela, jakości ASR, uszkodzonego fizycznego nośnika i Windows offline**, więc VN-01-02, VN-01-05 i cały VN-01 nie przechodzą do `DONE`.

To nie zmienia sposobu wyboru ścieżek `--stream`, surowego transkryptu, danych użytkownika, bazy, instalatora ani hosta Wiedora. Nie dodano usług płatnych i nic nie jest przesyłane do chmury.
