# Perfusion System Hydraulic Simulator V1.0

Wissenschaftliches Werkzeug zur hydraulischen Modellierung, Simulation, Optimierung und experimentellen Validierung eines
Low-Throughput-Perfusionssystems für das Tissue Engineering (Masterarbeit *„Entwicklung, Fertigung und biologische
Validierung eines Low-Throughput-Perfusionssystems für das Tissue Engineering“*).

> Stationäres **1D-Netzwerkmodell** – kein Ersatz für 3D-CFD oder biologische Validierung.
> Alle voreingestellten Zahlenwerte sind **Beispielparameter** und müssen durch reale Geometrien und Messwerte ersetzt werden.

## 1 Installation (Windows)

Voraussetzungen: Windows 10/11, **Python 3.12** (https://www.python.org/downloads/, bei der Installation
„Add python.exe to PATH“ anhaken), Internetzugang nur für die einmalige Paketinstallation.

1. Ordner `PerfusionSimulator` an einen Ort ohne Sonderzeichen kopieren (z. B. `C:\Users\<Name>\PerfusionSimulator`).
2. Doppelklick auf **`install.bat`** – legt die virtuelle Umgebung `.venv` an, installiert alle Pakete aus
   `requirements.txt`, lädt optional Chrome für den Abbildungsexport (Kaleido) und führt die Tests aus.
3. Doppelklick auf **`start.bat`** – die Anwendung öffnet sich im Browser unter http://localhost:8501.
4. Beenden: Konsolenfenster schließen.

Fehlerbehebung

| Meldung | Ursache / Lösung |
|---|---|
| `Python was not found` | Python 3.12 installieren, PATH-Option aktivieren, Rechner neu anmelden |
| `Package installation failed` | Internet/Proxy prüfen; `install.bat` erneut starten |
| `not installed yet` beim Start | zuerst `install.bat` ausführen |
| Port 8501 belegt | andere Instanz schließen |
| PNG/SVG/PDF-Export nutzt „matplotlib-fallback“ | Kaleido findet kein Chrome: Google Chrome installieren oder `.venv\Scripts\plotly_get_chrome.exe` ausführen. Der Fallback funktioniert offline mit vereinfachter Gestaltung |

Linux/macOS: `python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/streamlit run app.py`

Es werden keine kostenpflichtigen APIs, Cloud-Dienste oder externen Server benötigt; alles läuft lokal.

## 2 Bedienung (Kurzüberblick)

Navigation links, Sprache EN/DE umschaltbar. Jede Parameteränderung löst eine vollständige Neuberechnung aller Volumenströme und Drücke aus.

| Seite | Inhalt |
|---|---|
| Dashboard | Kennzahlen, Reaktor- und Bypassströme, Gleichmäßigkeit, Volumen, Warnungen, Systemdiagramm |
| System Diagram | interaktives Schaltbild; Klick auf ein Bauteil öffnet dessen Parameter |
| Fluid / Pump / Tubing / Splitter / Bioreactor / Throttle / Bypass | Konfiguration aller Komponenten (inkl. Verengungen, Pumpenkennlinien-Import, Drosselkennlinien) |
| Simulation Results | Tabellen je Reaktor/Segment/Knoten, Diagramme, Konvergenz und Residuen |
| Parameter Studies | 1D, 2D (Heatmap, 3D-Fläche), mehrdimensional (LHS), Sensitivität, Monte-Carlo, Fertigungstoleranzen |
| Optimization | 7 Zielfunktionen, Nebenbedingungen, Erklärung nicht realisierbarer Vorgaben |
| Experimental Validation | Vorlagen, Import CSV/Excel, MAE/RMSE/Bias/KI/R², Kalibrierung mit getrennten Datensätzen |
| Scenarios & Projects | 17 Szenarien, Projekte speichern/laden/duplizieren/versionieren/vergleichen |
| Scientific Documentation | Gleichungen, Annahmen, Grenzen, Verifikationsbericht |
| Export | CSV/Excel/JSON, Abbildungen PNG (300 dpi)/SVG/PDF/HTML, PDF-Simulationsbericht |

## 3 Nutzung ohne Oberfläche (Python-Skripte)

```python
from core.system import default_system
from core.simulation import run_simulation
cfg = default_system(n_reactors=4, bypass=True)
cfg.reactor_paths[0].throttle.opening_percent = 40
res = run_simulation(cfg)
print(res.reactors[["reactor", "Q_ml_min", "dp_pa"]])
```

Ausführliches Beispiel: `python tools/example_script.py` (Simulation, Parameterstudie, Toleranzanalyse, Optimierung).

## 4 Projektstruktur

```
PerfusionSimulator/
├── app.py                 Streamlit-Einstieg
├── install.bat / start.bat / run_tests.bat / requirements.txt
├── core/                  Berechnungsbibliothek (unabhängig von Streamlit)
│   ├── units.py fluids.py hydraulics.py elements.py
│   ├── tubing.py constrictions.py throttles.py scaffolds.py bioreactors.py splitters.py bypass.py pumps.py
│   ├── network.py solver.py system.py simulation.py
│   ├── sensitivity.py optimization.py validation.py project.py export.py verification.py
├── ui/                    Seiten und Editoren der Oberfläche, i18n (EN/DE)
├── visualization/         Plotly-Diagramme, Systemdiagramm, Export, PDF-Bericht
├── scenarios/             17 vordefinierte Szenarien (+ configs/*.json)
├── config/                Standardkonfiguration (JSON/YAML)
├── experimental_data/     Vorlagen für Messreihen (templates/)
├── projects/ results/ reports/   Ablage für Projekte, Läufe, Studien, Berichte
├── tests/                 pytest-Testsuite (158 Tests)
├── documentation/         wissenschaftliche Doku, Test-Doku, Verifikations- und Testbericht
└── tools/                 Berichtsgeneratoren, Beispielskript
```

## 5 Implementierungs- und Teststatus V1.0

**Implementiert und automatisch getestet:** SI-Einheitenkern; Fluidmodelle (Wasser, NaCl, Medium, benutzerdefiniert, temperaturabhängig, Überschreibungen); Schlauchsegmente mit Biegungen, Verbindern, Querschnittsänderungen; Verengungsmodul (6 Szenarien, Durchmesser- vs. Flächenreduktion, numerisch exakte Blockierung); Drosseln (6 Modelle, 4 Kennlinien, Kalibrierfaktor); Bioreaktoren (6 Zustände, Darcy/Forchheimer, Porenmodell-Schubspannung); Splitter (4 Modi, beliebige Anschlusszahl); Bypass (integrierter Port oder T-Stücke); Pumpenmodi A–D inkl. Kennlinienimport; generischer Netzwerk-Solver (Newton + SciPy-Fallback, Residuen, Konvergenz, Plausibilitätsprüfungen); frei wählbare Reaktoranzahl; Parameterstudien, Sensitivität, Monte-Carlo, Toleranzen; Optimierung (7 Ziele) mit Unzulässigkeitsdiagnose; Validierung/Kalibrierung; Projektverwaltung; Export; 17 Szenarien; UI-Seiten (Smoke-Tests).

**Implementiert, nur eingeschränkt automatisch getestet:** Abbildungsexport (Kaleido hier getestet; Matplotlib-Fallback vereinfacht), PDF-Bericht (Erzeugung geprüft, Layout manuell gesichtet), Klick-Auswahl im Diagramm (im Browser geprüft), Pulsationsmodell (rein illustrativ).

**Bewusst offen / Annahmen:** alle Bauteilparameter und Medienstoffwerte sind Beispielwerte; K-Werte bei kleinen Re unsicher; keine transiente Hydraulik (Compliance/Trägheit); keine strömungsverhältnisabhängigen Verzweigungsverluste; keine Umströmung von Scaffolds; `install.bat`/`start.bat` wurden in einer Linux-Umgebung erstellt und nicht auf einem Windows-PC ausgeführt.

Weitere Details: `documentation/scientific_documentation.md`, `documentation/test_documentation.md`,
`documentation/verification_report.md`, `documentation/test_results.md`.
