# Wissenschaftliche Dokumentation – Perfusion System Hydraulic Simulator V1.0

Masterarbeit: *„Entwicklung, Fertigung und biologische Validierung eines Low-Throughput-Perfusionssystems für das Tissue Engineering“*

> **Einordnung.** Die Software ist ein **stationäres, eindimensionales hydraulisches Netzwerkmodell** (Lumped-Parameter-Modell).
> Sie ersetzt weder eine dreidimensionale CFD-Simulation noch eine biologische Validierung. Alle voreingestellten
> Parameter sind **Beispielwerte (Annahmen)**, solange keine Messdaten vorliegen.

---

## 1 Ergebnisklassen

Jede Ausgabegröße wird einer der folgenden Klassen zugeordnet (Spalte `quantity_type` bzw. `classification`):

| Klasse | Bedeutung | Beispiele in der Software |
|---|---|---|
| analytisch berechnet | geschlossene Lösung der Modellgleichungen | laminarer Schlauchdruckverlust (Hagen-Poiseuille), Darcy-Druckverlust, Wandschubspannung laminar |
| numerisch simuliert | Lösung des nichtlinearen Netzwerk-Gleichungssystems | Volumenstromverteilung, Knotendrücke, Pumpenarbeitspunkt |
| empirische Abschätzung | Korrelationen / Handbuchbeiwerte | turbulente Reibungszahl (Colebrook), K-Werte, Orifice-/Kv-Drosselmodell, Wasser-Viskositätskorrelation |
| modellbasierte Abschätzung | Ergebnis eines expliziten Ersatzmodells | Porengeschwindigkeit, Scaffold-Schubspannung (Kapillarmodell), Knick-/Quetschmodell |
| experimentell kalibriert | Parameter aus Messdaten angepasst | Drossel mit `dp_curve`/Öffnungstabelle, kalibrierte Faktoren, Reaktor mit gemessenem Widerstand |
| experimentell validiert | Vorhersage durch **unabhängige** Messdaten bestätigt | erst nach Vergleich auf Validierungsdatensatz (Seite *Experimental Validation*) |

---

## 2 Einheiten und Konventionen

* Intern ausschließlich SI: m, s, kg, Pa, m³/s, Pa·s. Umrechnung nur an den Schnittstellen (UI, Import, Export), Modul `core/units.py`.
* Konfigurationsparameter tragen die Einheit im Namen (`length_m`, `inner_diameter_mm`, `flow_rate_ml_min`, `opening_percent`, `pressure_difference_pa`).
* Drücke sind **Überdrücke** relativ zur Atmosphäre; der Flüssigkeitsspiegel des Reservoirs ist der Referenzknoten (Standard 0 Pa).
* Kantenrichtung = positive Strömungsrichtung; negative Volumenströme bedeuten Rückströmung.
* 1 mL/min = 1,6667·10⁻⁸ m³/s; 1 mbar = 100 Pa; 1 mmHg = 133,322387415 Pa.

---

## 3 Mathematische Grundlagen

### 3.1 Massenerhaltung (Kontinuität)

Für inkompressible Strömung gilt an jedem Knoten *i* ohne vorgegebenen Druck

$$\sum_{j\in \text{in}(i)} Q_j - \sum_{j\in \text{out}(i)} Q_j = 0 .$$

Für das Gesamtsystem folgt daraus exakt $Q_\text{Pumpe} = \sum_k Q_{\text{Reaktor},k} + Q_\text{Bypass}$ (in den Tests auf ~10⁻¹⁵ relativ geprüft).

### 3.2 Energieerhaltung, Bernoulli-Gleichung und Gültigkeit

Für einen Stromfaden zwischen Ein- und Austritt eines Bauteils gilt die erweiterte Bernoulli-Gleichung

$$p_1 + \tfrac{\rho}{2}\alpha_1 v_1^2 + \rho g z_1 = p_2 + \tfrac{\rho}{2}\alpha_2 v_2^2 + \rho g z_2 + \Delta p_\text{V}.$$

Die *verlustfreie* Bernoulli-Gleichung gilt nur stationär, inkompressibel, reibungsfrei entlang einer Stromlinie. Sie wird daher nur dort verwendet, wo diese Annahmen näherungsweise zutreffen (Blendengleichung der Drossel, dynamischer Druck). Im Netzwerk werden Knotendrücke als **statische Drücke** behandelt; Änderungen der kinetischen Energie zwischen unterschiedlichen Querschnitten werden **ausschließlich** über die lokalen Verlustbeiwerte (Borda-Carnot, Kontraktion) erfasst. Der dynamische Druck $\rho v^2/2$ wird je Segment ausgegeben; bei den typischen Geschwindigkeiten (≈ 0,01–0,1 m/s) beträgt er 0,05–5 Pa und ist gegenüber den Reibungsverlusten klein.

Zweigleichung jedes passiven Bauteils:

$$p_\text{ein} - p_\text{aus} = \operatorname{sign}(Q)\,\Delta p_\text{V}(|Q|) + \rho g\,\Delta z ,\qquad \Delta z = z_\text{aus}-z_\text{ein}.$$

### 3.3 Reynolds-Zahl und Strömungsregime

$Re = \rho v d / \mu$ mit $v = 4Q/(\pi d^2)$ bzw. hydraulischem Durchmesser $d_h = 4A/U$.
Regimegrenzen (konfigurierbar): laminar $Re<2000$, transitional $2000\le Re\le 4000$, turbulent $Re>4000$ (übliche ingenieurmäßige Konvention; der reale Umschlag hängt von Einlaufbedingungen und Störungen ab).

### 3.4 Darcy-Weisbach und Hagen-Poiseuille (ohne Doppelzählung)

$$\Delta p_\text{R} = f\,\frac{L}{d}\,\frac{\rho v^2}{2}.$$

* **laminar:** $f = 64/Re$ (exakt für ausgebildete Rohrströmung). Einsetzen liefert exakt die Hagen-Poiseuille-Gleichung
  $$\Delta p = \frac{128\,\mu L}{\pi d^4}\,Q = R_\text{HP}\,Q .$$
  **Herleitung:** $f\frac{L}{d}\frac{\rho v^2}{2} = \frac{64\mu}{\rho v d}\frac{L}{d}\frac{\rho v^2}{2} = \frac{32\mu L v}{d^2} = \frac{32\mu L}{d^2}\frac{4Q}{\pi d^2} = \frac{128\mu L Q}{\pi d^4}$.
  Daher wird Hagen-Poiseuille **nicht zusätzlich** addiert; die Software berechnet Reibung nur einmal (Darcy-Weisbach mit regimeabhängigem $f$). Folge: $R\propto L$ und $R\propto d^{-4}$ (Referenzfälle V01–V03).
* **turbulent:** Colebrook-White (implizit, iterativ gelöst; Startwert Swamee-Jain); alternativ wählbar Swamee-Jain oder Haaland (explizit).
  $$\frac{1}{\sqrt f} = -2\log_{10}\!\left(\frac{\varepsilon/d}{3{,}7} + \frac{2{,}51}{Re\sqrt f}\right)$$
* **transitional:** lineare Interpolation von $f$ in $Re$ zwischen $f_\text{lam}(2000)$ und $f_\text{turb}(4000)$. Dies ist eine **numerische Überbrückungsannahme** (stetige, monotone Kennlinie für den Newton-Löser), kein physikalisches Modell intermittierender Strömung. Ergebnisse im Übergangsbereich werden mit Warnung versehen.

**Wandschubspannung:** $\tau_w = f\rho v^2/8$; laminar exakt $\tau_w = 8\mu v/d = 32\mu Q/(\pi d^3)$ (V05).

### 3.5 Lokale Druckverluste

$\Delta p = K\,\rho v^2/2$ mit $K$ bezogen auf die mittlere Geschwindigkeit des nominellen Segmentquerschnitts.

| Element | Modell | Klasse |
|---|---|---|
| Biegung, Verbinder | konstanter K je Stück (Benutzer, Annahme) | empirisch |
| Verbinder (optional) | 2-K-Methode $K = K_1/Re + K_\infty(1+1/D_\text{in})$, $D_\text{in}$ in Zoll | empirisch |
| plötzliche Erweiterung | Borda-Carnot $K=(1-A_1/A_2)^2$ (Impulsbilanz) | analytisch (hohe Re) |
| plötzliche Verengung | $K \approx 0{,}5(1-A_2/A_1)$ bezogen auf $v_2$ | empirisch |
| Splitter-, T-Stück-, Drossel-K | Benutzerwerte, kalibrierbar | Annahme / kalibriert |

Lokale Verluste werden **zusätzlich** zur Rohrreibung der *verbleibenden* geraden Länge addiert. Bei den sehr kleinen Reynolds-Zahlen der Perfusion sind tabellierte (turbulente) K-Werte unsicher; sie sind daher als kalibrierbare Parameter ausgeführt.

### 3.6 Hydraulischer Widerstand

Sekantenwiderstand $R = \Delta p/Q$ und differentieller Widerstand $R_d = \mathrm d\Delta p/\mathrm dQ$. Laminar sind beide gleich und konstant (lineares Netzwerk); mit lokalen Verlusten/Blenden wird das Netzwerk nichtlinear.
Serien-/Parallelschaltung (linear): $R_s=\sum R_i$, $1/R_p = \sum 1/R_i$ (V11–V13).

### 3.7 Darcy-Gesetz und Darcy-Forchheimer für poröse Scaffolds

$$\Delta p = \frac{\mu H}{k A}\,Q \quad(\text{Darcy}),\qquad \frac{\Delta p}{H} = \frac{\mu}{k}u + \beta\rho u^2 \quad(\text{Forchheimer, optional}),\qquad u = Q/A.$$

$\beta$ direkt oder über $\beta = C_F/\sqrt{k}$ (dimensionsloser $C_F$ = **Annahme**). Gültigkeitsindikator $Re_k = \rho u\sqrt k/\mu$; bei $Re_k \gtrsim 1$ wird gewarnt.
Porengeschwindigkeit (Dupuit-Forchheimer): $u_p = u/\varepsilon$ (Abschätzung, Tortuosität vernachlässigt).

**Scaffold-Schubspannung – explizites Porenmodell (nur Abschätzung):** Bündel gerader, paralleler Zylinderkapillaren gleichen Radius *r*. Poiseuille in jeder Kapillare liefert $k=\varepsilon r^2/8 \Rightarrow r=\sqrt{8k/\varepsilon}$; mittlere Wandschubspannung $\tau = 4\mu u_p/r$, also

$$\tau_\text{Pore} = \frac{4\mu u/\varepsilon}{\sqrt{8k/\varepsilon}} = \frac{\sqrt2\,\mu u}{\sqrt{k\varepsilon}} .$$

Nicht abgebildet: Tortuosität, Porengrößenverteilung, lokale Spitzen. Für lokale Schubspannungsverteilungen ist µCT-basierte CFD erforderlich.

### 3.8 Nicht-kreisförmige und veränderliche Querschnitte

* Ellipse (Halbachsen *a*, *b*), exakt laminar: $R = 4\mu L(a^2+b^2)/(\pi a^3 b^3)$ (für *a=b* = Hagen-Poiseuille, V09).
* Linear konischer Abschnitt (Schmierfilmnäherung): $R = \frac{128\mu L}{3\pi}\frac{d_1^2+d_1d_2+d_2^2}{d_1^3d_2^3}$ (V10); in der Software numerisch über Scheiben integriert, gültig in allen Regimen.
* Nicht-laminar in nicht-kreisförmigen Querschnitten: Darcy-Weisbach mit $d_h$ (Näherung, gekennzeichnet).

---

## 4 Fluidmodelle

| Fluid | Dichte | Viskosität | Status |
|---|---|---|---|
| Wasser | Tanaka et al. (2001), 0–40 °C | Vogel-Korrelation $\mu = A\,10^{B/(T-C)}$, A = 2,414·10⁻⁵ Pa·s, B = 247,8 K, C = 140 K | Korrelation; Abweichung gegen Tabellenwerte < 1,5 % (V24–V27) |
| NaCl 0,9 % | 1,0046 × Wasser | 1,02 × Wasser | **Annahme (Näherung)** – messen |
| Zellkulturmedium | 1,007 × Wasser | 1,05 × Wasser | **Annahme** – Medium mit/ohne Serum stark unterschiedlich; Messung bei 37 °C erforderlich |
| benutzerdefiniert | Wert bei T_ref, optional mit Temperaturabhängigkeit von Wasser skaliert | | Benutzer |

Überschreibungen (Dichte, dyn./kin. Viskosität, Verhältnisse) haben Vorrang. Für Medien werden **keine** universellen Stoffwerte unterstellt; die Herkunft jedes Wertes wird angezeigt (`provenance`).

---

## 5 Komponentenmodelle

### 5.1 Schlauchsegment
Länge, ID, AD, Wandstärke (konsistenzgeprüft), Material (typische Rauheit = Annahme, nur turbulent relevant), Höhenunterschied, Biegungen, Verbinder (inkl. Volumen), Querschnittsänderungen am Segmentaustritt, Zusatz-K, Verengungen. Ausgaben: Q, v, Re, Regime, R, Δp (Reibung/lokal/Verengung), τ_w, Volumen, Verweilzeit, p_ein, p_aus.

### 5.2 Schlauchverengungen und Blockierungen (`core/constrictions.py`)
* Spezifikation **Durchmesserreduktion** $s_d = 1-d_\text{eff}/D$ vs. **Querschnittsreduktion** $s_A = 1-A_\text{eff}/A$ (ausdrücklich getrennt; 50 % Durchmesser = 75 % Fläche, V29), alternativ effektiver Durchmesser bzw. Fläche.
* `local`: kurzer Engpass mit Kontraktions- und Borda-Carnot-Verlust; `continuous`: gleichförmig oder linear konisch; `partial_compression`: elliptischer Querschnitt mit erhaltenem Umfang (unelastische Wand) – **vereinfachtes Ersatzmodell**; `kink`: kalibrierbares Ersatzmodell (K_kink + optionaler Ersatzdurchmesser), Standardwerte sind Platzhalter; `blocked`: geschlossener Pfad.
* Die Verengungslänge wird von der Reibungslänge des Schlauchs abgezogen (keine Doppelzählung).
* Vollständige Blockierung: der Pfad wird im Solver als geschlossen behandelt (Q = 0 exakt), kein „sehr großer Widerstand“.

### 5.3 Drosseln
Öffnungsgrad θ → relative Durchlasskapazität g(θ) (linear, gleichprozentig $r^{\theta-1}$, schnellöffnend $\sqrt\theta$, Messtabelle). Modelle: Widerstand $R_\text{open}/g$; Blende $\Delta p = \frac{128\mu L_t}{\pi d^4}Q + \frac{\rho Q^2}{2C_d^2A^2}$ mit $A=gA_\text{max}$; K-Wert $K_\text{open}/g^2$; Kv/Cv nach IEC-60534-Definition ($K_v = 0{,}865\,C_v$; turbulente Auslegungsbeziehung – bei kleinen Re nur indikativ); experimentelle Δp-Kennlinien (Fit $\Delta p=aQ+bQ^2$, $a,b\ge0$, lineare Interpolation in θ). θ = 0 → geschlossen. **50 % Öffnung ≠ 50 % Volumenstrom** (Test `test_throttle_half_open_is_not_half_flow`). Kalibrierfaktor multipliziert Δp.

### 5.4 Bioreaktor
Reihenschaltung: Einlasskanal → Erweiterung (Borda-Carnot) → freie Kammerlänge → Scaffold (Darcy/Forchheimer) → Kontraktion → Auslasskanal → interner Zusatzwiderstand → Zusatz-K. Ein gemessener Gesamtwiderstand ersetzt das interne Modell. Zustände: `empty` (Kammer ohne Einbauten), `no_scaffold` (Halter/Netz mit K_holder, kein Scaffold), `with_scaffold`, `reduced_permeability` (k·Faktor), `partially_blocked` (offene Scaffoldfläche × (1−Anteil)), `blocked`. Diese Interpretation der Zustände ist eine Festlegung und anpassbar. Annahme: der gesamte Strom passiert das Scaffold (abgedichteter Rand); Umströmung wird nicht modelliert (Warnung bei d_Scaffold < d_Kammer).

### 5.5 Splitter
Knoten (Hub) + je Anschluss ein Kanalelement (Kanal-Reibung + K + optionaler linearer Widerstand). Modi: symmetrisch, asymmetrisch, ideal verlustfrei, individuelle Widerstände. Strömungsverhältnisabhängige Verzweigungsverluste werden **nicht** vorhergesagt, sondern über kalibrierbare K-Werte abgebildet. Keine 3D-CFD.

### 5.6 Bypass
Fünfter Parallelpfad (Schlauch → Drossel → [Zusatzwiderstand] → Schlauch). Integration über zusätzlichen Splitteranschluss (5-Wege) oder über T-Stücke in Zu- und Rücklauf (K_run, K_branch). Vergleich mit/ohne Bypass im UI.

### 5.7 Pumpe
| Modus | Gleichung | Hinweis |
|---|---|---|
| A konstanter Volumenstrom | $Q = Q_\text{soll}$ | Druck folgt aus dem Netzwerk |
| B konstanter Differenzdruck | $p_\text{aus}-p_\text{ein} = \Delta p_\text{soll}$ | |
| C Kennlinie | $\Delta p = H(Q;n)$, lineare Interpolation zwischen Drehzahlen, außerhalb Affinitätsskalierung (Extrapolation, Warnung) | Import CSV/Excel |
| D Verdränger/Peristaltik | $Q = \eta_v\,n V_U/60 - C_\text{slip}\Delta p$, $V_U \approx A_\text{Schlauch}\,2\pi R_\text{Bahn}$ falls nicht vorgegeben | grobe geometrische Abschätzung, Annahmen |

Hydraulische Leistung $P = Q\,\Delta p$. Das optionale Pulsationsmodell ist rein kinematisch (gleichgerichteter Sinus mit Rollenfrequenz $f = nN/60$) und **keine** validierte transiente Simulation (keine Compliance, Trägheit, Wellenausbreitung).

---

## 6 Hydraulische Netzwerkmodellierung und numerisches Lösungsverfahren

**Netzwerk:** gerichteter Multigraph aus Knoten und Komponenten (`core/network.py`); beliebige Topologien, mehrere Pumpen und Referenzknoten möglich. Das Standardsystem (`core/system.py`) ist nur eine Instanz; die Reaktoranzahl ist frei (getestet 1–8).

**Gemischte Formulierung:** Unbekannte sind Knotendrücke (ohne Referenzknoten) und Kantenvolumenströme. Gleichungen: Kontinuität je Knoten, Zweiggleichung je passiver Kante, Pumpenresiduum je Pumpe. Vorteil: geschlossene Komponenten werden exakt mit Q = 0 aus dem Gleichungssystem entfernt; ideale (verlustfreie) Verbinder sind zulässig.

**Topologische Vorprüfung:** Zusammenhangskomponenten der offenen Kanten; Abschnitte ohne Druckreferenz (beidseitig geschlossen) erhalten p = NaN, Q = 0 und eine Meldung. Physikalisch unmögliche Fälle werden erkannt und erklärt (Modus A gegen vollständig geschlossenen Kreis; Verdrängerpumpe ohne Schlupf gegen geschlossenen Kreis).

**Skalierung:** $Q_s$ (Pumpensollwert bzw. 10⁻⁷ m³/s), $P_s$ = 1 kPa; alle Residuen dimensionslos.

**Startwert:** Lösung des linearisierten Netzwerks (Sekantenwiderstände bei Referenzstrom; Pumpe linearisiert).

**Iteration:** gedämpftes Newton-Raphson-Verfahren mit Armijo-Backtracking; Elementableitungen $\mathrm d\Delta p/\mathrm dQ$ per zentraler Differenz; Jacobi-Regularisierung nur für verschwindende Ableitungen (rein quadratische Elemente bei Q=0). Rückfallebene: `scipy.optimize.root` (MINPACK hybrd, dann Levenberg-Marquardt).

**Konvergenzkriterien (konfigurierbar, `SolverSettings`):**
$\max_i |r_{\text{Masse},i}| \le 10^{-10}\,Q_s$ (m³/s) **und** $\max_j |r_{\text{Druck},j}| \le 10^{-6}$ Pa. Ausgegeben werden Iterationen, Methode, Residuen je Gleichung, Residuenverlauf, Konditionszahl der Jacobi-Matrix (Warnung > 10¹⁴), isolierte Knoten, geschlossene Kanten.

**Plausibilitätsprüfungen nach der Lösung:** Pumpendruck > zulässig (Fehler), negativer Pumpendruck in Modus A, Arbeitspunkt außerhalb der Kennlinie, absoluter Druck < Dampfdruck (Kavitation, Modell ungültig), Unterdruck < −200 mbar (Ausgasungsrisiko, indikativer Schwellwert = Annahme), Rückströmung, Re > 2000, $Re_k \ge 1$, Geometrieinkonsistenzen, Verteilung CV > 5 %.

---

## 7 Randbedingungen und Modellannahmen

1. stationär, inkompressibel, isotherm, newtonsches Fluid;
2. starre Schläuche (keine Compliance, kein Druck-Aufweiten), keine Pumpenpulsation im stationären Modell;
3. ausgebildete Strömung in Segmenten; Einlaufeffekte nur über K;
4. Reservoir offen, Spiegelhöhe konstant; Niveaus über Δz der Segmente; im geschlossenen Kreis heben sich hydrostatische Anteile im Pumpendruck auf (Test);
5. gleiche Kennlinie für Vor- und Rückströmung (antisymmetrisch);
6. homogene, isotrope Scaffolds; Durchströmung über den gesamten Querschnitt;
7. Junction-Verluste über konstante K-Werte;
8. alle Default-Parameter = Beispielwerte.

## 8 Gültigkeitsbereiche und Modellgrenzen

* Hagen-Poiseuille/Darcy: laminar, ausgebildet, $Re_k<1$. Für Perfusionsraten im mL/min-Bereich und ID ≈ 1–3 mm ist Re ≈ 1–100 (laminar).
* Turbulente Korrelationen: Swamee-Jain 5·10³ ≤ Re ≤ 10⁸; Colebrook für technisch raue Rohre.
* Wasserdichte 0–40 °C; Vogel-Viskosität geprüft 10–60 °C.
* K-Werte bei Re < 100 unsicher (Faktor 2 und mehr möglich) – Kalibrierung empfohlen.
* Ersatzmodelle (Quetschung, Knick, Splitter) sind vereinfachend; 3D-Effekte (Sekundärströmungen, Ablösung, ungleichmäßige Scaffold-Anströmung) werden nicht erfasst.
* Keine Aussage über Zellverhalten, Stofftransport (O₂, Nährstoffe) oder Schubspannungsverteilung im Scaffold.

## 9 Unsicherheiten

* Parameterunsicherheit (Durchmesser ∝ d⁻⁴!, Permeabilität, K-Werte, Viskosität) dominiert typischerweise die numerische Unsicherheit (Residuen ~10⁻⁹).
* Werkzeuge: lokale Sensitivitäten (Elastizitäten), Monte-Carlo mit Normal-/Gleich-/Lognormalverteilung, Fertigungstoleranzstudie der Schlauch-ID (Toleranz = 2σ bei Normalverteilung), Latin-Hypercube-Studien. Ergebnisse: Mittelwert, SD, Min/Max, 2,5/50/97,5-Perzentile; reproduzierbar per Seed.
* Beispiel: Bei laminarer Strömung bewirkt eine ID-Abweichung von 1 % eine Widerstandsänderung von ≈ 4 % (Elastizität −4, Test `test_local_sensitivity_laminar_exponents`).

## 10 Optimierung

Zielfunktionen 1–7 (homogen, individuelle Ziele, min. Pumpendruck, min. Verluste, min. Volumen, robust gegen Toleranzen, robust gegen Scaffoldstreuung); Nebenbedingungen als normierte quadratische Strafterme; Verfahren Powell (beschränkt, Multistart) oder Differential Evolution (Seed). Kennzahlen: Mittelwert, SD, CV, maximale relative Abweichung, RMSE gegen Ziele. Nicht realisierbare Vorgaben werden über Grenzkonfigurationen erklärt (z. B. Mindestdruck bei voll geöffneten Drosseln; maximal erreichbarer Anteil eines Reaktors, wenn nur dessen Drossel offen ist; Verletzung der Massenbilanz der Zielwerte). Drosseln können nur Widerstand hinzufügen – ein Pfad kann nie mehr Strom erhalten als bei voll geöffneter eigener Drossel.

## 11 Experimentelle Validierungsstrategie

1. **Stoffwerte:** Viskosität und Dichte des tatsächlich verwendeten Mediums bei 37 °C messen.
2. **Komponentenweise Kalibrierung** (Vorlagen 01–08): Einzelschlauch (Prüfung d⁻⁴/L-Skalierung, effektive ID), Verengungen, Drosselkennlinien (Öffnung → Δp(Q)), Pumpenkennlinien (Modus C) bzw. Verdrängungsvolumen/Schlupf (Modus D), Splitter-K, Einzelreaktor mit/ohne Scaffold (Permeabilität).
3. **Systemvalidierung** (Vorlagen 09–10) mit **unabhängigen** Datensätzen (Spalte `dataset = validation`), die nicht zur Kalibrierung verwendet wurden.
4. Kennzahlen: absolute/relative Abweichung, MAE, RMSE, Bias, SD, R² (n ≥ 3), 95-%-Konfidenzintervall des Bias (t-Verteilung, Annahme: unabhängige, normalverteilte Abweichungen), Anteil innerhalb 2u.
5. Ergebnisse erst nach Schritt 3 als „experimentell validiert“ bezeichnen.

## 12 Literatur

Hinweis: Es werden ausschließlich Standardwerke und Originalarbeiten genannt, deren Existenz bekannt ist. Es werden bewusst **keine DOI-Nummern** angegeben; bibliografische Details (Auflage, Seiten) bitte vor Übernahme in die Masterarbeit am Original prüfen.

1. White, F. M.: *Fluid Mechanics*. McGraw-Hill (verschiedene Auflagen). – Darcy-Weisbach, Moody-Diagramm, lokale Verluste, Bernoulli.
2. Bird, R. B.; Stewart, W. E.; Lightfoot, E. N.: *Transport Phenomena*. 2. Aufl., Wiley, 2002. – Hagen-Poiseuille, Schmierfilmnäherung.
3. Idelchik, I. E.: *Handbook of Hydraulic Resistance*. Begell House (3. Aufl.). – Verlustbeiwerte für Formstücke, Verzweigungen.
4. Crane Co.: *Flow of Fluids Through Valves, Fittings, and Pipe*. Technical Paper No. 410. – K-Werte, Kv/Cv.
5. Colebrook, C. F. (1939): Turbulent flow in pipes, with particular reference to the transition region between the smooth and rough pipe laws. *Journal of the Institution of Civil Engineers* 11, 133–156.
6. Swamee, P. K.; Jain, A. K. (1976): Explicit equations for pipe-flow problems. *Journal of the Hydraulics Division (ASCE)* 102(5), 657–664.
7. Haaland, S. E. (1983): Simple and explicit formulas for the friction factor in turbulent pipe flow. *Journal of Fluids Engineering* 105(1), 89–90.
8. Hooper, W. B. (1981): The two-K method predicts head losses in pipe fittings. *Chemical Engineering* 88(17), 96–100.
9. Shah, R. K.; London, A. L.: *Laminar Flow Forced Convection in Ducts*. Academic Press, 1978. – laminare Widerstände nicht-kreisförmiger Querschnitte (Ellipse).
10. Tanaka, M.; Girard, G.; Davis, R.; Peuto, A.; Bignell, N. (2001): Recommended table for the density of water between 0 °C and 40 °C based on recent experimental reports. *Metrologia* 38, 301–309.
11. Huber, M. L. et al. (2009): New international formulation for the viscosity of H₂O. *Journal of Physical and Chemical Reference Data* 38(2), 101–125. – Quelle der Prüfwerte für die Wasserviskosität (Prüfwerte bitte am Original verifizieren).
12. Bear, J.: *Dynamics of Fluids in Porous Media*. Elsevier, 1972 (Dover-Nachdruck). – Darcy-Gesetz, Kapillarbündelmodell.
13. Nield, D. A.; Bejan, A.: *Convection in Porous Media*. Springer (verschiedene Auflagen). – Darcy-Forchheimer, Gültigkeit.
14. IEC 60534-2-1: *Industrial-process control valves – Part 2-1: Flow capacity – Sizing equations for fluid flow under installed conditions*. – Kv-Definition.

## 13 Offene / experimentell zu bestimmende Parameter

Medienviskosität und -dichte (37 °C) · reale Schlauch-IDs (Toleranz!) und Längen · K-Werte von Verbindern, Splittern, T-Stücken · Drosselkennlinien (Öffnung → Δp(Q)) · Pumpenkennlinie/Verdrängungsvolumen/Schlupf der Stackable Perfusion Pump · Reaktorgeometrie und Kanalmaße · Scaffold-Permeabilität, Porosität, ggf. Forchheimer-Koeffizient · zulässige Drücke (Pumpe, Reaktor, Schlauchverbindungen) · Niveauunterschiede im Aufbau.
