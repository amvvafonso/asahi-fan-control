#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
    echo "Executa com: sudo ./install.sh"
    exit 1
fi

SOURCE_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
INSTALL_DIR=/opt/asahi-fan-control
CONFIG_FILE=/etc/asahi-fan-control.json
MODULE_CONF=/etc/modprobe.d/asahi-fan-control.conf

echo "A instalar Asahi Fan Control..."
install -d -m 0755 "$INSTALL_DIR" "$INSTALL_DIR/web"
install -m 0755 "$SOURCE_DIR/asahi_fan_control.py" "$INSTALL_DIR/asahi_fan_control.py"
install -m 0644 "$SOURCE_DIR/README.md" "$INSTALL_DIR/README.md"
install -m 0644 "$SOURCE_DIR/web/index.html" "$INSTALL_DIR/web/index.html"
install -m 0644 "$SOURCE_DIR/web/style.css" "$INSTALL_DIR/web/style.css"
install -m 0644 "$SOURCE_DIR/web/app.js" "$INSTALL_DIR/web/app.js"
if [[ ! -e "$CONFIG_FILE" ]]; then
    install -m 0644 "$SOURCE_DIR/config.json" "$CONFIG_FILE"
fi
install -m 0644 "$SOURCE_DIR/asahi-fan-control.service" /etc/systemd/system/asahi-fan-control.service
install -m 0644 "$SOURCE_DIR/asahi-fan-control.desktop" /usr/share/applications/asahi-fan-control.desktop

PARAM=fan_control
if modinfo -p macsmc-hwmon 2>/dev/null | grep -q '^melt_my_mac:'; then
    PARAM=melt_my_mac
fi
printf 'options macsmc-hwmon %s=1\n' "$PARAM" >"$MODULE_CONF"

REBOOT_REQUIRED=0
if lsmod | awk '{print $1}' | grep -qx 'macsmc_hwmon'; then
    systemctl stop asahi-fan-control.service 2>/dev/null || true
    if modprobe -r macsmc_hwmon 2>/dev/null; then
        modprobe macsmc-hwmon "$PARAM=1"
    else
        REBOOT_REQUIRED=1
    fi
fi

if ! python3 "$INSTALL_DIR/asahi_fan_control.py" --config "$CONFIG_FILE" --check >/dev/null 2>&1; then
    REBOOT_REQUIRED=1
    # Fedora Asahi may load macsmc-hwmon from the initramfs, before the
    # installed modprobe.d file is visible. The kernel command line works for
    # both built-in and loadable variants of the driver.
    if command -v grubby >/dev/null 2>&1; then
        grubby --update-kernel=ALL --args="macsmc_hwmon.${PARAM}=1"
    else
        echo "Acrescenta ao arranque do kernel: macsmc_hwmon.${PARAM}=1"
    fi
fi

systemctl daemon-reload
systemctl enable --now asahi-fan-control.service

echo
echo "Instalação concluída."
if [[ $REBOOT_REQUIRED -eq 1 ]]; then
    echo "É necessário reiniciar para o kernel disponibilizar o controlo das ventoinhas."
fi
echo "Depois abre: http://127.0.0.1:8799"
echo "Também ficou disponível no menu de aplicações como Asahi Fan Control."
echo "Estado: systemctl status asahi-fan-control"
