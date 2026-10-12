"""Eigene Adressen des Servers (Name, Studionetz, Tailscale) für Panel, Companion-Seite und mDNS."""

from __future__ import annotations

import ipaddress
import json
import socket
import subprocess
from typing import Any

TAILSCALE_NET = ipaddress.ip_network("100.64.0.0/10")


def _ipv4_addresses() -> list[tuple[str, str]]:
    """``[(interface, address)]`` aller IPv4-Adressen außer Loopback."""
    try:
        raw = subprocess.run(["ip", "-j", "-4", "addr"], capture_output=True, text=True, timeout=3, check=True).stdout
        out = []
        for iface in json.loads(raw):
            for info in iface.get("addr_info", []):
                if info.get("family") == "inet" and not info["local"].startswith("127."):
                    out.append((iface.get("ifname", ""), info["local"]))
        if out:
            return out
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    try:  # Rückfall (macOS / ohne iproute2): Adresse der Standardroute
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1", 9))
            return [("", sock.getsockname()[0])]
    except OSError:
        return []


def addresses(port: int, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Zugangsadressen. ``overrides`` (Konfiguration ``addresses``) kann jeden Wert festlegen."""
    overrides = overrides or {}
    hostname = socket.gethostname().split(".")[0]
    lan = tailscale = None
    for iface, addr in _ipv4_addresses():
        ip = ipaddress.ip_address(addr)
        if ip in TAILSCALE_NET or iface.startswith("tailscale"):
            tailscale = tailscale or addr
        elif ip.is_private and not ip.is_link_local and not iface.startswith(("docker", "br-", "veth")):
            lan = lan or addr
    info = {
        "hostname": hostname,
        "port": port,
        "mdns_name": overrides.get("mdns_name") or f"{hostname}.local",
        "lan_ip": overrides.get("lan_ip") or lan,
        "tailscale_ip": overrides.get("tailscale_ip") or tailscale,
        "tailscale_name": overrides.get("tailscale_name") or None,
    }
    urls = []
    for key, label in (
        ("mdns_name", "Studionetz (Name)"),
        ("lan_ip", "Studionetz (IP)"),
        ("tailscale_name", "Tailscale (Name)"),
        ("tailscale_ip", "Tailscale (IP)"),
    ):
        if info[key]:
            urls.append({"kind": key, "label": label, "host": info[key], "url": f"http://{info[key]}:{port}/"})
    info["urls"] = urls
    return info


def allowed_hosts(info: dict[str, Any], extra: list[str] | None = None) -> set[str]:
    """Host-Namen, unter denen der Server angesprochen werden darf (Schutz gegen DNS-Rebinding)."""
    hosts = {"localhost", "127.0.0.1", info["hostname"].lower()}
    for key in ("mdns_name", "lan_ip", "tailscale_ip", "tailscale_name"):
        if info.get(key):
            hosts.add(str(info[key]).lower())
    hosts.update(h.lower() for h in extra or [])
    return hosts


def connect_urls(info: dict[str, Any]) -> list[dict[str, str]]:
    """Adressen für den QR-Code – solche, die ein Telefon wirklich erreicht, die beste zuerst.

    Reihenfolge: IP im Studionetz (Standard), Tailscale-Name, Tailscale-IP, zuletzt der ``.local``-Name
    (Android löst mDNS oft nicht auf). Nie ``localhost``.
    """
    port = info.get("port")
    out = []
    for kind, label in (
        ("lan_ip", "Studionetz"),
        ("tailscale_name", "Tailscale"),
        ("tailscale_ip", "Tailscale (IP)"),
        ("mdns_name", "Studionetz (Name)"),
    ):
        host = info.get(kind)
        if host and str(host).lower() not in ("localhost", "127.0.0.1"):
            out.append({"kind": kind, "label": label, "host": str(host), "url": f"http://{host}:{port}/"})
    return out
