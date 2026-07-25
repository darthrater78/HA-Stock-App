from __future__ import annotations

import logging
import re

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN,
    CONF_STOCKS,
    CONF_API_PROVIDER,
    CONF_API_KEY,
    CONF_POLL_FREQUENCY,
    CONF_MONARCH_ENABLED,
    CONF_MONARCH_EMAIL,
    CONF_MONARCH_PASSWORD,
    CONF_MONARCH_MFA_SECRET,
    CONF_ALERT_THRESHOLD,
    CONF_MONARCH_ACCOUNTS,
    CONF_ENABLE_MARKET_HOURS,
    CONF_ENABLE_EOD_SUMMARY,
    CONF_ENABLE_MARKET_OPEN_EVENT,
    CONF_ENABLE_FINNHUB_SELF_TEST,
    CONF_ENABLE_MONARCH_DOUBLE_REFRESH,
    CONF_ENABLE_401K_REPORTING,
    CONF_ENABLE_PAYCHECK_DETECTION,
    CONF_ENABLE_DEBUG_LOGGING,
    CONF_MARKET_TIMEZONE,
    CONF_MONARCH_POLL_INTERVAL,
    CONF_PAYCHECK_ACCOUNT,
    CONF_PAYCHECK_THRESHOLD,
    CONF_PAYCHECK_WINDOWS,
    CONF_401K_SENSOR,
    CONF_401K_QUIET_START,
    CONF_401K_QUIET_END,
    CONF_401K_RETRY_INTERVAL,
    DEFAULT_PROVIDER,
    DEFAULT_POLL_FREQUENCY,
    DEFAULT_ALERT_THRESHOLD,
    DEFAULT_ENABLE_MARKET_HOURS,
    DEFAULT_ENABLE_EOD_SUMMARY,
    DEFAULT_ENABLE_MARKET_OPEN_EVENT,
    DEFAULT_ENABLE_FINNHUB_SELF_TEST,
    DEFAULT_ENABLE_MONARCH_DOUBLE_REFRESH,
    DEFAULT_ENABLE_401K_REPORTING,
    DEFAULT_ENABLE_PAYCHECK_DETECTION,
    DEFAULT_ENABLE_DEBUG_LOGGING,
    DEFAULT_MARKET_TIMEZONE,
    DEFAULT_MONARCH_POLL_INTERVAL,
    DEFAULT_PAYCHECK_THRESHOLD,
    DEFAULT_PAYCHECK_WINDOWS,
    DEFAULT_401K_QUIET_START,
    DEFAULT_401K_QUIET_END,
    DEFAULT_401K_RETRY_INTERVAL,
    MARKET_TIMEZONES,
    PROVIDERS,
)
from .providers import get_provider, validate_symbols

_LOGGER = logging.getLogger(__name__)

TIME_OF_DAY = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")


def _invalid_pay_windows(value: str) -> bool:
    """Whether a pay-window string has no usable segment."""
    from .market import parse_pay_windows

    return bool(str(value or "").strip()) and not parse_pay_windows(value)

POLL_OPTIONS = {
    "60": "1 minute",
    "300": "5 minutes",
    "600": "10 minutes",
    "900": "15 minutes",
    "1800": "30 minutes",
}

MONARCH_POLL_OPTIONS = {
    "5": "5 minutes",
    "10": "10 minutes",
    "15": "15 minutes",
    "30": "30 minutes",
    "60": "1 hour",
}

RETRY_OPTIONS = {
    "15": "15 minutes",
    "30": "30 minutes",
    "60": "1 hour",
}


class HAStockAppConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 2

    def __init__(self) -> None:
        self._data: dict = {}
        self._monarch_accounts: list = []

    async def async_step_user(self, user_input=None):
        errors = {}

        if user_input is not None:
            stocks_raw = user_input.get(CONF_STOCKS, "")
            stocks = [s.strip().upper() for s in stocks_raw.split(",") if s.strip()]
            if not stocks:
                errors[CONF_STOCKS] = "no_stocks"
            else:
                invalid = validate_symbols(stocks)
                if invalid:
                    errors[CONF_STOCKS] = "invalid_symbols"
                else:
                    self._data = {
                        CONF_API_PROVIDER: user_input[CONF_API_PROVIDER],
                        CONF_API_KEY: user_input[CONF_API_KEY],
                        CONF_STOCKS: stocks,
                        CONF_POLL_FREQUENCY: user_input.get(CONF_POLL_FREQUENCY, str(DEFAULT_POLL_FREQUENCY)),
                        CONF_ALERT_THRESHOLD: user_input.get(CONF_ALERT_THRESHOLD, DEFAULT_ALERT_THRESHOLD),
                    }
                    return await self.async_step_test_stock_api()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_API_PROVIDER, default=DEFAULT_PROVIDER): vol.In(PROVIDERS),
                vol.Required(CONF_API_KEY): str,
                vol.Required(CONF_STOCKS, default="VOO, VTI"): str,
                vol.Optional(CONF_POLL_FREQUENCY, default=str(DEFAULT_POLL_FREQUENCY)): vol.In(POLL_OPTIONS),
                vol.Optional(CONF_ALERT_THRESHOLD, default=DEFAULT_ALERT_THRESHOLD): vol.All(
                    vol.Coerce(float), vol.Range(min=0.1, max=100.0)
                ),
            }),
            errors=errors,
        )

    async def async_step_test_stock_api(self, user_input=None):
        provider = get_provider(
            self._data[CONF_API_PROVIDER],
            self._data[CONF_API_KEY],
            async_get_clientsession(self.hass),
        )

        test_symbol = self._data[CONF_STOCKS][0]
        try:
            quote = await provider.get_quote(test_symbol)
        except Exception:
            # Any failure here must land on the retry step rather than
            # aborting the flow with an unhandled-error screen.
            _LOGGER.exception("Stock API test failed for %s", test_symbol)
            quote = None

        if quote is None:
            return self.async_show_form(
                step_id="test_stock_api_failed",
                data_schema=vol.Schema({}),
                description_placeholders={
                    "provider": PROVIDERS.get(self._data[CONF_API_PROVIDER], self._data[CONF_API_PROVIDER]),
                    "symbol": test_symbol,
                },
            )

        return self.async_show_form(
            step_id="test_stock_api_success",
            data_schema=vol.Schema({}),
            description_placeholders={
                "provider": PROVIDERS.get(self._data[CONF_API_PROVIDER], self._data[CONF_API_PROVIDER]),
                "symbol": quote.symbol,
                "price": f"${quote.current_price:.2f}",
                "change": f"{'+' if quote.change >= 0 else ''}{quote.change:.2f}",
            },
        )

    async def async_step_test_stock_api_success(self, user_input=None):
        return await self.async_step_monarch()

    async def async_step_test_stock_api_failed(self, user_input=None):
        return await self.async_step_user()

    async def async_step_monarch(self, user_input=None):
        errors = {}
        if user_input is not None:
            if user_input.get(CONF_MONARCH_ENABLED):
                email = user_input.get(CONF_MONARCH_EMAIL, "").strip()
                password = user_input.get(CONF_MONARCH_PASSWORD, "").strip()
                if not email or not password:
                    errors["base"] = "monarch_missing_credentials"
                else:
                    self._data[CONF_MONARCH_ENABLED] = True
                    self._data[CONF_MONARCH_EMAIL] = email
                    self._data[CONF_MONARCH_PASSWORD] = password
                    self._data[CONF_MONARCH_MFA_SECRET] = user_input.get(CONF_MONARCH_MFA_SECRET, "").strip()
                    return await self.async_step_test_monarch()
            else:
                self._data[CONF_MONARCH_ENABLED] = False
                return self.async_create_entry(title="HA Stock App", data=self._data)

        return self.async_show_form(
            step_id="monarch",
            data_schema=vol.Schema({
                vol.Optional(CONF_MONARCH_ENABLED, default=False): bool,
                vol.Optional(CONF_MONARCH_EMAIL, default=""): str,
                vol.Optional(CONF_MONARCH_PASSWORD, default=""): str,
                vol.Optional(CONF_MONARCH_MFA_SECRET, default=""): str,
            }),
            errors=errors,
        )

    async def async_step_test_monarch(self, user_input=None):
        try:
            from .monarch import MonarchClient
        except ImportError:
            return self.async_show_form(
                step_id="test_monarch_failed",
                data_schema=vol.Schema({}),
                description_placeholders={
                    "error": "monarchmoney package not installed. Install with: pip install monarchmoney",
                },
            )

        client = MonarchClient(
            self._data[CONF_MONARCH_EMAIL],
            self._data[CONF_MONARCH_PASSWORD],
            mfa_secret=self._data.get(CONF_MONARCH_MFA_SECRET, ""),
            session_dir=self.hass.config.path(f".storage/{DOMAIN}"),
        )

        if await client.authenticate():
            accounts = await client.get_accounts()
            self._monarch_accounts = accounts
            return self.async_show_form(
                step_id="test_monarch_success",
                data_schema=vol.Schema({}),
                description_placeholders={
                    "account_count": str(len(accounts)),
                },
            )

        mfa_hint = ""
        if not self._data.get(CONF_MONARCH_MFA_SECRET):
            mfa_hint = " If your account has MFA enabled, provide your TOTP secret key."

        return self.async_show_form(
            step_id="test_monarch_failed",
            data_schema=vol.Schema({}),
            description_placeholders={
                "error": f"Login failed. Check your credentials.{mfa_hint}",
            },
        )

    async def async_step_test_monarch_success(self, user_input=None):
        return await self.async_step_select_accounts()

    async def async_step_select_accounts(self, user_input=None):
        if user_input is not None:
            self._data[CONF_MONARCH_ACCOUNTS] = user_input.get(CONF_MONARCH_ACCOUNTS, [])
            return self.async_create_entry(title="HA Stock App", data=self._data)

        account_options = {
            acct.id: f"{acct.institution} - {acct.name}"
            for acct in self._monarch_accounts
        }
        return self.async_show_form(
            step_id="select_accounts",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_MONARCH_ACCOUNTS,
                    default=[],
                ): cv.multi_select(account_options),
            }),
        )

    async def async_step_test_monarch_failed(self, user_input=None):
        return await self.async_step_monarch()

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return HAStockAppOptionsFlow(config_entry)


class HAStockAppOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry
        self._options: dict = {}

    async def async_step_init(self, user_input=None):
        errors = {}
        if user_input is not None:
            stocks = [s.strip().upper() for s in user_input.get(CONF_STOCKS, "").split(",") if s.strip()]
            invalid = validate_symbols(stocks)
            if invalid:
                errors[CONF_STOCKS] = "invalid_symbols"
            elif not stocks:
                errors[CONF_STOCKS] = "no_stocks"
            else:
                new_data = {**self._config_entry.data}
                new_data[CONF_STOCKS] = stocks
                new_data[CONF_POLL_FREQUENCY] = user_input.get(CONF_POLL_FREQUENCY, str(DEFAULT_POLL_FREQUENCY))
                new_data[CONF_ALERT_THRESHOLD] = user_input.get(CONF_ALERT_THRESHOLD, DEFAULT_ALERT_THRESHOLD)

                monarch_enabled = user_input.get(CONF_MONARCH_ENABLED, False)
                new_data[CONF_MONARCH_ENABLED] = monarch_enabled
                if monarch_enabled:
                    email = user_input.get(CONF_MONARCH_EMAIL, "").strip()
                    password = user_input.get(CONF_MONARCH_PASSWORD, "").strip()
                    mfa = user_input.get(CONF_MONARCH_MFA_SECRET, "").strip()
                    if email:
                        new_data[CONF_MONARCH_EMAIL] = email
                    if password:
                        new_data[CONF_MONARCH_PASSWORD] = password
                    if mfa:
                        new_data[CONF_MONARCH_MFA_SECRET] = mfa

                self.hass.config_entries.async_update_entry(self._config_entry, data=new_data)

                self._options = {**self._config_entry.options}
                self._options.update({
                    CONF_ENABLE_MARKET_HOURS: user_input.get(CONF_ENABLE_MARKET_HOURS, DEFAULT_ENABLE_MARKET_HOURS),
                    CONF_ENABLE_EOD_SUMMARY: user_input.get(CONF_ENABLE_EOD_SUMMARY, DEFAULT_ENABLE_EOD_SUMMARY),
                    CONF_ENABLE_MARKET_OPEN_EVENT: user_input.get(CONF_ENABLE_MARKET_OPEN_EVENT, DEFAULT_ENABLE_MARKET_OPEN_EVENT),
                    CONF_ENABLE_FINNHUB_SELF_TEST: user_input.get(CONF_ENABLE_FINNHUB_SELF_TEST, DEFAULT_ENABLE_FINNHUB_SELF_TEST),
                })

                self._options[CONF_MARKET_TIMEZONE] = user_input.get(
                    CONF_MARKET_TIMEZONE, DEFAULT_MARKET_TIMEZONE
                )

                self._options[CONF_ENABLE_DEBUG_LOGGING] = user_input.get(
                    CONF_ENABLE_DEBUG_LOGGING, DEFAULT_ENABLE_DEBUG_LOGGING
                )

                if monarch_enabled:
                    self._options[CONF_MONARCH_POLL_INTERVAL] = user_input.get(
                        CONF_MONARCH_POLL_INTERVAL, str(DEFAULT_MONARCH_POLL_INTERVAL)
                    )
                    self._options[CONF_ENABLE_MONARCH_DOUBLE_REFRESH] = user_input.get(
                        CONF_ENABLE_MONARCH_DOUBLE_REFRESH, DEFAULT_ENABLE_MONARCH_DOUBLE_REFRESH
                    )
                    self._options[CONF_ENABLE_PAYCHECK_DETECTION] = user_input.get(
                        CONF_ENABLE_PAYCHECK_DETECTION, DEFAULT_ENABLE_PAYCHECK_DETECTION
                    )
                    self._options[CONF_ENABLE_401K_REPORTING] = user_input.get(
                        CONF_ENABLE_401K_REPORTING, DEFAULT_ENABLE_401K_REPORTING
                    )
                    return await self.async_step_select_accounts()

                needs_advanced = (
                    self._options.get(CONF_ENABLE_PAYCHECK_DETECTION, False)
                    or self._options.get(CONF_ENABLE_401K_REPORTING, False)
                )
                if needs_advanced:
                    return await self.async_step_advanced()

                return self.async_create_entry(title="", data=self._options)

        current = self._config_entry.data
        opts = self._config_entry.options

        saved_poll = str(current.get(CONF_POLL_FREQUENCY, DEFAULT_POLL_FREQUENCY))

        schema = vol.Schema({
            vol.Required(CONF_STOCKS, default=", ".join(current.get(CONF_STOCKS, []))): str,
            vol.Required(CONF_POLL_FREQUENCY, default=saved_poll): vol.In(POLL_OPTIONS),
            vol.Optional(CONF_ALERT_THRESHOLD, default=current.get(CONF_ALERT_THRESHOLD, DEFAULT_ALERT_THRESHOLD)): vol.All(
                vol.Coerce(float), vol.Range(min=0.1, max=100.0)
            ),
            vol.Optional(CONF_MARKET_TIMEZONE, default=opts.get(CONF_MARKET_TIMEZONE, DEFAULT_MARKET_TIMEZONE)): vol.In(MARKET_TIMEZONES),
            vol.Optional(CONF_ENABLE_MARKET_HOURS, default=opts.get(CONF_ENABLE_MARKET_HOURS, DEFAULT_ENABLE_MARKET_HOURS)): bool,
            vol.Optional(CONF_ENABLE_EOD_SUMMARY, default=opts.get(CONF_ENABLE_EOD_SUMMARY, DEFAULT_ENABLE_EOD_SUMMARY)): bool,
            vol.Optional(CONF_ENABLE_MARKET_OPEN_EVENT, default=opts.get(CONF_ENABLE_MARKET_OPEN_EVENT, DEFAULT_ENABLE_MARKET_OPEN_EVENT)): bool,
            vol.Optional(CONF_ENABLE_FINNHUB_SELF_TEST, default=opts.get(CONF_ENABLE_FINNHUB_SELF_TEST, DEFAULT_ENABLE_FINNHUB_SELF_TEST)): bool,
            vol.Optional(CONF_MONARCH_ENABLED, default=current.get(CONF_MONARCH_ENABLED, False)): bool,
            vol.Optional(CONF_MONARCH_EMAIL, default=current.get(CONF_MONARCH_EMAIL, "")): str,
            vol.Optional(CONF_MONARCH_PASSWORD, default=""): str,
            vol.Optional(CONF_MONARCH_MFA_SECRET, default=""): str,
        })

        if current.get(CONF_MONARCH_ENABLED, False):
            monarch_poll = str(opts.get(CONF_MONARCH_POLL_INTERVAL) or current.get(CONF_MONARCH_POLL_INTERVAL) or DEFAULT_MONARCH_POLL_INTERVAL)
            schema = schema.extend({
                vol.Required(CONF_MONARCH_POLL_INTERVAL, default=monarch_poll): vol.In(MONARCH_POLL_OPTIONS),
                vol.Optional(CONF_ENABLE_MONARCH_DOUBLE_REFRESH, default=opts.get(CONF_ENABLE_MONARCH_DOUBLE_REFRESH, DEFAULT_ENABLE_MONARCH_DOUBLE_REFRESH)): bool,
                vol.Optional(CONF_ENABLE_PAYCHECK_DETECTION, default=opts.get(CONF_ENABLE_PAYCHECK_DETECTION, DEFAULT_ENABLE_PAYCHECK_DETECTION)): bool,
                vol.Optional(CONF_ENABLE_401K_REPORTING, default=opts.get(CONF_ENABLE_401K_REPORTING, DEFAULT_ENABLE_401K_REPORTING)): bool,
            })

        schema = schema.extend({
            vol.Optional(CONF_ENABLE_DEBUG_LOGGING, default=opts.get(CONF_ENABLE_DEBUG_LOGGING, DEFAULT_ENABLE_DEBUG_LOGGING)): bool,
        })

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_select_accounts(self, user_input=None):
        if user_input is not None:
            new_data = {**self._config_entry.data}
            new_data[CONF_MONARCH_ACCOUNTS] = user_input.get(CONF_MONARCH_ACCOUNTS, [])
            self.hass.config_entries.async_update_entry(self._config_entry, data=new_data)

            needs_advanced = (
                self._options.get(CONF_ENABLE_PAYCHECK_DETECTION, False)
                or self._options.get(CONF_ENABLE_401K_REPORTING, False)
            )
            if needs_advanced:
                return await self.async_step_advanced()
            return self.async_create_entry(title="", data=self._options)

        account_options: dict[str, str] = {}
        data = self.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id, {})
        coordinator = data.get("monarch_coordinator")
        if coordinator and coordinator.data:
            for acct_id, acct in coordinator.data.get("accounts", {}).items():
                account_options[acct_id] = f"{acct.institution} - {acct.name}"

        if not account_options:
            needs_advanced = (
                self._options.get(CONF_ENABLE_PAYCHECK_DETECTION, False)
                or self._options.get(CONF_ENABLE_401K_REPORTING, False)
            )
            if needs_advanced:
                return await self.async_step_advanced()
            return self.async_create_entry(title="", data=self._options)

        current_selected = self._config_entry.data.get(
            CONF_MONARCH_ACCOUNTS, []
        )
        return self.async_show_form(
            step_id="select_accounts",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_MONARCH_ACCOUNTS,
                    default=current_selected,
                ): cv.multi_select(account_options),
            }),
        )

    async def async_step_advanced(self, user_input=None):
        errors = {}
        if user_input is not None:
            # Both of these are free-form text. Reject a typo here rather than
            # letting it reach the parsers, which fall back silently.
            if self._options.get(CONF_ENABLE_401K_REPORTING, False):
                for key in (CONF_401K_QUIET_START, CONF_401K_QUIET_END):
                    if not TIME_OF_DAY.match(str(user_input.get(key, "")).strip()):
                        errors[key] = "invalid_time"
            if self._options.get(CONF_ENABLE_PAYCHECK_DETECTION, False):
                if _invalid_pay_windows(user_input.get(CONF_PAYCHECK_WINDOWS, "")):
                    errors[CONF_PAYCHECK_WINDOWS] = "invalid_pay_windows"

        if user_input is not None and not errors:
            if self._options.get(CONF_ENABLE_PAYCHECK_DETECTION, False):
                self._options[CONF_PAYCHECK_ACCOUNT] = user_input.get(
                    CONF_PAYCHECK_ACCOUNT, ""
                )
                self._options[CONF_PAYCHECK_THRESHOLD] = user_input.get(
                    CONF_PAYCHECK_THRESHOLD, DEFAULT_PAYCHECK_THRESHOLD
                )
                self._options[CONF_PAYCHECK_WINDOWS] = user_input.get(
                    CONF_PAYCHECK_WINDOWS, DEFAULT_PAYCHECK_WINDOWS
                )

            if self._options.get(CONF_ENABLE_401K_REPORTING, False):
                self._options[CONF_401K_SENSOR] = user_input.get(CONF_401K_SENSOR, "")
                self._options[CONF_401K_QUIET_START] = user_input.get(
                    CONF_401K_QUIET_START, DEFAULT_401K_QUIET_START
                )
                self._options[CONF_401K_QUIET_END] = user_input.get(
                    CONF_401K_QUIET_END, DEFAULT_401K_QUIET_END
                )
                self._options[CONF_401K_RETRY_INTERVAL] = user_input.get(
                    CONF_401K_RETRY_INTERVAL, str(DEFAULT_401K_RETRY_INTERVAL)
                )

            return self.async_create_entry(title="", data=self._options)

        opts = self._config_entry.options
        schema_dict = {}

        if self._options.get(CONF_ENABLE_PAYCHECK_DETECTION, False):
            account_options: dict[str, str] = {"": "All cash accounts (default)"}
            data = self.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id, {})
            coordinator = data.get("monarch_coordinator")
            if coordinator and coordinator.data:
                for acct_id, acct in coordinator.data.get("accounts", {}).items():
                    account_options[acct_id] = f"{acct.institution} - {acct.name}"
            schema_dict[vol.Optional(CONF_PAYCHECK_ACCOUNT, default=opts.get(CONF_PAYCHECK_ACCOUNT, ""))] = vol.In(account_options)
            schema_dict[vol.Optional(CONF_PAYCHECK_THRESHOLD, default=opts.get(CONF_PAYCHECK_THRESHOLD, DEFAULT_PAYCHECK_THRESHOLD))] = vol.All(
                vol.Coerce(float), vol.Range(min=100.0, max=50000.0)
            )
            schema_dict[vol.Optional(CONF_PAYCHECK_WINDOWS, default=opts.get(CONF_PAYCHECK_WINDOWS, DEFAULT_PAYCHECK_WINDOWS))] = str

        if self._options.get(CONF_ENABLE_401K_REPORTING, False):
            schema_dict[vol.Required(CONF_401K_SENSOR, default=opts.get(CONF_401K_SENSOR, ""))] = str
            schema_dict[vol.Optional(CONF_401K_QUIET_START, default=opts.get(CONF_401K_QUIET_START, DEFAULT_401K_QUIET_START))] = str
            schema_dict[vol.Optional(CONF_401K_QUIET_END, default=opts.get(CONF_401K_QUIET_END, DEFAULT_401K_QUIET_END))] = str
            saved_retry = str(opts.get(CONF_401K_RETRY_INTERVAL) or DEFAULT_401K_RETRY_INTERVAL)
            schema_dict[vol.Required(CONF_401K_RETRY_INTERVAL, default=saved_retry)] = vol.In(RETRY_OPTIONS)

        return self.async_show_form(
            step_id="advanced",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
        )
