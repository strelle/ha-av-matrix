"""Systemauslastung: was der Rechner und was der Dienst gerade tun – direkt aus /proc und /sys.

Sparsam: keine Abhängigkeiten, keine Unterprozesse. Gemessen wird nur, solange jemand zuschaut
(alle 2 s bei offener Detailansicht, alle 5 s für die Anzeige in der Kopfzeile); sonst einmal je Minute
für den Verlauf. Der Verlauf liegt nur im Speicher (einige Minuten).

Nichts hier enthält Geheimnisse: keine Kommandozeilen, keine Pfade aus Benutzerverzeichnissen, keine Schlüssel.
"""

from __future__ import annotations

import asyncio
import glob
import logging
import os
import time
from collections import deque
from typing import Any

IDLE_INTERVAL = 60.0
WATCH_INTERVAL = 5.0
DETAIL_INTERVAL = 2.0
HISTORY = 180
TEMP_WARN, TEMP_HOT = 70.0, 80.0
DISK_WARN, MEM_WARN, CPU_WARN = 90.0, 90.0, 85.0
CLK = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
PAGE = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096


def _read(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def _first(pattern: str) -> str | None:
    for path in sorted(glob.glob(pattern)):
        text = _read(path)
        if text is not None:
            return text.strip()
    return None


class ErrorLog(logging.Handler):
    """Merkt sich die letzten Warnungen und Fehler des Dienstes (nur Text, gekürzt)."""

    def __init__(self, size: int = 20) -> None:
        super().__init__(logging.WARNING)
        self.items: deque[dict[str, Any]] = deque(maxlen=size)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = " ".join(record.getMessage().split())[:200]
        except Exception:  # noqa: BLE001
            return
        self.items.appendleft({"time": record.created, "level": record.levelname.lower(), "where": record.name.rsplit(".", 1)[-1], "message": text})


class SystemMonitor:
    def __init__(self) -> None:
        self.started = time.time()
        self.errors = ErrorLog()
        self.history: deque[dict[str, Any]] = deque(maxlen=HISTORY)
        self.current: dict[str, Any] = {}
        self._cpu_prev: dict[str, tuple[int, int]] = {}
        self._proc_prev: dict[int, tuple[int, float]] = {}
        self._net_prev: tuple[int, int, float] | None = None
        self._companion_pids: list[int] = []
        self._pids_at = 0.0
        self._watch_until = 0.0
        self._detail_until = 0.0
        self._task: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()
        self.sample_cost_ms = 0.0
        self.samples = 0
        #: Schutz vor schleichendem Speicherzuwachs (NDI-Bibliothek): darüber startet der Dienst sich sauber neu
        self.memory_limit_mb = 0
        self.on_memory_limit: Any = None

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        logging.getLogger().addHandler(self.errors)
        self.sample()
        self._task = asyncio.create_task(self._run(), name="avm sysmon")

    async def stop(self) -> None:
        logging.getLogger().removeHandler(self.errors)
        if self._task is not None:
            self._task.cancel()

    def watch(self, detail: bool = False) -> None:
        """Ein Client schaut zu: für kurze Zeit dichter messen."""
        now = time.monotonic()
        was = self.interval()
        self._watch_until = now + 3 * WATCH_INTERVAL
        if detail:
            self._detail_until = now + 3 * DETAIL_INTERVAL
        if self.interval() < was:
            self._wake.set()

    def interval(self) -> float:
        now = time.monotonic()
        if now < self._detail_until:
            return DETAIL_INTERVAL
        return WATCH_INTERVAL if now < self._watch_until else IDLE_INTERVAL

    async def _run(self) -> None:
        while True:
            try:
                await asyncio.wait_for(self._wake.wait(), self.interval())
            except TimeoutError:
                pass
            self._wake.clear()
            self.sample()

    # --------------------------------------------------------------- reading
    def _cpu(self) -> tuple[float | None, list[float]]:
        total, cores = None, []
        for line in (_read("/proc/stat") or "").splitlines():
            if not line.startswith("cpu"):
                break
            name, *vals = line.split()
            nums = [int(v) for v in vals[:8]]
            idle, busy_all = nums[3] + nums[4], sum(nums)
            prev = self._cpu_prev.get(name)
            self._cpu_prev[name] = (idle, busy_all)
            pct = None
            if prev and busy_all > prev[1]:
                pct = round(100 * (1 - (idle - prev[0]) / (busy_all - prev[1])), 1)
            if name == "cpu":
                total = pct
            elif pct is not None:
                cores.append(pct)
        return total, cores

    @staticmethod
    def _mem() -> dict[str, Any]:
        info = {}
        for line in (_read("/proc/meminfo") or "").splitlines():
            key, _, rest = line.partition(":")
            if key in ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree"):
                info[key] = int(rest.split()[0]) // 1024
        total, avail = info.get("MemTotal", 0), info.get("MemAvailable", 0)
        return {
            "total_mb": total,
            "used_mb": total - avail,
            "free_mb": avail,
            "percent": round(100 * (total - avail) / total, 1) if total else None,
            "swap_used_mb": info.get("SwapTotal", 0) - info.get("SwapFree", 0),
        }

    def _find_companion(self) -> list[int]:
        """Prozesse von Bitfocus Companion (Hauptprozess, Module, Oberflächen) – selten neu gesucht."""
        now = time.monotonic()
        if now - self._pids_at < 30 and self._companion_pids:
            return self._companion_pids
        self._pids_at = now
        main = []
        for path in glob.glob("/proc/[0-9]*/cmdline"):
            text = _read(path) or ""
            if "/companion/" in text and "main.js" in text and "node" in text:
                main.append(int(path.split("/")[2]))
        pids = set(main)
        if main:  # Kindprozesse (Module laufen als eigene Prozesse des Hauptprozesses)
            parents: dict[int, int] = {}
            for path in glob.glob("/proc/[0-9]*/stat"):
                text = _read(path)
                if text:
                    parents[int(path.split("/")[2])] = int(text.rsplit(")", 1)[1].split()[1])
            grew = True
            while grew:
                grew = False
                for pid, parent in parents.items():
                    if parent in pids and pid not in pids:
                        pids.add(pid)
                        grew = True
        self._companion_pids = sorted(pids)
        return self._companion_pids

    def _process(self, pids: list[int], now: float) -> dict[str, Any]:
        cpu, rss, threads, alive = 0.0, 0, 0, 0
        for pid in pids:
            text = _read(f"/proc/{pid}/stat")
            if not text:
                continue
            fields = text.rsplit(")", 1)[1].split()
            ticks = int(fields[11]) + int(fields[12])
            prev = self._proc_prev.get(pid)
            self._proc_prev[pid] = (ticks, now)
            if prev and now > prev[1]:
                cpu += 100 * (ticks - prev[0]) / CLK / (now - prev[1])
            rss += int(fields[21]) * PAGE // (1024 * 1024)
            threads += int(fields[17])
            alive += 1
        return {"cpu_percent": round(cpu, 1), "rss_mb": rss, "threads": threads, "processes": alive}

    def _net(self, now: float) -> dict[str, Any]:
        rx = tx = 0
        for line in (_read("/proc/net/dev") or "").splitlines()[2:]:
            name, _, rest = line.partition(":")
            if name.strip() in ("lo",) or name.strip().startswith(("docker", "veth", "br-")):
                continue
            vals = rest.split()
            rx, tx = rx + int(vals[0]), tx + int(vals[8])
        prev, self._net_prev = self._net_prev, (rx, tx, now)
        if not prev or now <= prev[2]:
            return {"rx_kbit": None, "tx_kbit": None}
        span = now - prev[2]
        return {"rx_kbit": round((rx - prev[0]) * 8 / 1000 / span), "tx_kbit": round((tx - prev[1]) * 8 / 1000 / span)}

    def sample(self) -> dict[str, Any]:
        began = time.perf_counter()
        now = time.monotonic()
        cpu, cores = self._cpu()
        load = (_read("/proc/loadavg") or "0 0 0").split()[:3]
        temp_raw = _read("/sys/class/thermal/thermal_zone0/temp")
        temp = round(int(temp_raw) / 1000, 1) if temp_raw and temp_raw.strip().lstrip("-").isdigit() else None
        under = _first("/sys/class/hwmon/hwmon*/in0_lcrit_alarm")
        freq, freq_max = _read("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq"), _read("/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq")
        try:
            disk = os.statvfs("/")
            disk_total, disk_free = disk.f_blocks * disk.f_frsize, disk.f_bavail * disk.f_frsize
        except OSError:
            disk_total = disk_free = 0
        uptime = (_read("/proc/uptime") or "0").split()[0]
        host = {
            "cpu_percent": cpu,
            "cores_percent": cores,
            "cores": len(cores) or os.cpu_count(),
            "load": [float(v) for v in load],
            "memory": self._mem(),
            "temperature_c": temp,
            "undervoltage": (under == "1") if under in ("0", "1") else None,
            # Drosselung meldet nur die Firmware (vcgencmd, braucht Gerätezugriff); ohne Root bleibt die Taktfrequenz
            "throttled": None,
            "cpu_mhz": round(int(freq) / 1000) if freq and freq.strip().isdigit() else None,
            "cpu_max_mhz": round(int(freq_max) / 1000) if freq_max and freq_max.strip().isdigit() else None,
            "disk": {
                "total_gb": round(disk_total / 1e9, 1),
                "free_gb": round(disk_free / 1e9, 1),
                "percent": round(100 * (1 - disk_free / disk_total), 1) if disk_total else None,
            },
            "network": self._net(now),
            "uptime_s": round(float(uptime)),
        }
        processes = {
            "matrix": {**self._process([os.getpid()], now), "uptime_s": round(time.time() - self.started)},
            "companion": self._process(self._find_companion(), now),
        }
        self.current = {"time": time.time(), "host": host, "processes": processes}
        self.history.append(
            {
                "t": round(time.time()),
                "cpu": cpu,
                "mem": host["memory"]["percent"],
                "temp": temp,
                "matrix": processes["matrix"]["cpu_percent"],
                "companion": processes["companion"]["cpu_percent"],
            }
        )
        self.samples += 1
        if self.memory_limit_mb and processes["matrix"]["rss_mb"] > self.memory_limit_mb and self.on_memory_limit:
            self.on_memory_limit(processes["matrix"]["rss_mb"])
        self.sample_cost_ms = round((time.perf_counter() - began) * 1000, 2)
        return self.current

    # -------------------------------------------------------------- warnings
    def warnings(self) -> list[dict[str, str]]:
        host = self.current.get("host") or {}
        out: list[dict[str, str]] = []
        temp = host.get("temperature_c")
        if temp is not None and temp >= TEMP_HOT:
            out.append({"code": "overheat", "text": f"Überhitzung: {temp:.0f} °C"})
        elif temp is not None and temp >= TEMP_WARN:
            out.append({"code": "hot", "text": f"Heiß: {temp:.0f} °C"})
        if host.get("undervoltage"):
            out.append({"code": "undervoltage", "text": "Unterspannung am Netzteil"})
        freq, top = host.get("cpu_mhz"), host.get("cpu_max_mhz")
        if temp is not None and temp >= TEMP_WARN and freq and top and freq < top * 0.7:
            out.append({"code": "throttled", "text": f"Gedrosselt: {freq} von {top} MHz"})
        disk = (host.get("disk") or {}).get("percent")
        if disk is not None and disk >= DISK_WARN:
            out.append({"code": "disk_full", "text": f"Speicherplatz knapp: {disk:.0f} % belegt"})
        mem = (host.get("memory") or {}).get("percent")
        if mem is not None and mem >= MEM_WARN:
            out.append({"code": "memory", "text": f"Arbeitsspeicher knapp: {mem:.0f} % belegt"})
        recent = [h["cpu"] for h in self.history if h["cpu"] is not None and h["t"] >= time.time() - 120]
        if len(recent) >= 6 and sum(recent) / len(recent) >= CPU_WARN:
            out.append({"code": "load", "text": f"Dauerhaft hohe Last: {sum(recent) / len(recent):.0f} % CPU"})
        return out

    def summary(self) -> dict[str, Any]:
        """Kompakt für die Anzeige in der Kopfzeile."""
        host = self.current.get("host") or {}
        return {
            "cpu_percent": host.get("cpu_percent"),
            "memory_percent": (host.get("memory") or {}).get("percent"),
            "temperature_c": host.get("temperature_c"),
            "warnings": self.warnings(),
        }
