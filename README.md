# Takt Engine

**Version 1.4.0** – GTK3-Desktopanwendung für Raspberry Pi OS mit dunklem Anthrazit- und warmem Claude-Orange-Design. Die halbtransparente „Benninator“-Signatur, die kurze Orange-Pulsanimation beim Anwenden und zusätzliche dezente Übergänge bleiben erhalten.

> **Sicherheit:** Übertakten und Undervolting können Instabilität, Rechenfehler, Datenverlust oder Bootprobleme verursachen. App-Schutzgrenzen sind keine Garantie für Stabilität oder Lebensdauer. Sichere wichtige Daten, verwende ausreichende Kühlung und ein geeignetes Netzteil. Die manuell auswählbaren Pi-5-App-Eingabegrenzen sind in 1.2.1 auf 3,8 GHz CPU und 2,0 GHz V3D erweitert. Das sind ausdrücklich experimentelle Eingabegrenzen, keine vom Hersteller zugesicherten stabilen Takte. Werte oberhalb von 2,8 GHz CPU oder 1,0 GHz V3D benötigen eine zusätzliche Warnbestätigung. Raspberry Pi nennt als Pi-5-Standardwerte 2,4 GHz CPU und 960 MHz V3D; sehr hohe Werte können ignoriert werden, Instabilität verursachen oder den Start verhindern.

## Änderungen in 1.4.0

- Die Lüfterkurve kann jetzt aus **4 bis 10 Stufen** bestehen. Temperatur und Lüfterleistung sind je Stufe einstellbar; eine Kurvengrafik zeigt den Verlauf.
- Die Kurve wird dauerhaft in `/etc/takt-engine/fan-curve.json` gespeichert. Beim ersten Speichern wird der Systemdienst `takt-engine-fan.service` aktiviert; er lädt das Profil auch nach jedem Neustart.
- Ein Live-Regler kann die Lüfterleistung für 5 bis 300 Sekunden vorübergehend erhöhen. Er kann die aktuelle temperaturabhängige Mindestleistung nicht unterschreiten; nach Ablauf oder Neustart ist wieder die gespeicherte Kurve aktiv.
- Sicherheitsverhalten: mindestens 29 % bei 50 °C, 49 % bei 60 °C, 69 % bei 67,5 °C und 95 % bei 75 °C, volle Leistung ab 80 °C und volle Leistung, falls die Temperatur nicht gelesen werden kann.
- Animationen: rotierende Lüftergrafik, animiert einblendende Kurvenstufen, Live-Leistungsbalken, Kurvendiagramm und animierte Rückmeldung beim Speichern.
- Die Steuerung verwendet die Linux-`pwm-fan`-Schnittstelle des kompatiblen Raspberry-Pi-5-Lüfters. Die native Firmware-Konfiguration unterstützt weiterhin nur vier `fan_tempN`-Stufen; ältere Vier-Stufen-Kurven können importiert werden.
## Änderungen in 1.3.0

- Neuer Reiter **„Lüfterkurve“** für den Raspberry Pi 5 mit kompatiblem Firmware-Lüfter am offiziellen Lüfteranschluss.
- Vier Temperaturstufen mit einstellbarer Lüfterleistung und gemeinsamer Hysterese. Die Kurve wird von der Raspberry-Pi-Firmware geregelt und funktioniert nach dem Neustart auch ohne laufende Takt Engine.
- Sicherheitsgrenzen: Lüfterstart spätestens bei 55 °C, mindestens 2,5 °C Abstand zwischen Stufen, steigende Lüfterleistung und mindestens 95 % in der letzten Stufe bei höchstens 75 °C.
- Vor dem Schreiben wird `config.txt` gesichert. Nur der eigene Takt-Engine-Lüfterblock wird ersetzt; andere Konfigurationseinträge bleiben erhalten.
- Die Funktion ist auf den Raspberry Pi 5 begrenzt. Sie steuert keine beliebigen GPIO-, USB- oder externen Lüfter. Die Drehzahl wird – sofern der Treiber sie bereitstellt – weiterhin im Live-Monitor angezeigt.

## Änderungen in 1.2.4

- Neue Schaltfläche „↻ Neustart…“ oben in der Kopfzeile. Sie startet nach einer deutlichen Bestätigungsabfrage den gesamten Raspberry Pi neu.
- Der Neustart nutzt `systemctl reboot`; für normale Desktop-Benutzer wird nur diese Aktion mit `pkexec` autorisiert. Die App läuft nicht als Root.
- Vor dem Neustart wird ein laufender Benchmark blockiert. Ungespeicherte Regleränderungen und ein gegebenenfalls aktives Testprofil werden im Bestätigungsdialog ausdrücklich erwähnt.
- Bei fehlender Systemautorisierung oder einem Systemfehler bleibt Takt Engine geöffnet und zeigt eine Fehlermeldung. Der Neustart läuft nicht über eine Shell.

## Änderungen in 1.2.3

- Die Legende über den Reglern wurde entfernt, damit der Übertakten-Tab aufgeräumter aussieht.
- CPU- und V3D-Regler des Pi 5 verwenden jetzt einen stufenlosen Farbverlauf: Grün geht über Gelb zu Orange und anschließend zu Rot.
- Die Reglerfarbe wird bei Wertänderungen über eine kurze GTK-Animation weich an den Zielwert angenähert; Reglerknopf, gefüllte Leiste und MHz-Anzeige ändern sich zusammen.
- Der Farbverlauf wird auch beim Laden von Profilen und beim Einlesen von `config.txt` aktualisiert. Die farbige Anzeige bleibt eine visuelle Risikohilfe und keine Stabilitätsgarantie.
- Das Projekt verwendet weiterhin GTK3/PyGObject; der bestehende Anthrazit-/Orange-Stil und alle übrigen Funktionen bleiben erhalten.

## Änderungen in 1.2.2

- Dynamische Farbzonen für Pi-5-CPU- und V3D-Regler: Grün/Blau im konservativen Empfehlungsbereich, Gelb bei erhöhtem Risiko, Rot im Extrembereich.
- Reglerknopf, gefüllte Reglerstrecke und MHz-Anzeige wechseln die Farbe live beim Ziehen sowie beim Einlesen von `config.txt` oder Laden eines Profils.
- Legende direkt im Übertakten-Tab zeigt die Schwellwerte: CPU 2.800/3.100 MHz und V3D 1.000/1.500 MHz; die Obergrenzen bleiben 3.800/2.000 MHz.
- Das Projekt verwendet bereits GTK3/PyGObject statt Standard-Tkinter. Deshalb bleibt die vorhandene GTK-Oberfläche mit Claude-inspiriertem Anthrazit-/Orange-Design erhalten, statt ohne funktionalen Vorteil auf CustomTkinter umzubauen.

## Änderungen in 1.2.1

- Pi-5-Reglerbereich erweitert: CPU bis 3.800 MHz und V3D bis 2.000 MHz.
- Zusätzliche Risikoabfrage bei Einstellungen oberhalb von 2.800 MHz CPU bzw. 1.000 MHz V3D.
- Config-Inspector markiert Werte im experimentellen Bereich.
- Der Tuning-Assistent empfiehlt weiterhin nur bis zu den konservativen Schwellenwerten.

## Neue Funktionen in 1.2.0

1. **Config-Inspector:** Prüft erkennbare Syntaxfehler, doppelte Taktzuweisungen im selben Abschnitt, Werte außerhalb der App-Grenzen, lange Zeilen und `include=`-Referenzen. Zeigt den zuletzt erkannten passenden Taktwert. Include-Dateien werden nicht rekursiv eingelesen; das Tool ist keine vollständige Firmware-Validierung.
2. **Tuning-Verlauf:** Protokolliert erfolgreiche Änderungen mit Zeit, Modell, alten/neuen verwalteten Taktwerten, Temperatur-Momentaufnahme und Backup-Dateiname. Speichert höchstens 200 Einträge und exportiert keine vollständigen `config.txt`-Inhalte.
3. **Neustart-Verifikation:** Speichert Sollwerte und Boot-ID beim Anwenden. Nach einem Neustart vergleicht es die Datei und soweit durch `vcgencmd get_config int` auslesbar die Firmwarewerte. Nicht verfügbare Firmwarewerte werden als unbekannt statt als Fehler klassifiziert.
4. **Optionales sicheres Testprofil:** Wenn im Tab „Werkzeuge“ ausdrücklich aktiviert, legt der privilegierte Schreiber eine root-eigene Sicherung an. Der systemd-Timer prüft 120 Sekunden nach dem nächsten Boot. Wird der Teststart nicht bestätigt, stellt er die vorherige `config.txt` wieder her. Der Timer ist inaktiv, solange kein Testprofil aussteht. **Er hilft nur, wenn Linux und systemd starten; ein Firmware-/Bootfehler vor Linux kann damit nicht repariert werden.**
5. **Geführter Tuning-Assistent:** Kühl/leise, ausgewogen oder mehr Leistung. Er berücksichtigt Temperatur, Unterspannung, Throttling und die modellbezogenen Grenzen. Er wendet nichts automatisch an; Vorschläge müssen separat in die Regler geladen und bestätigt werden.
6. **Kühlungs-Dashboard:** Verlaufsdiagramm für SoC-Temperatur, CPU-Takt, V3D-Takt, CPU-Auslastung und – falls Linux es bereitstellt – Lüfter-RPM. Das Statusfeld zeigt verfügbare Cooling-Device-Zustände.
7. **Hardware-/Firmware-Kompatibilität:** Modell, Hardware-Revision (wenn lesbar), Betriebssystem, Kernel, Architektur, Python, Firmware-Information und Verfügbarkeit von `vcgencmd`, `stress-ng` und `pkexec`.
8. **Profil-Bibliothek mit JSON-Import/-Export:** Eigene Profile können exportiert und wieder importiert werden. Modell, Schema und Takt-/Offset-Grenzen werden vor dem Speichern geprüft; Importieren ändert `config.txt` nicht.
9. **Ein-Klick-Systemdiagnose:** Prüft Python, GTK/PyGObject, erkannte Hardware, Lesbarkeit der Boot-Konfiguration, wichtige Werkzeuge und Rollback-Timer. Es schreibt nichts und erzeugt keine CPU-Last.
10. **Bedienung/Animationen:** Zusätzlich zu den bisherigen Orange- und Tabanimationen zeigt der Live-Monitor Lüfterwerte, der Benchmark pulsiert während der Messung, und Diagnose-/Profilfunktionen sind unter „Werkzeuge“ bzw. „Voreinstellungen“ gebündelt.

Aus Version 1.1.0 bleiben erhalten: Live-Monitoring, Benchmark-Historie, Vorschau des Konfigurations-Diffs, eigene Profile, Diagnoseexport, Sicherheitsbanner, Backups/Wiederherstellung, Desktop-Verknüpfung und zehn eingebaute Profile.

## Installation auf Raspberry Pi OS
Die erweiterte Lüftersteuerung benötigt einen Raspberry Pi 5 mit kompatiblem Lüfter am offiziellen PWM-Anschluss. Installiere das aktualisierte Projekt mit dem Installationsskript neu, bevor du die Lüfterkurve in der App speicherst. Der Systemdienst wird erst beim ersten Speichern der Kurve aktiviert.


1. Den Projektordner auf dem Pi entpacken.
2. Im Terminal in den Ordner `Takt-Engine` wechseln.
3. Installationsskript ausführen:

   ```bash
   sudo bash scripts/install-deps.sh
   ```

4. Danach im Anwendungsmenü oder vom Desktop **Takt Engine** öffnen. Terminalstart:

   ```bash
   takt-engine
   ```

Der Installer richtet GTK3/PyGObject, `stress-ng`, `pkexec`, `polkitd` und `xdg-user-dirs` ein. Er installiert die App nach `/opt/takt-engine`, den Starter nach `/usr/local/bin/takt-engine` und die Desktop-Datei. Er installiert außerdem den root-eigenen Rollback-Helper und aktiviert den systemd-Timer; ohne ein explizit aktiviertes Testprofil nimmt dieser keine Änderung vor.

### Voraussetzungen

- Raspberry Pi OS / Debian mit `apt`, systemd und GTK3.
- Unterstützte Hardware: Raspberry Pi 4 oder Raspberry Pi 5.
- `vcgencmd` für volle Telemetrie und `stress-ng` für Benchmarks.
- Für Änderungen an der Boot-Konfiguration eine funktionierende PolicyKit-Abfrage (`pkexec`).

## Benutzerdateien

- Eigene Profile: `~/.config/takt-engine/profiles.json`
- Neustart-/Testprofilstatus: `~/.config/takt-engine/reboot-state.json`
- Zeitgestempelte Sicherungen: `~/.config/takt-engine/backups/`
- Benchmark-Historie: `~/.local/share/takt-engine/benchmark-history.json` (max. 50 Läufe)
- Tuning-Verlauf: `~/.local/share/takt-engine/tuning-history.json` (max. 200 Einträge)
- Profil-Importdateien: JSON-Schema `takt-engine-profile`, Version 1

JSON-Nutzerdateien werden atomar geschrieben. Persönliche Profile, Backups und Verläufe werden bei der Deinstallation nicht automatisch gelöscht.

## Tests und technische Prüfung

Im Projektordner:

```bash
bash scripts/test.sh
```

Das Skript führt `unittest`-Tests, Python-Compile-/Syntaxprüfung sowie Shell-Syntaxprüfung durch. Es prüft auch die Rollback-Logik isoliert mit temporären Dateien. Die Tests brauchen weder GTK noch echte Pi-Hardware.

Alternativ:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m compileall -q src tests
bash -n scripts/install-deps.sh scripts/uninstall.sh
python3 -m py_compile scripts/rollback-check.py
```

## Takt-Synchronisierung und Schutzgrenzen

- Die Regler lesen `arm_freq`, `v3d_freq`, `core_freq` (nur Pi 4) und `over_voltage_delta` aus der passenden `config.txt`; Änderungen werden regelmäßig erkannt.
- Die Regler stellen gespeicherte Sollwerte dar. Der gemessene Ist-Takt kann sich durch DVFS, Temperatur und Last unterscheiden.
- Die App verwaltet nur `arm_freq`, `v3d_freq`, `core_freq` (Pi 4) und `over_voltage_delta`; `force_turbo` und SDRAM-Übertaktung werden nicht gesetzt.
- Pi-5-Eingabegrenzen in Version 1.2.1 und 1.2.2: CPU maximal 3.800 MHz und V3D maximal 2.000 MHz. Dies sind experimentelle App-Obergrenzen, keine bestätigten Betriebsgrenzen der Hardware oder Firmware.
- Konservative Schwellen für Empfehlungen: CPU 2.800 MHz und V3D 1.000 MHz. Darüber zeigt die App eine zusätzliche Bestätigungswarnung; der Tuning-Assistent schlägt solche Werte nicht automatisch vor. Der stufenlose Farbverlauf der Regler ist nur eine visuelle Risikohilfe, keine Stabilitätsgarantie. Die Farbe wird ohne sprunghafte Zonenwechsel von Grün über Gelb und Orange nach Rot interpoliert und kurz weich animiert.
- Raspberry-Pi-Standardwerte laut Dokumentation: CPU 2.400 MHz und V3D 960 MHz. Nichtstandardwerte können zu Instabilität oder Startproblemen führen.
- `over_voltage_delta` wirkt auf den SoC-/DVFS-Spannungswert und ist kein unabhängiger CPU-only-Regler. Undervolting kann Rechenfehler und Abstürze verursachen.
- Der Benchmark bricht bei 80 °C ab. Ein bestandener kurzer Test garantiert keine Langzeitstabilität.
- Der Config-Inspector zeigt auch auffällige Werte aus manuellen Änderungen, aber die Anwendung schreibt nur über den regulären, bestätigungspflichtigen Apply-Weg.

## Sicheres Testprofil – genaue Einschränkungen

- Standardmäßig **deaktiviert**. Vor dem Anwenden im Tab „Werkzeuge“ aktivieren.
- Änderungen werden weiterhin mit Backup und Sicherheitsdialog geschrieben.
- Der Helper speichert die vorherige vollständige `config.txt` root-eigen in `/var/lib/takt-engine/rollback/` und markiert die Boot-ID, in der das Profil angewendet wurde.
- Beim selben Boot wird nicht zurückgerollt. Beim nächsten Boot löst der systemd-Timer nach 120 Sekunden aus; wenn die Anwendung nicht bestätigt hat, wird die gesicherte Datei atomar zurückgespielt.
- Wird die Anwendung nach dem Neustart gestartet, fragt sie nach Bestätigung. Alternativ kann unter „Werkzeuge“ bestätigt werden.
- Wenn `config.txt` zwischenzeitlich manuell geändert wurde, bestätigt die App nicht automatisch. Weitere Konfigurationsänderungen über Takt Engine sind gesperrt, solange ein Testprofil auf Bestätigung wartet.
- **Kein echter Firmware-Bootloop-Schutz:** Wenn der Pi nicht bis zu Linux/systemd bootet, kann dieser Timer nicht starten. In diesem Fall braucht es eine manuelle Wiederherstellung über einen anderen Boot-/Recovery-Weg.

## Desktop-Verknüpfung und Entfernen

Der Installer legt `Takt-Engine.desktop` auf dem Desktop des Benutzers an, der das Skript per `sudo` aufgerufen hat, und registriert Takt Engine im Anwendungsmenü.

Zum Entfernen:

```bash
sudo bash scripts/uninstall.sh
```

Wenn ein Testprofil noch auf Bestätigung wartet, bricht der Installer vorsichtshalber ab. Bestätige oder lasse die Rückkehr zuerst abschließen.

## Lizenz

MIT. Siehe `LICENSE`.
