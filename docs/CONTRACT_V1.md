# Video Notes — lokalny kontrakt danych v1 (VN-00)

**06.11.2026:** kod i testy kontraktu istnieją, ale format wymiany nie jest jeszcze zatwierdzony do produkcji ani do adaptera WWW.

Program trzyma projekt w lokalnym katalogu użytkownika. Nagranie OBS i model ASR pozostają w lokalizacji wskazanej przez użytkownika. Niczego automatycznie nie wysyła ani nie pobiera.

| Plik | Znaczenie | Gwarancja |
| --- | --- | --- |
| `project.json` | Wersja, UUID, źródło i SHA-256, wybrany indeks ścieżki audio, czas, lokalny model i jego SHA-256 | przy wznowieniu sprawdzana zgodność źródła i modelu |
| `transcript.json` | Surowe segmenty (`id`, `chunk_index`, `start_ms`, `end_ms`, `text`, `status=raw`) i `completed_chunks` | atomowy zapis całego ukończonego fragmentu |
| `edits.json` | Mapa poprawek po ID segmentu | oryginalna transkrypcja nie jest nadpisywana |
| `exports/transcript.txt` | Tekst po poprawkach | UTF-8 |
| `exports/transcript.srt` | Napisy po poprawkach | globalny czas HH:MM:SS,mmm |
| `exports/transcript.vtt` | Napisy po poprawkach | globalny czas HH:MM:SS.mmm |
| `exports/transcript.json` | Przenośny wynik z poprawkami | oddzielny od surowych segmentów |

Obowiązują wersje `videonotes-project-v1`, `videonotes-transcript-v1`, `videonotes-edits-v1`. Segmenty mają jawne identyfikatory, ciągłe indeksy ukończonych fragmentów, czas w milisekundach i walidację długości. Cisza jest ukończonym fragmentem o zerowej liczbie segmentów. Przy błędzie ASR nie nadpisuje się poprzedniego checkpointu.

Wykrycie zmiany SHA-256 pliku lub modelu zatrzymuje wznowienie. Obliczenie SHA-256 wielogigabajtowego filmu wymaga czasu, ale działa ze stałą pamięcią. FFmpeg i whisper.cpp są uruchamiane bez powłoki systemowej; ich potencjalnie prywatne logi nie są przekazywane na stdout.

**Otwarte:** przenośny backup, relokacja pliku źródłowego, migracje v1→v2, odzyskiwanie starego pliku blokady po awarii, instalator Windows i końcowy kontrakt WWW. Nie oznaczać ich DONE na podstawie samego schematu.

## Integralność eksportu napisów — 07.11.2026

W SRT i VTT każdy segment pozostaje jednym cue: wielowierszowe poprawki są łączone w pojedynczy wiersz przez spacje, aby tekst nie wstrzykiwał pozornych znaczników czasu i nowych bloków napisów. W VTT znaki `&`, `<`, `>` są kodowane jako tekst, aby nie interpretować wpisanej transkrypcji jako składni WebVTT. Eksporty TXT/JSON zachowują oryginalne znaki nowej linii i tekst użytkownika. Testy syntetyczne obejmują oba eksportery (Python i WWW); nie zastępują testu rzeczywistych odtwarzaczy napisów.

## Jawne odzyskanie blokady po awarii (07.11.2026)

Po przerwanym działaniu procesu `.processing.lock` może pozostać na dysku. Bez usuwania jakichkolwiek plików projektu sprawdź:

```bash
python -m videonotes lock-status KATALOG_PROJEKTU
```

Stan `active` oznacza działający proces, `stale` potwierdzony brak procesu o danym PID, `unknown` niewystarczające uprawnienia/wynik, `invalid` nieznany format blokady, `missing` brak blokady. **Tylko dla `stale`** po kontroli, że poprzednia transkrypcja rzeczywiście się zakończyła, uruchom:

```bash
python -m videonotes lock-recover KATALOG_PROJEKTU --confirm
python -m videonotes resume KATALOG_PROJEKTU
```

Na Windows sprawdzanie obecności procesu korzysta z `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)`, nigdy z potencjalnie destrukcyjnego `os.kill(pid,0)`. Dla aktywnych, nieznanych, uszkodzonych i zmienionych w trakcie kontroli blokad odmowa jest obowiązkowa. Odzyskiwanie nie kasuje żadnych zapisanych checkpointów, transkrypcji ani edycji. PID może zostać wykorzystany ponownie przez inny proces, dlatego w takiej sytuacji odzyskiwanie jest zachowawczo blokowane; test realnej awarii Windows nadal pozostaje otwarty.

## Wyłączność tworzenia projektu — 12.11.2026

Dwa równoczesne procesy tworzące projekt w tym samym katalogu mogły wcześniej przejść kontrolę pustego katalogu i nadpisać wzajemnie pliki `project.json`, `transcript.json` lub `edits.json`. Teraz przed sprawdzeniem pustego katalogu tworzone jest wyłączne `.creating.lock` w katalogu docelowym. Druga próba odmawia zapisu; ukończony projekt pozostaje niezmieniony. Po udanym utworzeniu trzech plików lub obsłużonym błędzie blokada jest zwalniana. Pusty katalog wskazany przez użytkownika nadal jest obsługiwany.

Jeżeli proces zostanie gwałtownie zakończony, plik `.creating.lock` może pozostać. **Nie usuwać go automatycznie ani nie nadpisywać częściowo zapisanych projektów**. Sprawdzić, czy poprzedni proces zakończył się i czy nie istnieją dane do uratowania. Jest to blokada tworzenia nowego projektu, oddzielna od `.processing.lock` używanej podczas transkrypcji; polecenie `lock-recover` jej nie dotyczy. Dowody testowe obejmują równoległe wywołania i awarię syntetyczną, ale nie stanowią testu fizycznej awarii Windows.

## Kontrola fragmentów PCM z FFmpeg (12.11.2026)

Przetwarzanie VN-01 tworzy segment WAV w nowym katalogu tymczasowym. Silnik używa `ffmpeg -n` (bez nadpisywania), zamiast `-y`, a wcześniej odmawia użycia istniejącej ścieżki wyjściowej. Po zakończeniu procesu sprawdza nie tylko deklarowany w nagłówku RIFF format mono 16 kHz / 16 bit, ale również **fizycznie odczytuje w ograniczonych buforach wszystkie zadeklarowane próbki PCM**. Ucięty ogon WAV po przerwaniu FFmpeg nie zostanie błędnie zaakceptowany przez ASR mimo poprawnego nagłówka. Oryginału OBS ani istniejących plików nie nadpisuje. Test syntetyczny celowo ucina PCM przy zachowaniu niezmienionego nagłówka; pełny test na docelowym Windows i realnym 2h pliku nadal pozostaje osobną bramką.

## Spójność eksportu transkrypcji TXT/SRT/VTT/JSON (12.11.2026)

Eksport używa wspólnej blokady `.transcript-edits.lock` przez odczyt i zapis wszystkich czterech formatów, aby współpracujące edytory nie zmieniały poprawek podczas publikacji. Dodatkowo ponownie przygotowuje i porównuje wszystkie cztery formaty z aktualną transkrypcją oraz ręcznymi poprawkami **zanim zacznie nadpisywać istniejące pliki wynikowe**. Jeśli użytkownik wprowadzi poprawkę w trakcie pierwszego renderowania, narzędzie odmawia publikacji starych napisów i zachowuje wcześniejsze eksporty. Testy syntetyczne sprawdzają zarówno taką kolizję, jak i zwykły eksport czterech spójnych formatów. Nie oznacza to atomowej transakcji obejmującej cztery pliki po rozpoczęciu zapisu; przerwanie dysku w połowie publikacji nadal wymaga osobnego mechanizmu odzyskiwania.

## Spójność Unicode między Pythonem i przeglądarką — 14.11.2026

W wersjonowanych plikach transkrypcji i poprawek obowiązuje poprawny,
jednoznaczny tekst Unicode: polskie znaki i emoji (prawidłowa para
UTF-16 dla kodów spoza BMP) są akceptowane. Niedozwolone są pojedyncze
`surrogate code points` U+D800–U+DFFF, które mogą znaleźć się w
ciągach JSON zapisanych jako `\\uD800` lub `\\uDC00`.

Pythonowy `json.loads` sam w sobie akceptuje takie sekwencje, choć
przy późniejszym zapisie UTF-8 mogą powodować wyjątek kodowania.
JavaScript pozwala zachować je jako tekst, ale przy tworzeniu Blob może
bez ostrzeżenia zastąpić je znakiem U+FFFD. Wspólna walidacja
`videonotes/contracts.py` oraz walidator JS odrzucają je zatem
**przed zapisaniem projektu, poprawki lub eksportu**. Dotyczy to
także propozycji notatek modelu lokalnego oraz edycji w interfejsie
WWW. Poprawny, dosłownie wpisany znak U+FFFD nie jest odrzucany.

Regresje syntetyczne sprawdzają zgodność Python/Node, brak częściowego
zapisu poprawek, poprawny UTF-8 i emoji oraz ochronę oryginalnego ASR.
To nie jest próba jakości transkrypcji z prawdziwej mowy ani odbiór
fizycznych urządzeń.

## Granice długości tekstu i identyfikatora projektu — 14.11.2026

Walidacja przenośna `videonotes-export-v1` w przeglądarce liczy długość
ciągów JavaScript w **jednostkach UTF-16**. Historycznie część desktopowa
Python liczyła punkty kodowe. Na przykład 5001 emoji zajmuje 5001
znaków z perspektywy `len(str)`, lecz 10002 jednostki UTF-16.
Taka poprawka mogła być zapisana w projekcie Windows, po czym odrzucona
przez czytnik WWW/mobilny.

Desktop stosuje teraz `utf16_code_units` z `videonotes/contracts.py`
w walidacji segmentów, poprawek, identyfikatora projektu oraz tekstów
modelu, gdzie obowiązują limity znakowe. Granica treści segmentu wynosi
**10000 jednostek UTF-16** (np. 5000 emoji, ale nie 5001).
Identyfikator projektu może mieć najwyżej **128 jednostek UTF-16**.
Import poprawek WWW jest zgodny z tą samą granicą. Dotyczy to
nowych zapisów i walidacji podczas otwierania plików.

Testy syntetyczne sprawdzają oba brzegi limitu, zgodność Python/JS,
ochronę `transcript.json`, odmowę nadmiernej poprawki oraz pełny lokalny
eksport czterech formatów przy prawidłowej długości. Historyczne projekty
niespełniające nowych ograniczeń wymagają osobnej, bezpiecznej migracji,
a nie automatycznego przycięcia słów. Żaden z tych testów nie zastępuje
odbioru rzeczywistego wielogodzinnego nagrania.

## Stabilny odczyt lokalnych checkpointów i poprawek JSON (14.11.2026)

`load_json` odczytujący `project.json`, `transcript.json` i
`edits.json` wcześniej sprawdzał limit bajtów i dowiązania, ale
nie wykrywał bezbłędnie nadpisania zawartości w trakcie pojedynczego
odczytu, zwłaszcza gdy obcy proces zapisał plik o identycznym
rozmiarze na systemie plików z małą rozdzielczością zegara.

Odczyt działa obecnie w dwóch przebiegach przez ten sam otwarty
plik: pierwszy zbiera ograniczone dane (maksymalnie 64 MiB),
drugi ponownie czyta w porcjach po 64 KiB i porównuje SHA-256.
Następnie kontroluje zgodność obiektu pliku oraz widocznej ścieżki
(przed, podczas i po odczycie): typ zwykłego pliku, numer nośnika,
identyfikator, rozmiar i znaczniki modyfikacji. Plik zmieniający
się podczas odczytu jest **odrzucany bez modyfikacji projektu**.
Walidacja duplikatów JSON i samego kontraktu działa nadal osobno.

Regresje w GitHub Actions symulują różne bajty z tego samego
deskryptora mimo niezmienionych metadanych, podmianę pliku po
odczycie oraz wzrost danych ponad limit. Nie jest to globalna
transakcja trzech plików ani blokada przed kolejnymi zmianami
po zakończeniu odczytu. Przy sporze z edytorem nadal obowiązują
osobne blokady edycji i ponowne sprawdzenie projektu przed zapisem.
Nie zastępuje to rzeczywistej awarii dysku na fizycznym Windows.
