# Asahi Fan Control

Local fan controller for Apple Silicon MacBook Pro running Asahi Linux. It talks directly to the `hwmon` interface exposed by the `macsmc-hwmon` driver, with no external libraries.

## Safety

- On the automatic curve, Apple's SMC keeps control below the activation threshold.
- Once that threshold is reached, the controller applies the selected curve.
- At 92 °C it immediately forces 100%.
- If it loses all temperature readings, it forces 100%.
- When the service stops, it writes `0` to `fanX_target` to hand control back to the SMC.
- systemd's watchdog restarts the controller if it stops responding.

Manual fan control is flagged as unsafe by the kernel itself, since there's no formal recovery guarantee for every failure mode. Use it with care.

## Installation

In a terminal, go into the extracted folder and run:

```
chmod +x install.sh uninstall.sh
sudo ./install.sh
```

If the installer asks, reboot the computer. Then open in your browser:

```
http://127.0.0.1:8799
```

The dashboard only listens on `127.0.0.1`: it's not reachable from the network.
You can also open it from the **Asahi Fan Control** icon installed in the Fedora application menu.

## Installing the KDE Plasma widget

The repository includes a ready-made widget package, `asahi-fan-control-widget-v1.1.2.plasmoid`, for adding fan status/control to your panel or desktop.

**Option A — from the KDE UI (no terminal):**

1. Right-click on the desktop or on a panel and choose **Add Widgets…**
2. In the Widget Explorer, click **Get New Widgets** → **Install Widget From Local File…**
3. Select the downloaded `asahi-fan-control-widget-v1.1.2.plasmoid` file and confirm.
4. The widget will now appear in the widget list — drag it onto your panel or desktop.

**Option B — from the terminal, with `kpackagetool6`:**

```
kpackagetool6 --type Plasma/Applet --install asahi-fan-control-widget-v1.1.2.plasmoid
```

To update it later to a newer version of the same package:

```
kpackagetool6 --type Plasma/Applet --upgrade asahi-fan-control-widget-v1.1.2.plasmoid
```

If it doesn't show up right away, restart Plasma Shell:

```
kquitapp6 plasmashell && kstart plasmashell
```

Then add it as usual via **Add Widgets…** and search for **Asahi Fan Control**.

To remove it:

```
kpackagetool6 --type Plasma/Applet --remove com.<widget-package-id>
```

(check the exact package ID inside the plasmoid's `metadata.json` if the name above doesn't match).

## Profiles

- **Silent:** the controller takes over at 65 °C.
- **Balanced:** takes over at 55 °C.
- **Cool:** takes over at 45 °C.
- **Manual:** 20–100%, while keeping critical-temperature protection.
- **Apple SMC:** control fully handed back to the firmware.

## Diagnostics

```
sudo /opt/asahi-fan-control/asahi_fan_control.py --check
systemctl status asahi-fan-control
journalctl -u asahi-fan-control -f
```

If `control_available` shows up as `false`, check the supported parameter:

```
modinfo -p macsmc-hwmon
```

On current versions it's `fan_control=1`; older Asahi kernels may call it `melt_my_mac=1`.

On Fedora Asahi, if the module is loaded by `initramfs`, enable the parameter directly on the boot line and reboot:

```
sudo grubby --update-kernel=ALL --args="macsmc_hwmon.fan_control=1"
sudo reboot
```

## Configuration

The file is `/etc/asahi-fan-control.json`. You can change temperatures, hysteresis, which sensors are considered, and the dashboard port. Then restart:

```
sudo systemctl restart asahi-fan-control
```

## Removal

```
sudo ./uninstall.sh
```

The uninstaller preserves `/etc/asahi-fan-control.json` and hands the fans back to the SMC before removing the service.
