#!/usr/bin/env bash
set -euo pipefail
if [[ ${EUID} -ne 0 ]]; then echo "Executa com: sudo ./uninstall.sh"; exit 1; fi
systemctl disable --now asahi-fan-control.service 2>/dev/null || true
rm -f /etc/systemd/system/asahi-fan-control.service
rm -f /usr/share/applications/asahi-fan-control.desktop
rm -f /etc/modprobe.d/asahi-fan-control.conf
rm -rf /opt/asahi-fan-control
systemctl daemon-reload
echo "Asahi Fan Control removido. A configuração /etc/asahi-fan-control.json foi preservada."
