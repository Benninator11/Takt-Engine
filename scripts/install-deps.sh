#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Bitte mit sudo starten: sudo bash scripts/install-deps.sh" >&2
  exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
INSTALL_DIR="/opt/takt-engine"

if ! command -v apt-get >/dev/null 2>&1; then
  echo "Dieses Installationsskript ist für Raspberry Pi OS/Debian mit apt gedacht." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3 python3-gi gir1.2-gtk-3.0 stress-ng pkexec polkitd xdg-user-dirs

install -d -m 0755 "$INSTALL_DIR"
rm -rf "$INSTALL_DIR/src" "$INSTALL_DIR/data" "$INSTALL_DIR/scripts" "$INSTALL_DIR/share"
cp -a "$PROJECT_DIR/src" "$INSTALL_DIR/"
cp -a "$PROJECT_DIR/data" "$INSTALL_DIR/"
cp -a "$PROJECT_DIR/scripts" "$INSTALL_DIR/"
install -d -m 0755 "$INSTALL_DIR/share"
install -m 0644 "$PROJECT_DIR/data/takt-engine.svg" "$INSTALL_DIR/share/takt-engine.svg"
install -m 0644 "$PROJECT_DIR/README.md" "$INSTALL_DIR/README.md"
install -m 0644 "$PROJECT_DIR/LICENSE" "$INSTALL_DIR/LICENSE"

# Persistent Raspberry Pi 5 fan controller and its systemd unit.
install -m 0755 "$PROJECT_DIR/scripts/fan-control.py" /usr/local/libexec/takt-engine-fan-control.py
install -m 0644 "$PROJECT_DIR/scripts/takt-engine-fan.service" /etc/systemd/system/takt-engine-fan.service
install -d -m 0755 /etc/takt-engine /var/lib/takt-engine/fan-backups /run/takt-engine
# Root-owned post-boot rollback helper and its timer are optional safety net
# for an explicitly armed trial. They do nothing unless a pending marker exists.
install -d -m 0755 /usr/local/libexec
install -m 0755 "$PROJECT_DIR/scripts/rollback-check.py" /usr/local/libexec/takt-engine-rollback-check.py
install -m 0644 "$PROJECT_DIR/scripts/takt-engine-rollback.service" /etc/systemd/system/takt-engine-rollback.service
install -m 0644 "$PROJECT_DIR/scripts/takt-engine-rollback.timer" /etc/systemd/system/takt-engine-rollback.timer
if command -v systemctl >/dev/null 2>&1; then
  systemctl daemon-reload
  if ! systemctl enable --now takt-engine-rollback.timer; then
    echo "WARNUNG: systemd-Rollback-Timer konnte nicht aktiviert werden. Sichere Testprofile sind dann nicht nutzbar." >&2
  fi
fi
# Files executed by pkexec must not remain writable by the desktop user.
chown -R root:root "$INSTALL_DIR"
find "$INSTALL_DIR" -type d -exec chmod 0755 {} +
find "$INSTALL_DIR" -type f -exec chmod 0644 {} +

cat > /usr/local/bin/takt-engine <<'LAUNCHER'
#!/usr/bin/env sh
export TAKT_ENGINE_HOME="/opt/takt-engine"
export PYTHONPATH="/opt/takt-engine/src${PYTHONPATH:+:$PYTHONPATH}"
exec /usr/bin/python3 -m takt_engine.gui.main "$@"
LAUNCHER
chmod 0755 /usr/local/bin/takt-engine

cat > /usr/share/applications/takt-engine.desktop <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=Takt Engine
Comment=Raspberry Pi Taktprofile, Status und Stabilitätstest
Exec=/usr/local/bin/takt-engine
Icon=/opt/takt-engine/share/takt-engine.svg
Terminal=false
Categories=System;Settings;Utility;
StartupNotify=true
DESKTOP
chmod 0644 /usr/share/applications/takt-engine.desktop

# Also install a desktop shortcut for the user who invoked sudo.
TARGET_USER="${SUDO_USER:-}"
if [[ -n "$TARGET_USER" && "$TARGET_USER" != "root" ]] && getent passwd "$TARGET_USER" >/dev/null; then
  TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
  TARGET_GROUP="$(id -gn "$TARGET_USER")"
  DESKTOP_DIR=""
  if command -v xdg-user-dir >/dev/null 2>&1; then
    DESKTOP_DIR="$(sudo -u "$TARGET_USER" env HOME="$TARGET_HOME" xdg-user-dir DESKTOP 2>/dev/null || true)"
  fi
  case "$DESKTOP_DIR" in
    "$TARGET_HOME"/*) ;;
    *)
      if [[ -d "$TARGET_HOME/Schreibtisch" ]]; then
        DESKTOP_DIR="$TARGET_HOME/Schreibtisch"
      else
        DESKTOP_DIR="$TARGET_HOME/Desktop"
      fi
      ;;
  esac
  install -d -m 0755 -o "$TARGET_USER" -g "$TARGET_GROUP" "$DESKTOP_DIR"
  install -m 0755 -o "$TARGET_USER" -g "$TARGET_GROUP" \
    /usr/share/applications/takt-engine.desktop "$DESKTOP_DIR/Takt-Engine.desktop"
  if command -v gio >/dev/null 2>&1; then
    sudo -u "$TARGET_USER" env HOME="$TARGET_HOME" gio set \
      "$DESKTOP_DIR/Takt-Engine.desktop" metadata::trusted true >/dev/null 2>&1 || true
  fi
  printf 'Desktop-Verknüpfung erstellt: %s\n' "$DESKTOP_DIR/Takt-Engine.desktop"
else
  printf 'Keine Desktop-Verknüpfung angelegt (SUDO_USER nicht erkannt). Das Anwendungsmenü bleibt verfügbar.\n'
fi

printf '\nInstallation abgeschlossen.\n'
printf 'Start im Terminal: takt-engine\n'
printf 'Oder über Anwendungsmenü/Desktop: Takt Engine\n'
printf 'Tests aus dem Quellordner: PYTHONPATH=src python3 -m unittest discover -s tests -v\n'
printf '\nZum Schreiben von config.txt und zum Ändern der Lüfterkurve wird beim Anwenden eine Rechteabfrage geöffnet.\n'
printf 'Eine gespeicherte Pi-5-Lüfterkurve wird als systemd-Dienst automatisch bei jedem Start geladen.\n'
