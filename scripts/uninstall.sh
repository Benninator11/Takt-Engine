#!/usr/bin/env bash
set -euo pipefail
if [[ "$(id -u)" -ne 0 ]]; then
  echo "Bitte mit sudo starten: sudo bash scripts/uninstall.sh" >&2
  exit 1
fi
if [[ -f /var/lib/takt-engine/rollback/pending.json ]]; then
  echo "Ein sicheres Testprofil wartet noch auf Bestätigung. Bestätige es oder lasse den Rollback nach dem Neustart abschließen, bevor du deinstallierst." >&2
  exit 1
fi
if command -v systemctl >/dev/null 2>&1; then
  systemctl disable --now takt-engine-rollback.timer >/dev/null 2>&1 || true
  systemctl disable --now takt-engine-fan.service >/dev/null 2>&1 || true
  systemctl daemon-reload || true
fi
rm -f /etc/systemd/system/takt-engine-rollback.timer /etc/systemd/system/takt-engine-rollback.service
rm -f /etc/systemd/system/takt-engine-fan.service
rm -f /usr/local/libexec/takt-engine-rollback-check.py /usr/local/libexec/takt-engine-fan-control.py
rm -rf /run/takt-engine
rm -rf /var/lib/takt-engine/rollback
rm -f /usr/local/bin/takt-engine /usr/share/applications/takt-engine.desktop
TARGET_USER="${SUDO_USER:-}"
if [[ -n "$TARGET_USER" && "$TARGET_USER" != "root" ]] && getent passwd "$TARGET_USER" >/dev/null; then
  TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
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
  rm -f "$DESKTOP_DIR/Takt-Engine.desktop"
fi
rm -rf /opt/takt-engine
echo "Takt Engine wurde entfernt. Persönliche Backups unter ~/.config/takt-engine/backups und das Lüfterprofil unter /etc/takt-engine bleiben erhalten."
