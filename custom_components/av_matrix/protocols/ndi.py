"""NDI® protocol: source identity = NDI name ("MACHINE (Stream name)")."""

from __future__ import annotations

import re

from .base import SourceRegistry

NDI_SERVICE_TYPE = "_ndi._tcp.local."


class NdiSourceRegistry(SourceRegistry):
    """NDI source registry.

    BirdDog lists names with non-ASCII characters as ``NDI_<hex id>``; those are
    mapped to the real name through the address currently used by that name.
    """

    protocol = "ndi"
    placeholder_re = re.compile(r"^NDI_[0-9A-F]{8,}$", re.IGNORECASE)


def ndi_name_from_mdns(name: str, service_type: str = NDI_SERVICE_TYPE) -> str:
    """``"HOST.DOMAIN (Stream)._ndi._tcp.local."`` → ``"HOST.DOMAIN (Stream)"``.

    The instance name itself may contain dots, so strip the service type suffix
    instead of splitting.
    """
    suffix = "." + service_type
    if name.endswith(suffix):
        return name[: -len(suffix)]
    if name.endswith(suffix.rstrip(".")):
        return name[: -len(suffix.rstrip("."))]
    return name
