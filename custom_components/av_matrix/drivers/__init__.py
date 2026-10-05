"""Device drivers. Add a new device family by adding a class to ``DRIVERS``.

See CONTRIBUTING.md / docs/adding-a-driver.md.
"""

from __future__ import annotations

from .base import CannotConnect, Driver, DriverError, InvalidAuth, RouteFailed
from .birddog import BirdDogDecoder
from .dante import DanteNetwork
from .magewell import MagewellProConvert

DRIVERS: dict[str, type[Driver]] = {
    driver.KEY: driver
    for driver in (
        BirdDogDecoder,
        DanteNetwork,
        MagewellProConvert,
    )
}

__all__ = ["DRIVERS", "CannotConnect", "Driver", "DriverError", "InvalidAuth", "RouteFailed"]
