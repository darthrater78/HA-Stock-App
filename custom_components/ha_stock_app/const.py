import json as _json
from pathlib import Path as _Path

DOMAIN = "ha_stock_app"
PLATFORMS = ["sensor", "button", "select", "switch"]
VERSION = _json.loads((_Path(__file__).parent / "manifest.json").read_text())["version"]

CONF_STOCKS = "stocks"
CONF_API_PROVIDER = "api_provider"
CONF_API_KEY = "api_key"
CONF_POLL_FREQUENCY = "poll_frequency"
CONF_MONARCH_EMAIL = "monarch_email"
CONF_MONARCH_PASSWORD = "monarch_password"
CONF_MONARCH_ENABLED = "monarch_enabled"
CONF_MONARCH_MFA_SECRET = "monarch_mfa_secret"
CONF_ALERT_THRESHOLD = "alert_threshold"
CONF_ALERT_COOLDOWN = "alert_cooldown"

DEFAULT_PROVIDER = "finnhub"
DEFAULT_POLL_FREQUENCY = 300  # 5 minutes
DEFAULT_ALERT_THRESHOLD = 2.0  # percent
DEFAULT_ALERT_COOLDOWN = 60  # minutes

# Feature toggles
CONF_ENABLE_MARKET_HOURS = "enable_market_hours"
CONF_ENABLE_EOD_SUMMARY = "enable_eod_summary"
CONF_ENABLE_MARKET_OPEN_EVENT = "enable_market_open_event"
CONF_ENABLE_FINNHUB_SELF_TEST = "enable_finnhub_self_test"
CONF_ENABLE_MONARCH_DOUBLE_REFRESH = "enable_monarch_double_refresh"
CONF_ENABLE_401K_REPORTING = "enable_401k_reporting"
CONF_ENABLE_PAYCHECK_DETECTION = "enable_paycheck_detection"

DEFAULT_ENABLE_MARKET_HOURS = True
DEFAULT_ENABLE_EOD_SUMMARY = True
DEFAULT_ENABLE_MARKET_OPEN_EVENT = False
DEFAULT_ENABLE_FINNHUB_SELF_TEST = True
DEFAULT_ENABLE_MONARCH_DOUBLE_REFRESH = True
DEFAULT_ENABLE_401K_REPORTING = False
DEFAULT_ENABLE_PAYCHECK_DETECTION = True

# Configurable values
CONF_MONARCH_POLL_INTERVAL = "monarch_poll_interval"
CONF_PAYCHECK_ACCOUNT = "paycheck_account"
CONF_PAYCHECK_THRESHOLD = "paycheck_threshold"
CONF_PAYCHECK_WINDOWS = "paycheck_windows"
CONF_401K_SENSOR = "401k_sensor_entity"
CONF_401K_QUIET_START = "401k_quiet_start"
CONF_401K_QUIET_END = "401k_quiet_end"
CONF_401K_RETRY_INTERVAL = "401k_retry_interval"

CONF_MONARCH_SYNC_COOLDOWN = "monarch_sync_cooldown"
DEFAULT_MONARCH_POLL_INTERVAL = 15  # minutes
DEFAULT_MONARCH_SYNC_COOLDOWN = 240  # minutes (4 hours)
DEFAULT_PAYCHECK_THRESHOLD = 4000.0
DEFAULT_PAYCHECK_WINDOWS = "27-5,11-19"
DEFAULT_401K_QUIET_START = "22:00"
DEFAULT_401K_QUIET_END = "08:35"
DEFAULT_401K_RETRY_INTERVAL = 30  # minutes

# Events
EVENT_PRICE_ALERT = f"{DOMAIN}_price_alert"
EVENT_EOD_SUMMARY = f"{DOMAIN}_eod_summary"
EVENT_PAYCHECK_DETECTED = f"{DOMAIN}_paycheck_detected"
EVENT_MONARCH_STATUS = f"{DOMAIN}_monarch_status"
EVENT_MARKET_OPEN = f"{DOMAIN}_market_open"
EVENT_EOD2_SUMMARY = f"{DOMAIN}_eod2_summary"
EVENT_FINNHUB_ERROR = f"{DOMAIN}_finnhub_error"
EVENT_FINNHUB_OK = f"{DOMAIN}_finnhub_ok"
EVENT_STOCK_UPDATE = f"{DOMAIN}_stock_update"
EVENT_MONARCH_SYNC = f"{DOMAIN}_monarch_sync"

CONF_MARKET_TIMEZONE = "market_timezone"
DEFAULT_MARKET_TIMEZONE = "America/New_York"

# The holiday calendar is NYSE-specific, so Eastern is the correct answer for
# US equities. Exposed mainly so the assumption is visible and overridable.
MARKET_TIMEZONES = {
    "America/New_York": "Eastern — NYSE, NASDAQ (default)",
    "America/Chicago": "Central — CME, CBOT",
    "America/Los_Angeles": "Pacific",
    "Europe/London": "London — LSE",
    "Europe/Frankfurt": "Frankfurt — XETRA",
    "Asia/Tokyo": "Tokyo — TSE",
    "Australia/Sydney": "Sydney — ASX",
    "UTC": "UTC",
}

CONF_MONARCH_ACCOUNTS = "monarch_accounts"
CONF_PL_ACCOUNTS = "pl_accounts"
CONF_PL_TICKER_MAP = "pl_ticker_map"
CONF_ENABLE_DEBUG_LOGGING = "enable_debug_logging"
DEFAULT_ENABLE_DEBUG_LOGGING = False
PROVIDERS = {
    "finnhub": "Finnhub",
}


def device_info(entry) -> dict:
    from homeassistant.helpers.device_registry import DeviceInfo

    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="HA Stock App",
        manufacturer="HA Stock App",
        model="Stock & Finance Tracker",
        sw_version=VERSION,
    )


def first_entity_id(hass, entry_id: str) -> str | None:
    from homeassistant.helpers import entity_registry as er

    ent_reg = er.async_get(hass)
    entries = er.async_entries_for_config_entry(ent_reg, entry_id)
    return entries[0].entity_id if entries else None
