# KWN — lokalny rejestr dowodów odbioru, bez publikowania danych

## Po co?

Automatyczne CI sprawdza funkcje i symulacje, ale nie dowodzi jakości wykładu, mikrofonu, realnego GGUF, instalacji Windows offline ani licencji. Ta procedura pomaga rejestrować **wyniki wykonane przez człowieka** jako `SELF_REPORTED_PASS` / `SELF_REPORTED_FAIL` / `NOT_RUN`; nigdy nie aktualizuje automatycznie `VN_STATUS.json`.

## Użycie na komputerze testowym

```powershell
python scripts/vn_acceptance_evidence.py --init C:\\KWN-prywatne\\wyniki.json
# W pliku lokalnym uzupełnij wyłącznie dopuszczone pola.
python scripts/vn_acceptance_evidence.py --check C:\\KWN-prywatne\\wyniki.json
```

Nie uruchamiaj na publicznym runnerze z prywatnym plikiem. `--init` odmawia nadpisania istniejącego rejestru. `--check` wypisuje tylko wyniki zbiorcze, bez żadnych lokalnych ścieżek, nazw urządzeń, tekstów nagrań lub identyfikatorów recenzenta. Narzędzie nie łączy się z siecią.

## Schemat pojedynczego wyniku

```json
{
  "case_id": "ASR-04",
  "kind": "PHYSICAL_WINDOWS",
  "result": "PASS",
  "checked_at": "2026-11-11",
  "commit_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "attested_by_human": true,
  "sample_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "wer": 0.15,
  "cer": 0.08,
  "elapsed_seconds": 85.5,
  "peak_ram_mb": 1200,
  "evidence_url": "https://github.com/WiedoraNotes/Video-notes/issues/95"
}
```

**To przykład formatu, nie prawdziwy wynik.** Hash commita, pliku i metryki należy zastąpić rzeczywiście zmierzonymi danymi. Link musi prowadzić do **wyłącznie zanonimizowanych metadanych**, nie do nagrania/transkrypcji. Narzędzie nie sprawdza prawdziwości deklaracji, podpisu osoby ani tożsamości; jest tylko walidatorem formatu i kompletności lokalnych metryk.

Dopuszczalne rodzaje: `PHYSICAL_WINDOWS`, `HUMAN_REVIEW`, `LEGAL_REVIEW`, `PORTAL_REVIEW`, `PRODUCT_DECISION`; dobrane do kryterium z [macierzy](VN_HARDWARE_ACCEPTANCE_20261107.md). `CI` nie może zostać uznane za fizyczny PASS. `PKG-02` wymaga osobno Windows i przeglądu prawnego, `NOTE-02` wymaga fizycznego Word oraz recenzji, `WEB-02` wymaga testu systemowego i recenzji dostępności.

Wpis `NOT_RUN` powinien zawierać tylko `case_id`, `kind` i `result`. `FAIL` lub `PASS` wymaga daty, commita, świadomego potwierdzenia oraz linku do anonimowych dowodów. `ASR-01` dodatkowo wymaga WER/CER, a `ASR-03/04` także czasu i RAM; `ASR-05` czasu i RAM.

**Nigdy nie dodawaj do repozytorium surowego lokalnego pliku `wyniki.json`, nagrań, transkrypcji, nazwisk, ścieżek, danych urządzeń, sekretów ani modeli.** Podsumowanie z `--check` nadaje się do dalszej weryfikacji tylko pod warunkiem osobnego, niezależnego potwierdzenia dowodów.

Nawet `SELF_REPORTED_PASS` dla całej macierzy **nie oznacza automatycznego DONE** i nie upoważnia do publikacji. Decyzja o wydaniu oraz integracji z Wiedora pozostaje osobna.

## Kontrola zakresu i dat — 11.11.2026

Wprowadzono dodatkowe ograniczenia walidatora: lokalny plik rejestru do 2 MiB, maksymalnie 512 wpisów, zakaz dat przyszłych. Nie da się przekazać do dalszego odbioru raportu datowanego na jutro, który przesłania wcześniejszy negatywny wynik. Wszystkie testy nadal są **deklaracją operatora**, nie niezależnym potwierdzeniem testu fizycznego. Wpisy pozostają poza GitHub.

## Integralność odczytu rejestru — 15.11.2026

Opcja `--check` czyta odtąd wyłącznie lokalny zwykły plik: nie pozwala na dowiązania symboliczne, sprawdza identyfikator i metadane pliku przed i po odczycie, a ponowny odczyt tego samego uchwytu porównuje SHA-256 nawet przy słabej precyzji znaczników czasu. Limit **2 MiB** jest egzekwowany także na rzeczywistych bajtach odczytanych z pliku, nie tylko na `stat()`. Parser odrzuca powielone pola w JSON (również zapisane z `\\u`), `NaN` i `Infinity`, więc wpis `FAIL` nie zostanie przypadkowo nadpisany późniejszym `PASS` o tej samej nazwie klucza.

Narzędzie nie poświadcza autentyczności podpisów ani wyników testów. Wszelkie `SELF_REPORTED_PASS` nadal wymagają niezależnej weryfikacji, a cały rejestr i dane testera muszą pozostać prywatne.

## 15.11.2026 — bramka statusu DONE dla zadań niesamodzielnych

`scripts/check_vn_microtasks.py` odrzuca teraz oznaczenie **DONE** dla zadań o właścicielu `HUMAN_TEST`, `REVIEW`, `LEGAL`, `PORTAL` lub `DECISION`, jeśli brakuje `acceptance_receipt` z niezależnym potwierdzeniem człowieka i dopuszczalnym odnośnikiem do **anonimowych metadanych** na GitHub Issues. Sukces samego PR, CI, mocka, GitHub-hosted Windows lub pojedynczego deployu nie wystarcza.

Rejestr w `docs/VN_MICROTASKS.json` może przyjąć `acceptance_receipt` **dopiero po faktycznym odbiorze**. Wymagane pola: `schema: videonotes-human-acceptance-v1`, `case_id` identyczne z `acceptance_id`, `kind` zgodne z rolą zadania, `decision: APPROVED`, data testu, SHA zweryfikowanego commita, `attested_by_human: true`, `independently_reviewed: true` i `evidence_url` wskazujące istniejący GitHub Issue zawierający wyłącznie zanonimizowane metadane. Identyczny URL należy dodać do `evidence_refs`. Dodatkowo `PORTAL` wymaga `deployed_sha`, `environment_verified: true` oraz linku do pełnego przebiegu GitHub Actions Wiedory.

**To kontrola poprawności struktury, nie weryfikacja autentyczności.** Same wartości `true`, SHA i link do Issue można wpisać bez realnego testu. Odbierający musi niezależnie sprawdzić faktyczny sprzęt, przebieg, środowisko, prawa/licencje, wyniki CI i datę. Nie wolno wpisywać fikcyjnych pól ani surowych transkrypcji, nazwisk, lokalizacji, danych konta czy nagrań do Issue. Po zaliczeniu każdego testu należy też sprawdzić zależności i dopiero wtedy świadomie zmienić zadanie na DONE. Nie działa żadne automatyczne promowanie etapów.

## Nowe repozytoria po 16.11.2026

Dowody dotyczące silnika KWN należy odtąd rejestrować w `WiedoraNotes/Video-notes`, a odbiory `HOST-01` w `wiedoraWeb/Constant_app`. Historyczne anonimizowane dowody z `testowyemailaplikacja-spec` pozostają dozwolone tylko we właściwym obszarze. Zmiana repozytorium nie stanowi akceptacji testu. Dla zadań sprzętowych dowód w repozytorium hosta nie jest równoważny z fizycznym testem Windows, a PR nie zastępuje podpisanego `acceptance_receipt`.
