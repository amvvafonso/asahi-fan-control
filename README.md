# Asahi Fan Control

Local fan controller for Apple Silicon MacBook Pro running Asahi Linux. It talks directly to the `hwmon` interface exposed by the `macsmc-hwmon` driver — no external libraries required.

## Table of Contents

- [Safety](#safety)
- [Installation](#installation)
- [KDE Plasma Widget](#kde-plasma-widget)
- [Profiles](#profiles)
- [Diagnostics](#diagnostics)
- [Configuration](#configuration)
- [Removal](#removal)
- [License](#license)

## Safety

- On the automatic curve, Apple's SMC keeps control below the activation threshold.
- Once that threshold is reached, the controller applies the selected curve.
- At 92 °C it immediately forces 100%.
- If it loses all temperature readings, it forces 100%.
- When the service stops, it writes `0` to `fanX_target` to hand control back to the SMC.
- systemd's watchdog restarts the controller if it stops responding.

> **Note:** Manual fan control is flagged as unsafe by the kernel itself, since there's no formal recovery guarantee for every failure mode. Use it with care.

## Installation

Clone or download this repository, then from the project folder run:

```bash
chmod +x install.sh uninstall.sh
sudo ./install.sh
```

If the installer prompts you to, reboot the computer. Then open the dashboard in your browser:

```
http://127.0.0.1:8799
```

The dashboard only listens on `127.0.0.1` — it is not reachable from the network.
You can also launch it from the **Asahi Fan Control** icon in the Fedora application menu.

## KDE Plasma Widget

A ready-made widget package, [`asahi-fan-control-widget-v1.1.2.plasmoid`](./asahi-fan-control-widget-v1.1.2.plasmoid), is included for adding fan status and control to your panel or desktop.

### Option A — Install via the KDE UI

1. Right-click on the desktop or on a panel and select **Add Widgets…**
2. In the Widget Explorer, click **Get New Widgets** → **Install Widget From Local File…**
3. Select `asahi-fan-control-widget-v1.1.2.plasmoid` and confirm.
4. The widget now appears in the widget list — drag it onto your panel or desktop.

### Option B — Install via terminal

```bash
kpackagetool6 --type Plasma/Applet --install asahi-fan-control-widget-v1.1.2.plasmoid
```

**Update to a newer version:**

```bash
kpackagetool6 --type Plasma/Applet --upgrade asahi-fan-control-widget-v1.1.2.plasmoid
```

**If the widget doesn't appear immediately, restart Plasma Shell:**

```bash
kquitapp6 plasmashell && kstart plasmashell
```

Then add it as usual via **Add Widgets…** and search for **Asahi Fan Control**.

**Remove the widget:**

```bash
kpackagetool6 --type Plasma/Applet --remove com.<widget-package-id>
```

Check the exact package ID in the plasmoid's `metadata.json` if the placeholder above doesn't match.

## Profiles

| Profile | Behavior |
|---|---|
| **Silent** | Controller takes over at 65 °C |
| **Balanced** | Controller takes over at 55 °C |
| **Cool** | Controller takes over at 45 °C |
| **Manual** | 20–100%, with critical-temperature protection always active |
| **Apple SMC** | Control fully returned to the firmware |

## Diagnostics

```bash
sudo /opt/asahi-fan-control/asahi_fan_control.py --check
systemctl status asahi-fan-control
journalctl -u asahi-fan-control -f
```

If `control_available` shows as `false`, check the supported module parameter:

```bash
modinfo -p macsmc-hwmon
```

On current kernels it's `fan_control=1`; older Asahi kernels may call it `melt_my_mac=1`.

On Fedora Asahi, if the module is loaded by `initramfs`, enable the parameter directly on the boot line and reboot:

```bash
sudo grubby --update-kernel=ALL --args="macsmc_hwmon.fan_control=1"
sudo reboot
```

## Configuration

Settings live in `/etc/asahi-fan-control.json` — temperatures, hysteresis, which sensors are considered, and the dashboard port can all be changed there. Restart the service afterward:

```bash
sudo systemctl restart asahi-fan-control
```

## Removal

```bash
sudo ./uninstall.sh
```

The uninstaller preserves `/etc/asahi-fan-control.json` and hands the fans back to the SMC before removing the service.

