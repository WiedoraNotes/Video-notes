# KWN VN-01 — odizolowanie Tkinter od procesu transkrypcji

Data: 14.11.2026. Repozytorium `Video-notes`, gałąź `develop` po odbiorze CI.

## Przyczyna

Interfejs Windows uruchamiał `create_project` w osobnym wątku, ale
odczytywał `StringVar.get()` dla pliku źródłowego, modelu, CLI,
identyfikatora ścieżki audio i języka **dopiero wewnątrz wątku**.
Tkinter wymaga obsługi stanu GUI w głównym wątku. Na niektórych
systemach ta sytuacja kończy się błędem głównego wątku Tk lub
niezamierzoną zmianą źródła, gdy pole formularza zostanie zmodyfikowane
po kliknięciu Rozpocznij.

## Zmiana

`VideoNotesWindow._work` odczytuje wszystkie ustawienia Tk
**przed** uruchomieniem wątku, weryfikuje wybraną ścieżkę audio,
a dalej przekazuje do silnika niezmienny lokalny zestaw wartości.
Wznowienie istniejącego projektu odczytuje wyłącznie jego katalog,
nie wymaga ponownego wskazania modelu ani źródła i nie czyta ich z Tk.

Regresje w `scripts/gui_headless_test.py` działają na prawdziwych
widgetach Tk z kontrolowanym silnikiem, sprawdzając brak odczytu
zmiennych w wątku, zachowanie wybranej ścieżki audio mimo zmian pól
i ścieżkę wznawiania. Uruchomienia GitHub Actions na wirtualnym Windows
i Xvfb Linux nie zastępują odbioru fizycznego Windows z prawdziwym OBS,
modelami i nagraniami PL/EN. Faza VN-01 pozostaje nieodebrana do czasu
rzeczywistego testu.
