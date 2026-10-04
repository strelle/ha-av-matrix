"""Constants of the AV Matrix integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "av_matrix"

CONF_DRIVER: Final = "driver"
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_DISPLAYS: Final = "displays"

DEFAULT_SCAN_INTERVAL: Final = 5
MIN_SCAN_INTERVAL: Final = 2
MAX_SCAN_INTERVAL: Final = 60
MAX_BACKOFF: Final = timedelta(seconds=30)
REQUEST_TIMEOUT: Final = 3.0

# linked display options (per destination)
CONF_DISPLAY_ENTITY: Final = "entity_id"
CONF_DISPLAY_INPUT: Final = "input"
CONF_DISPLAY_AUTO_ON: Final = "auto_on"
CONF_DISPLAY_OFF_ON_NONE: Final = "off_on_none"
DISPLAY_ON_TIMEOUT: Final = 10.0

NONE_OPTION: Final = "None"
HISTORY_SIZE: Final = 10
CONNECTING_GRACE: Final = 10.0  # seconds after a route in which "not connected" means "connecting"

EVENT_ROUTED: Final = "av_matrix_routed"
SIGNAL_UPDATE: Final = "av_matrix_update"

STORAGE_KEY: Final = "av_matrix"
STORAGE_VERSION: Final = 1

URL_BASE: Final = "/av_matrix_static"
CARD_FILENAME: Final = "av-matrix-card.js"

SERVICE_ROUTE: Final = "route"
SERVICE_SALVO: Final = "salvo"
SERVICE_LOCK: Final = "lock"
SERVICE_UNLOCK: Final = "unlock"
SERVICE_UNDO: Final = "undo"
SERVICE_REFRESH: Final = "refresh_sources"

ATTR_SOURCE: Final = "source"
ATTR_ROUTES: Final = "routes"
ATTR_DESTINATION: Final = "destination"
