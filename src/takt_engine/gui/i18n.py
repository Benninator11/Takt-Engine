"""Small, dependency-free German/English UI translations for the GTK application."""
from __future__ import annotations

from pathlib import Path
import json
import os


UI_SETTINGS_PATH = Path.home() / ".config" / "takt-engine" / "ui-settings.json"


# German is the source language. Exact entries cover the fixed UI; shorter
# entries also translate changing status strings without touching numeric data.
TRANSLATIONS = {
    "Takt Engine – Raspberry Pi Taktverwaltung": "Takt Engine – Raspberry Pi clock management",
    "Taktprofile, Status und Stabilität für Raspberry Pi 4 / 5": "Clock profiles, status and stability for Raspberry Pi 4 / 5",
    "Systemstatus wird geprüft …": "Checking system status …",
    "↻ Neustart…": "↻ Reboot…",
    "Den Raspberry Pi nach Bestätigung vollständig neu starten": "Fully reboot the Raspberry Pi after confirmation",
    "Neustart wird angefordert…": "Requesting reboot…",
    "Neustart angefordert": "Reboot requested",
    "Überblick": "Overview",
    "Übertakten": "Overclocking",
    "Voreinstellungen": "Presets",
    "Live-Monitor": "Live Monitor",
    "Lüfterkurve": "Fan Curve",
    "Werkzeuge": "Tools",
    "Achtung: Übertakten kann Abstürze, Datenverlust oder Bootprobleme verursachen. Die Profile sind keine Stabilitätsgarantie. Änderungen benötigen einen Neustart.": "Warning: Overclocking can cause crashes, data loss or boot problems. Profiles do not guarantee stability. Changes require a reboot.",
    "Erweiterte App-Einstellbereiche: CPU bis 3.800 MHz und V3D bis 2.000 MHz. Das sind experimentelle Eingabegrenzen, keine offiziell zugesicherten stabilen Taktraten. Die dokumentierten Pi-5-Standardwerte liegen bei 2.400 MHz CPU und 960 MHz V3D. Oberhalb von 2.800/1.000 MHz erscheint vor dem Anwenden eine zusätzliche Warnung. Sehr hohe Werte können ignoriert werden, Abstürze verursachen oder den Start verhindern.": "Extended app input ranges: CPU up to 3,800 MHz and V3D up to 2,000 MHz. These are experimental input limits, not officially guaranteed stable clock rates. The documented Pi 5 defaults are 2,400 MHz CPU and 960 MHz V3D. Above 2,800/1,000 MHz, an additional warning appears before applying. Very high values may be ignored, cause crashes or prevent startup.",
    "CPU-Takt (arm_freq)": "CPU clock (arm_freq)",
    "3D-Grafiktakt / V3D (v3d_freq)": "3D graphics clock / V3D (v3d_freq)",
    "Core-Takt (core_freq)": "Core clock (core_freq)",
    "SoC-Spannungs-Offset / Undervolting (over_voltage_delta)": "SoC voltage offset / undervolting (over_voltage_delta)",
    "Core-Takt: separater core_freq-Regler wird für den Pi 5 nicht angeboten; V3D wird separat geregelt.": "Core clock: a separate core_freq control is not available on the Pi 5; V3D is controlled separately.",
    "Negative Werte senken den vom DVFS berechneten SoC-Spannungswert; das ist kein separater CPU-only-Regler. Zum Ausprobieren nur kleine Schritte von -5000 µV verwenden. Bei Rechenfehlern, Abstürzen oder Bootproblemen auf 0 µV zurückstellen. Positive Werte erhöhen Wärme und Energiebedarf. Die Spannungsregelung bleibt modellabhängig.": "Negative values lower the SoC voltage calculated by DVFS; this is not a CPU-only control. For testing, use only small steps of -5,000 µV. If calculation errors, crashes or boot problems occur, return to 0 µV. Positive values increase heat and power consumption. Voltage control remains model-dependent.",
    "Modell-Standardwerte laden": "Load model defaults",
    "config.txt neu einlesen": "Reload config.txt",
    "Änderungen anwenden…": "Apply changes…",
    "App-Grenzen: {lower}–{upper} {unit}": "App limits: {lower}–{upper} {unit}",
    "Wähle ein Profil aus Standard, Leistung oder Undervolting. Es übernimmt zunächst nur Werte in die Regler; config.txt wird erst nach „Änderungen anwenden“ und deiner Bestätigung geändert.": "Choose a profile from Standard, Performance or Undervolting. It only loads values into the controls; config.txt is changed only after you select “Apply changes” and confirm.",
    "Standard & Alltag": "Standard & everyday",
    "Mehr Leistung": "More performance",
    "Undervolting": "Undervolting",
    "Negative Spannungs-Offsets sind experimentell. Auch kleine Schritte können Rechenfehler oder Abstürze verursachen. Profile einzeln testen und bei Problemen auf 0 µV zurückstellen.": "Negative voltage offsets are experimental. Even small steps can cause calculation errors or crashes. Test profiles one at a time and return to 0 µV if problems occur.",
    "Hinweis: ": "Note: ",
    "Profil in Regler laden": "Load profile into controls",
    "Kein passendes Profil gefunden. Bitte unterstützten Raspberry Pi 4 oder Pi 5 verwenden.": "No matching profile found. Please use a supported Raspberry Pi 4 or Pi 5.",
    "Eigene Profile": "Custom profiles",
    "Eigene Profile werden nur lokal für deinen Benutzer gespeichert und verändern config.txt erst nach dem Anwenden.": "Custom profiles are stored locally for your user only and change config.txt only after you apply them.",
    "Aktuelle Regler als Profil speichern…": "Save current controls as profile…",
    "Profil exportieren…": "Export profile…",
    "Profil importieren…": "Import profile…",
    "Laden": "Load",
    "Löschen": "Delete",
    "Noch keine eigenen Profile gespeichert.": "No custom profiles saved yet.",
    "Name für die aktuelle Reglerauswahl (max. 40 Zeichen):": "Name for the current control selection (max. 40 characters):",
    "z. B. Alltag – kühl": "e.g. Everyday – cool",
    "Zu exportierendes Profil auswählen:": "Select a profile to export:",
    "Live-Telemetrie zeigt den tatsächlich gemessenen Zustand. Werte aus config.txt sind nur Sollwerte; DVFS und Last können den realen Takt verändern.": "Live telemetry shows the actually measured state. Values in config.txt are targets only; DVFS and workload can change the real clock.",
    "Sammle erste Messwerte …": "Collecting initial measurements …",
    "Orange: Temperatur · Hellblau: CPU-Takt · Grün: V3D-Takt · Violett: CPU-Last · Messpunkte alle ca. 3 Sekunden": "Orange: temperature · Light blue: CPU clock · Green: V3D clock · Purple: CPU load · Samples approximately every 3 seconds",
    "Die native Lüfterkurve benötigt einen Raspberry Pi 5 mit einer vorhandenen config.txt. Die vier PWM-Stufen werden direkt von der Pi-Firmware verwaltet.": "The native fan curve requires a Raspberry Pi 5 with an existing config.txt. The four PWM stages are managed directly by the Pi firmware.",
    "Die Raspberry-Pi-5-Firmware unterstützt vier Temperaturstufen. Takt Engine schreibt diese Werte in config.txt; nach dem Neustart regelt die Firmware den Lüfter automatisch – auch wenn die App geschlossen ist.": "Raspberry Pi 5 firmware supports four temperature stages. Takt Engine writes these values to config.txt; after reboot, the firmware controls the fan automatically – even when the app is closed.",
    "Lüfter-Telemetrie wird gelesen …": "Reading fan telemetry …",
    "Lüfterleistung · Stufe auswählen und Balken ziehen": "Fan speed · Select a stage and drag the slider",
    "Stellt die PWM-Leistung der ausgewählten Temperaturstufe ein. Danach die Kurve speichern und den Raspberry Pi neu starten.": "Sets the PWM output for the selected temperature stage. Then save the curve and reboot the Raspberry Pi.",
    "Zielwert Stufe 1: 29 %": "Target stage 1: 29 %",
    "Istwert: PWM/RPM wird gelesen …": "Actual: reading PWM/RPM …",
    "Schutzkurve: Start spätestens bei 50 °C, mindestens 49 % bei 60 °C, 69 % bei 67,5 °C und volle Leistung bei 75 °C. Die Stufen müssen temperaturabhängig aufsteigend bleiben. Die Firmware behält ihre eigene thermische Steuerung und Hysterese.": "Protective curve: start no later than 50 °C, at least 49% at 60 °C, 69% at 67.5 °C and full speed at 75 °C. Stages must increase with temperature. The firmware retains its own thermal control and hysteresis.",
    "Hysterese (°C):": "Hysteresis (°C):",
    "Standardkurve laden": "Load default curve",
    "Firmwarekurve aus config.txt laden": "Load firmware curve from config.txt",
    "Kurve speichern…": "Save curve…",
    "Firmwarekurve wird geladen …": "Loading firmware curve …",
    "Benchmark": "Benchmark",
    "CPU- und Speicherlast mit Live-Temperatur-/Throttling-Prüfung. Der Test erzeugt Last und kann das Gerät erwärmen; keine anderen wichtigen Aufgaben parallel ausführen.": "CPU and memory load with live temperature/throttling checks. The test creates load and can heat up the device; do not run other important tasks at the same time.",
    "Dauer (Sekunden):": "Duration (seconds):",
    "CPU-Threads:": "CPU threads:",
    "Benchmark starten": "Start benchmark",
    "Stoppen": "Stop",
    "Bereit. Für den Start wird stress-ng benötigt.": "Ready. stress-ng is required to start.",
    "Noch keine gespeicherten Benchmarks.": "No saved benchmarks yet.",
    "Status": "Status",
    "Status aktualisieren": "Refresh status",
    "Sicherung zurückspielen…": "Restore backup…",
    "Diagnosebericht exportieren…": "Export diagnostic report…",
    "Diagnose- und Tuning-Werkzeuge. Analysen lesen nur; Änderungen an config.txt werden weiterhin ausschließlich über „Änderungen anwenden…“ und die Sicherheitsbestätigung geschrieben.": "Diagnostic and tuning tools. Analyses are read-only; changes to config.txt are still written only through “Apply changes…” and the safety confirmation.",
    "Config prüfen": "Inspect config",
    "Hardware/Firmware": "Hardware/Firmware",
    "System-Selbsttest": "System self-test",
    "Kühlung und Systemkompatibilität": "Cooling and system compatibility",
    "Kühlungsdaten werden gelesen …": "Reading cooling data …",
    "Nutze „Hardware/Firmware“ für Kernel-, Firmware- und Werkzeugversionen.": "Use “Hardware/Firmware” for kernel, firmware and tool versions.",
    "Geführter Tuning-Assistent": "Guided tuning assistant",
    "Ausgewogen": "Balanced",
    "Kühl und leise": "Cool and quiet",
    "Mehr Leistung": "More performance",
    "Vorschlag berechnen": "Calculate suggestion",
    "Vorschlag in Regler laden": "Load suggestion into controls",
    "Der Assistent wendet keine Änderungen automatisch an.": "The assistant does not apply changes automatically.",
    "Neustart-Verifikation und sichere Rückkehr": "Reboot verification and safe rollback",
    "Noch keine anzuwendenden Werte protokolliert.": "No values pending application have been recorded yet.",
    "Neustart-Verifikation aktualisieren": "Refresh reboot verification",
    "Teststart bestätigen": "Confirm test boot",
    "Sicheres Testprofil: nach dem Neustart automatische Rückkehr, wenn ich nicht binnen 120 Sekunden bestätige": "Safe test profile: automatically roll back after reboot if I do not confirm within 120 seconds",
    "Nur verfügbar, wenn der systemd-Rollback-Timer installiert und aktiviert ist.": "Available only when the systemd rollback timer is installed and enabled.",
    "Optional und standardmäßig aus. Funktioniert nur, wenn Linux und systemd starten: Der Timer wird 120 Sekunden nach dem Boot ausgelöst. Wenn der Rechner vor Linux hängen bleibt, kann dieser Mechanismus nicht helfen.": "Optional and disabled by default. Works only if Linux and systemd start: the timer is triggered 120 seconds after boot. This mechanism cannot help if the computer hangs before Linux starts.",
    "Tuning-Verlauf": "Tuning history",
    "Verlauf aktualisieren": "Refresh history",
    "Der Raspberry Pi konnte nicht neu gestartet werden.": "The Raspberry Pi could not be rebooted.",
    "Bitte stoppe zuerst den laufenden Benchmark und warte, bis er beendet ist.": "Please stop the running benchmark first and wait until it has finished.",
    "Takt Engine fordert einen vollständigen Neustart des Raspberry Pi an. Offene Programme können beendet werden.": "Takt Engine is requesting a full reboot of the Raspberry Pi. Open programs may be closed.",
    "Achtung: Deine aktuellen Regleränderungen wurden noch nicht angewendet. Sie werden durch den Neustart nicht in config.txt geschrieben.": "Warning: Your current control changes have not been applied. They will not be written to config.txt by rebooting.",
    "Ein sicheres Testprofil wartet auf Prüfung. Bestätige es nach dem Neustart innerhalb von 120 Sekunden, sonst wird die vorherige Konfiguration zurückgespielt.": "A safe test profile is waiting for verification. Confirm it within 120 seconds after reboot or the previous configuration will be restored.",
    "Raspberry Pi jetzt neu starten?": "Reboot the Raspberry Pi now?",
    "Abbrechen": "Cancel",
    "Jetzt neu starten": "Reboot now",
    "Der Systemneustart wurde angenommen. Takt Engine wird beim Herunterfahren beendet.": "The system reboot request was accepted. Takt Engine will close during shutdown.",
    "Systemneustart wird angefordert. Bitte warte auf die Systemautorisierung.": "Requesting system reboot. Please wait for system authorization.",
    "Systemneustart fehlgeschlagen.": "System reboot failed.",
    "Systemstatus wird geprüft": "Checking system status",
    "Die native Lüfterkurve ist nur auf einem erkannten Raspberry Pi 5 mit config.txt verfügbar.": "The native fan curve is available only on a detected Raspberry Pi 5 with config.txt.",
    "Bitte stoppe zuerst den laufenden Benchmark.": "Please stop the running benchmark first.",
    "Istwert: PWM/RPM nicht verfügbar": "Actual: PWM/RPM unavailable",
    "Benchmark konnte nicht ausgeführt werden.": "Benchmark could not be run.",
    "Benchmark wird gestartet …": "Starting benchmark …",
    "Stopp angefordert …": "Stop requested …",
    "Startet …": "Starting …",
    "Bestanden": "Passed",
    "Nicht bestanden": "Failed",
    "Name": "Name",
    "Hardware": "Hardware",
    "Modell": "Model",
    "Raspberry Pi erkannt": "Raspberry Pi detected",
    "Betriebssystem": "Operating system",
    "Boot-Konfiguration": "Boot configuration",
    "Live-Telemetrie": "Live telemetry",
    "SoC-Temperatur": "SoC temperature",
    "CPU-Takt momentan": "Current CPU clock",
    "V3D-Takt momentan": "Current V3D clock",
    "CPU-Auslastung": "CPU utilization",
    "Lüfterdrehzahl": "Fan speed",
    "Kühlungsstatus": "Cooling status",
    "get_throttled": "get_throttled",
    "Aktive Unterspannung/Drosselung": "Active undervoltage/throttling",
    "Historische Flags": "Historical flags",
    "Hinweis": "Note",
    "In config.txt gespeicherter Takt-Engine-Block": "Takt Engine block stored in config.txt",
    "Nicht verfügbar": "Unavailable",
    "Nicht gefunden": "Not found",
    "Ja": "Yes",
    "Nein": "No",
    "Nein / nicht erkannt": "No / not detected",
    "nicht aktiv erkannt": "not detected as active",
    "aktiv": "active",
    "Drehzahl nicht verfügbar": "Fan speed unavailable",
    "Lüfterdrehzahl nicht verfügbar": "Fan speed unavailable",
    "keine Cooling-Device-Statuswerte verfügbar": "no cooling-device status values available",
    "Noch kein Takt-Engine-Block eingetragen.": "No Takt Engine block has been added yet.",
    "Lesefehler": "Read error",
    "Profil exportiert:": "Profile exported:",
    "Diagnosebericht gespeichert:": "Diagnostic report saved:",
    "Vorherige Konfiguration gesichert unter:": "Previous configuration saved at:",
    "Bitte neu starten.": "Please reboot.",
    "Temperatur:": "Temperature:",
    "CPU Ist:": "CPU actual:",
    "Soll:": "Target:",
    "V3D Ist:": "V3D actual:",
    "CPU-Auslastung:": "CPU utilization:",
    "Lüfter:": "Fan:",
    "Aktuelle Lüfterdrehzahl:": "Current fan speed:",
    "SoC:": "SoC:",
    "Drosselung:": "Throttling:",
    "Unterspannung:": "Undervoltage:",
    "nicht aktiv": "inactive",
    "Bitte": "Please",
    "Stufe": "Stage",
    "Zielwert": "Target",
    "Istwert": "Actual",
    "Firmwarekurve konnte nicht gelesen werden:": "Could not read firmware curve:",
    "config.txt kann nicht gelesen werden:": "Could not read config.txt:",
    "config.txt-Werte konnten nicht gelesen werden:": "Could not read config.txt values:",
    "Benchmark-Historie konnte nicht gelesen werden:": "Could not read benchmark history:",
    "Keine Änderungen notwendig: config.txt enthält bereits genau diese Werte.": "No changes needed: config.txt already contains exactly these values.",
    "Prüfe die tatsächlichen Zeilenänderungen. Grün bedeutet neu/hinzugefügt, Orange bedeutet entfernt. Andere Zeilen sollten erhalten bleiben. Noch wurde nichts geschrieben.": "Review the actual line changes. Green means new/added, orange means removed. Other lines should remain unchanged. Nothing has been written yet.",
    "Teststart bestätigt.": "Test boot confirmed.",
    "Automatische Rückkehr wurde deaktiviert.": "Automatic rollback has been disabled.",
}

# These fragments are also used inside values that contain live measurements,
# filenames, exception messages or user-created profile names.
PHRASES = sorted(TRANSLATIONS.items(), key=lambda item: len(item[0]), reverse=True)
REVERSE_TRANSLATIONS = sorted(
    ((english, german) for german, english in TRANSLATIONS.items() if english != german),
    key=lambda item: len(item[0]),
    reverse=True,
)


def translate_text(value: str, language: str = "de") -> str:
    """Translate a UI string in either direction while preserving dynamic values."""
    if not isinstance(value, str) or not value:
        return value

    # Normalize English text back to the German source first. This makes the
    # periodic GTK refresh idempotent and lets the same function switch both ways.
    normalized = value
    for english, german in REVERSE_TRANSLATIONS:
        normalized = normalized.replace(english, german)

    if language != "en":
        return normalized

    exact = TRANSLATIONS.get(normalized)
    if exact is not None:
        return exact

    translated = normalized
    for german, english in PHRASES:
        if german and german in translated:
            translated = translated.replace(german, english)
    return translated


def load_ui_language() -> str:
    """Load the saved UI language, defaulting to German for existing installs."""
    try:
        settings = json.loads(UI_SETTINGS_PATH.read_text(encoding="utf-8"))
        language = settings.get("language") if isinstance(settings, dict) else None
        return language if language in {"de", "en"} else "de"
    except (OSError, ValueError, TypeError):
        return "de"


def save_ui_language(language: str) -> None:
    """Persist the UI language without changing any tuning/configuration files."""
    if language not in {"de", "en"}:
        raise ValueError("Unsupported UI language")
    UI_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = UI_SETTINGS_PATH.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"language": language}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, UI_SETTINGS_PATH)
