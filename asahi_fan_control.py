#!/usr/bin/env python3
"""Asahi Fan Control - safe userspace fan controller for Apple Silicon Macs."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import signal
import socket
import stat
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


VERSION = "1.0.1"
LOG = logging.getLogger("asahi-fan-control")

DEFAULT_CONFIG: dict[str, Any] = {
    "poll_interval": 1.0,
    "emergency_temperature": 92.0,
    "critical_temperature": 100.0,
    "deactivation_hysteresis": 5.0,
    "rpm_step_percent": 12.0,
    "sensor_include_regex": ".*",
    "sensor_exclude_regex": "(?i)(ambient|battery|palm|wireless)",
    "default_preset": "balanced",
    "web": {"enabled": True, "host": "127.0.0.1", "port": 8799},
    "presets": {
        "quiet": {
            "label": "Silencioso",
            "activation_temperature": 65.0,
            "curve": [[65, 25], [75, 45], [85, 80], [92, 100]],
        },
        "balanced": {
            "label": "Equilibrado",
            "activation_temperature": 55.0,
            "curve": [[55, 25], [65, 40], [75, 65], [85, 90], [92, 100]],
        },
        "cool": {
            "label": "Fresco",
            "activation_temperature": 45.0,
            "curve": [[45, 25], [55, 40], [65, 60], [75, 80], [85, 100]],
        },
    },
}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = json.loads(json.dumps(base))
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def read_int(path: Path) -> int:
    return int(path.read_text(encoding="ascii").strip())


def read_text(path: Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return default


@dataclass
class TemperatureSensor:
    label: str
    input_path: Path

    def read_celsius(self) -> float:
        value = read_int(self.input_path) / 1000.0
        if not -20.0 <= value <= 150.0:
            raise ValueError(f"invalid temperature {value}")
        return value


@dataclass
class Fan:
    index: int
    label: str
    input_path: Path
    target_path: Path
    min_path: Path
    max_path: Path

    @property
    def minimum(self) -> int:
        return read_int(self.min_path)

    @property
    def maximum(self) -> int:
        return read_int(self.max_path)

    @property
    def rpm(self) -> int:
        return read_int(self.input_path)

    @property
    def target(self) -> int:
        return read_int(self.target_path)

    @property
    def writable(self) -> bool:
        try:
            return bool(self.target_path.stat().st_mode & stat.S_IWUSR)
        except OSError:
            return False

    def set_target(self, rpm: int) -> None:
        self.target_path.write_text(str(rpm), encoding="ascii")

    def restore_smc(self) -> None:
        self.set_target(0)


class Hardware:
    def __init__(self, sysfs_root: Path, config: dict[str, Any]):
        self.sysfs_root = sysfs_root
        self.config = config
        self.hwmon_path: Path | None = None
        self.fans: list[Fan] = []
        self.sensors: list[TemperatureSensor] = []
        self.discover()

    def discover(self) -> None:
        include = re.compile(str(self.config["sensor_include_regex"]))
        exclude_pattern = str(self.config.get("sensor_exclude_regex", ""))
        exclude = re.compile(exclude_pattern) if exclude_pattern else None

        candidates = sorted(self.sysfs_root.glob("hwmon*"))
        for candidate in candidates:
            name = read_text(candidate / "name").lower().replace("-", "_")
            if "macsmc" in name or name in {"apple_smc", "applesmc"}:
                self.hwmon_path = candidate
                break
        if self.hwmon_path is None:
            raise RuntimeError("macsmc-hwmon não foi encontrado em /sys/class/hwmon")

        for input_path in sorted(self.hwmon_path.glob("fan[0-9]*_input")):
            match = re.match(r"fan(\d+)_input$", input_path.name)
            if not match:
                continue
            index = int(match.group(1))
            paths = {
                "target": self.hwmon_path / f"fan{index}_target",
                "min": self.hwmon_path / f"fan{index}_min",
                "max": self.hwmon_path / f"fan{index}_max",
            }
            if not all(path.exists() for path in paths.values()):
                continue
            label = read_text(self.hwmon_path / f"fan{index}_label", f"Fan {index}")
            self.fans.append(Fan(index, label, input_path, paths["target"], paths["min"], paths["max"]))

        for input_path in sorted(self.hwmon_path.glob("temp[0-9]*_input")):
            match = re.match(r"temp(\d+)_input$", input_path.name)
            if not match:
                continue
            index = int(match.group(1))
            label = read_text(self.hwmon_path / f"temp{index}_label", f"Temperature {index}")
            if include.search(label) and not (exclude and exclude.search(label)):
                self.sensors.append(TemperatureSensor(label, input_path))

        if not self.fans:
            raise RuntimeError("não foram encontradas ventoinhas compatíveis")
        if not self.sensors:
            raise RuntimeError("não foram encontrados sensores de temperatura válidos")

    @property
    def control_available(self) -> bool:
        return all(fan.writable for fan in self.fans)

    def temperatures(self) -> list[dict[str, Any]]:
        values: list[dict[str, Any]] = []
        for sensor in self.sensors:
            try:
                values.append({"label": sensor.label, "celsius": round(sensor.read_celsius(), 1)})
            except (OSError, ValueError):
                continue
        return values

    def fan_status(self) -> list[dict[str, Any]]:
        result = []
        for fan in self.fans:
            try:
                result.append({
                    "index": fan.index,
                    "label": fan.label,
                    "rpm": fan.rpm,
                    "target": fan.target,
                    "minimum": fan.minimum,
                    "maximum": fan.maximum,
                    "writable": fan.writable,
                })
            except OSError as exc:
                result.append({"index": fan.index, "label": fan.label, "error": str(exc)})
        return result

    def set_percent(self, percent: float, previous: dict[int, int], step_percent: float) -> dict[int, int]:
        targets: dict[int, int] = {}
        percent = max(0.0, min(100.0, percent))
        for fan in self.fans:
            minimum, maximum = fan.minimum, fan.maximum
            requested = round(minimum + ((maximum - minimum) * percent / 100.0))
            old = previous.get(fan.index, fan.target or minimum)
            max_step = max(100, round((maximum - minimum) * step_percent / 100.0))
            if requested < old:
                requested = max(requested, old - max_step)
            fan.set_target(requested)
            targets[fan.index] = requested
        return targets

    def set_maximum(self) -> dict[int, int]:
        targets = {}
        for fan in self.fans:
            fan.set_target(fan.maximum)
            targets[fan.index] = fan.maximum
        return targets

    def restore_smc(self) -> None:
        errors = []
        for fan in self.fans:
            try:
                if fan.writable:
                    fan.restore_smc()
            except OSError as exc:
                errors.append(f"{fan.label}: {exc}")
        if errors:
            raise RuntimeError("; ".join(errors))


def interpolate_curve(curve: list[list[float]], temperature: float) -> float:
    points = sorted((float(t), float(p)) for t, p in curve)
    if temperature <= points[0][0]:
        return points[0][1]
    for (t1, p1), (t2, p2) in zip(points, points[1:]):
        if temperature <= t2:
            ratio = (temperature - t1) / (t2 - t1)
            return p1 + ratio * (p2 - p1)
    return points[-1][1]


class Controller:
    def __init__(self, hardware: Hardware, config: dict[str, Any], config_path: Path):
        self.hardware = hardware
        self.config = config
        self.config_path = config_path
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.mode = "auto" if hardware.control_available else "smc"
        self.preset = str(config["default_preset"])
        self.manual_percent = 50.0
        self.override_active = False
        self.last_targets: dict[int, int] = {}
        self.last_error: str | None = None
        self.last_update = 0.0
        self.state: dict[str, Any] = {}
        # A previous daemon may have stopped abruptly while the SMC was still
        # in manual mode. Always begin from Apple's automatic control.
        if hardware.control_available:
            hardware.restore_smc()

    def _save_preference(self) -> None:
        try:
            saved = json.loads(self.config_path.read_text(encoding="utf-8")) if self.config_path.exists() else {}
            saved["default_preset"] = self.preset
            temp = self.config_path.with_suffix(".tmp")
            temp.write_text(json.dumps(saved, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            os.replace(temp, self.config_path)
        except OSError as exc:
            LOG.warning("Não foi possível guardar a preferência: %s", exc)

    def set_mode(self, mode: str) -> None:
        if mode not in {"smc", "auto", "manual"}:
            raise ValueError("modo inválido")
        with self.lock:
            if mode != "smc" and not self.hardware.control_available:
                raise RuntimeError("controlo manual não está ativado no kernel")
            if mode == "smc":
                self.hardware.restore_smc()
                self.override_active = False
                self.last_targets = {}
            self.mode = mode

    def set_preset(self, preset: str) -> None:
        if preset not in self.config["presets"]:
            raise ValueError("perfil desconhecido")
        with self.lock:
            self.preset = preset
            self._save_preference()

    def set_manual_percent(self, percent: float) -> None:
        if not 20 <= percent <= 100:
            raise ValueError("a velocidade manual tem de estar entre 20% e 100%")
        with self.lock:
            self.manual_percent = float(percent)

    def tick(self) -> None:
        with self.lock:
            temps = self.hardware.temperatures()
            hottest = max((item["celsius"] for item in temps), default=None)
            error = None
            requested_percent: float | None = None

            try:
                if self.mode == "smc":
                    if self.override_active:
                        self.hardware.restore_smc()
                    self.override_active = False
                    self.last_targets = {}
                elif hottest is None:
                    self.last_targets = self.hardware.set_maximum()
                    self.override_active = True
                    requested_percent = 100.0
                    error = "sem leitura de temperatura: ventoinhas no máximo"
                elif hottest >= float(self.config["critical_temperature"]):
                    self.last_targets = self.hardware.set_maximum()
                    self.override_active = True
                    requested_percent = 100.0
                    error = "temperatura crítica"
                elif self.mode == "manual":
                    requested_percent = self.manual_percent
                    self.last_targets = self.hardware.set_percent(
                        requested_percent, self.last_targets, float(self.config["rpm_step_percent"])
                    )
                    self.override_active = True
                else:
                    preset = self.config["presets"][self.preset]
                    activation = float(preset["activation_temperature"])
                    deactivate = activation - float(self.config["deactivation_hysteresis"])
                    if hottest >= float(self.config["emergency_temperature"]):
                        requested_percent = 100.0
                        self.last_targets = self.hardware.set_maximum()
                        self.override_active = True
                    elif not self.override_active and hottest < activation:
                        self.last_targets = {}
                    elif self.override_active and hottest < deactivate:
                        self.hardware.restore_smc()
                        self.override_active = False
                        self.last_targets = {}
                    else:
                        requested_percent = interpolate_curve(preset["curve"], hottest)
                        self.last_targets = self.hardware.set_percent(
                            requested_percent, self.last_targets, float(self.config["rpm_step_percent"])
                        )
                        self.override_active = True
            except (OSError, RuntimeError, ValueError) as exc:
                error = str(exc)
                LOG.error("Falha de controlo: %s", exc)
                try:
                    if self.hardware.control_available:
                        self.last_targets = self.hardware.set_maximum()
                        self.override_active = True
                except OSError:
                    pass

            self.last_error = error
            self.last_update = time.time()
            self.state = {
                "version": VERSION,
                "mode": self.mode,
                "preset": self.preset,
                "manual_percent": self.manual_percent,
                "override_active": self.override_active,
                "requested_percent": round(requested_percent, 1) if requested_percent is not None else None,
                "hottest": hottest,
                "temperatures": sorted(temps, key=lambda item: item["celsius"], reverse=True),
                "fans": self.hardware.fan_status(),
                "control_available": self.hardware.control_available,
                "error": error,
                "updated_at": self.last_update,
                "presets": {
                    key: {"label": val.get("label", key), "curve": val["curve"]}
                    for key, val in self.config["presets"].items()
                },
            }

    def status(self) -> dict[str, Any]:
        with self.lock:
            return json.loads(json.dumps(self.state))

    def run(self) -> None:
        interval = max(0.25, float(self.config["poll_interval"]))
        LOG.info("Controlador iniciado em modo %s, perfil %s", self.mode, self.preset)
        while not self.stop_event.is_set():
            started = time.monotonic()
            self.tick()
            notify_systemd_watchdog()
            remaining = interval - (time.monotonic() - started)
            self.stop_event.wait(max(0.05, remaining))

    def stop(self) -> None:
        self.stop_event.set()
        with self.lock:
            try:
                self.hardware.restore_smc()
                LOG.info("Controlo devolvido ao SMC")
            except (OSError, RuntimeError) as exc:
                LOG.error("Não foi possível devolver o controlo ao SMC: %s", exc)


def notify_systemd_watchdog() -> None:
    address = os.environ.get("NOTIFY_SOCKET")
    if not address:
        return
    if address.startswith("@"):
        address = "\0" + address[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.connect(address)
            sock.sendall(b"WATCHDOG=1\nSTATUS=Asahi Fan Control ativo")
    except OSError:
        pass


class ApiHandler(BaseHTTPRequestHandler):
    controller: Controller
    web_root: Path

    def log_message(self, fmt: str, *args: Any) -> None:
        LOG.debug("HTTP: " + fmt, *args)

    def _json(self, code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _same_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        return origin in {
            "http://127.0.0.1:8799",
            "http://localhost:8799",
            f"http://{self.headers.get('Host', '')}",
        }

    def do_GET(self) -> None:
        if self.path == "/api/status":
            self._json(200, self.controller.status())
            return
        requested = "index.html" if self.path in {"/", "/index.html"} else self.path.lstrip("/")
        if requested not in {"index.html", "app.js", "style.css"}:
            self.send_error(404)
            return
        path = self.web_root / requested
        try:
            body = path.read_bytes()
        except OSError:
            self.send_error(404)
            return
        mime = {".html": "text/html", ".js": "text/javascript", ".css": "text/css"}[path.suffix]
        self.send_response(200)
        self.send_header("Content-Type", f"{mime}; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if not self._same_origin():
            self._json(403, {"error": "origem recusada"})
            return
        try:
            length = min(int(self.headers.get("Content-Length", "0")), 4096)
            data = json.loads(self.rfile.read(length) or b"{}")
            if self.path == "/api/mode":
                self.controller.set_mode(str(data["mode"]))
            elif self.path == "/api/preset":
                self.controller.set_preset(str(data["preset"]))
            elif self.path == "/api/manual":
                self.controller.set_manual_percent(float(data["percent"]))
            else:
                self._json(404, {"error": "endpoint desconhecido"})
                return
            self.controller.tick()
            self._json(200, self.controller.status())
        except (KeyError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
            self._json(400, {"error": str(exc)})


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return json.loads(json.dumps(DEFAULT_CONFIG))
    user_config = json.loads(path.read_text(encoding="utf-8"))
    config = deep_merge(DEFAULT_CONFIG, user_config)
    if config["default_preset"] not in config["presets"]:
        raise ValueError("default_preset não existe em presets")
    for preset in config["presets"].values():
        if len(preset.get("curve", [])) < 2:
            raise ValueError("cada curva precisa de pelo menos dois pontos")
    return config


def main() -> int:
    parser = argparse.ArgumentParser(description="Controlador de ventoinhas para Asahi Linux")
    parser.add_argument("--config", type=Path, default=Path("/etc/asahi-fan-control.json"))
    parser.add_argument("--sysfs-root", type=Path, default=Path("/sys/class/hwmon"))
    parser.add_argument("--web-root", type=Path, default=Path(__file__).resolve().parent / "web")
    parser.add_argument("--check", action="store_true", help="verifica hardware e configuração")
    parser.add_argument("--once", action="store_true", help="executa um único ciclo")
    parser.add_argument("--no-web", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        config = load_config(args.config)
        hardware = Hardware(args.sysfs_root, config)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        LOG.error("Inicialização falhou: %s", exc)
        return 2

    if args.check:
        print(json.dumps({
            "hwmon": str(hardware.hwmon_path),
            "control_available": hardware.control_available,
            "fans": hardware.fan_status(),
            "temperatures": hardware.temperatures(),
        }, indent=2, ensure_ascii=False))
        return 0 if hardware.control_available else 3

    controller = Controller(hardware, config, args.config)
    controller.tick()
    if args.once:
        print(json.dumps(controller.status(), indent=2, ensure_ascii=False))
        controller.stop()
        return 0

    def shutdown(_signum: int, _frame: Any) -> None:
        controller.stop()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    worker = threading.Thread(target=controller.run, name="fan-controller", daemon=True)
    worker.start()

    server = None
    try:
        web = config["web"]
        if bool(web["enabled"]) and not args.no_web:
            ApiHandler.controller = controller
            ApiHandler.web_root = args.web_root
            server = ThreadingHTTPServer((str(web["host"]), int(web["port"])), ApiHandler)
            server.timeout = 0.5
            LOG.info("Painel disponível em http://%s:%s", web["host"], web["port"])
            while not controller.stop_event.is_set():
                server.handle_request()
        else:
            while not controller.stop_event.wait(0.5):
                pass
    finally:
        if server:
            server.server_close()
        controller.stop()
        worker.join(timeout=3)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
