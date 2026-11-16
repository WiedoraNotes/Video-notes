# KWN / Video Notes — aktualne repozytoria

**Decyzja właściciela 16.11.2026:** `WiedoraNotes/Video-notes` jest jedynym głównym repozytorium rozwoju KWN. Gałąź `develop` obejmuje kod Windows, ASR, notatki, adapter WWW, testy i rejestry `docs/VN_STATUS.json` oraz `docs/VN_MICROTASKS.json`. `main` pozostaje stabilnym punktem odniesienia.

**Miejsce praktycznych testów i integracji:** `wiedoraWeb/Constant_app` na gałęzi `develop`. Integracja hosta jest odbierana osobno. Istniejący PR #246 należy zweryfikować przed jakimkolwiek scaleniem. Nie modyfikować produkcyjnej Wiedory w ramach prac nad samym silnikiem KWN.

**Historia:** wcześniejsze repozytoria `testowyemailaplikacja-spec/Video-notes` i `testowyemailaplikacja-spec/Constant_app` to od 16.11.2026 źródła historycznych PR-ów, SHA i raportów. Zachować autentyczne odnośniki jako dowody. Nowe implementacje i nowe odbiory rejestrować na kontach WiedoraNotes/wiedoraWeb. Sama migracja nie potwierdza nowych testów.

**Osobne plany:** VN-00–VN-08 to 9 etapów i 37 mikrozadań. Dawne 189 kryteriów i 22 etapy Wiedory nie mogą być dodawane do nowych liczników. Bez naturalnej mowy, sprzętu, legal review i niezależnego podpisanego odbioru etap nie otrzymuje DONE. Konwerter plików pozostaje oddzielnym projektem.
