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
    CONF_ALERT_COOLDOWN,
    CONF_MONARCH_ACCOUNTS,
    CONF_PL_ACCOUNTS,
    CONF_PL_TICKER_MAP,
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
    DEFAULT_ALERT_COOLDOWN,
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

ALERT_COOLDOWN_OPTIONS = {
    "15": "15 minutes",
    "30": "30 minutes",
    "60": "1 hour",
    "120": "2 hours",
    "240": "4 hours",
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
        self._stock_test_result: str = ""
        self._monarch_error: str = ""

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
                        CONF_ALERT_COOLDOWN: user_input.get(CONF_ALERT_COOLDOWN, str(DEFAULT_ALERT_COOLDOWN)),
                    }
                    return await self._test_stock_api()

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
                vol.Optional(CONF_ALERT_COOLDOWN, default=str(DEFAULT_ALERT_COOLDOWN)): vol.In(ALERT_COOLDOWN_OPTIONS),
            }),
            errors=errors,
        )

    async def _test_stock_api(self):
        provider = get_provider(
            self._data[CONF_API_PROVIDER],
            self._data[CONF_API_KEY],
            async_get_clientsession(self.hass),
        )

        test_symbol = self._data[CONF_STOCKS][0]
        try:
            quote = await provider.get_quote(test_symbol)
        except Exception:
            _LOGGER.exception("Stock API test failed for %s", test_symbol)
            quote = None

        if quote is None:
            self._stock_test_result = ""
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema({
                    vol.Required(CONF_API_PROVIDER, default=self._data[CONF_API_PROVIDER]): vol.In(PROVIDERS),
                    vol.Required(CONF_API_KEY, default=self._data[CONF_API_KEY]): str,
                    vol.Required(CONF_STOCKS, default=", ".join(self._data[CONF_STOCKS])): str,
                    vol.Optional(CONF_POLL_FREQUENCY, default=self._data[CONF_POLL_FREQUENCY]): vol.In(POLL_OPTIONS),
                    vol.Optional(CONF_ALERT_THRESHOLD, default=self._data[CONF_ALERT_THRESHOLD]): vol.All(
                        vol.Coerce(float), vol.Range(min=0.1, max=100.0)
                    ),
                    vol.Optional(CONF_ALERT_COOLDOWN, default=self._data.get(CONF_ALERT_COOLDOWN, str(DEFAULT_ALERT_COOLDOWN))): vol.In(ALERT_COOLDOWN_OPTIONS),
                }),
                errors={CONF_API_KEY: "stock_api_failed"},
            )

        provider_name = PROVIDERS.get(self._data[CONF_API_PROVIDER], self._data[CONF_API_PROVIDER])
        change_str = f"{'+' if quote.change >= 0 else ''}{quote.change:.2f}"
        self._stock_test_result = (
            f"{provider_name} connected — {quote.symbol} at ${quote.current_price:.2f} ({change_str})"
        )
        return await self.async_step_monarch()

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
                    return await self._test_monarch()
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
            description_placeholders={
                "stock_result": self._stock_test_result,
            },
        )

    async def _test_monarch(self):
        from .monarch import MonarchClient

        client = MonarchClient(
            self._data[CONF_MONARCH_EMAIL],
            self._data[CONF_MONARCH_PASSWORD],
            mfa_secret=self._data.get(CONF_MONARCH_MFA_SECRET, ""),
            session_dir=self.hass.config.path(f".storage/{DOMAIN}"),
        )

        if await client.authenticate():
            accounts = await client.get_accounts()
            self._monarch_accounts = accounts
            return await self.async_step_select_accounts()

        return self.async_show_form(
            step_id="monarch",
            data_schema=vol.Schema({
                vol.Optional(CONF_MONARCH_ENABLED, default=True): bool,
                vol.Optional(CONF_MONARCH_EMAIL, default=self._data.get(CONF_MONARCH_EMAIL, "")): str,
                vol.Optional(CONF_MONARCH_PASSWORD, default=""): str,
                vol.Optional(CONF_MONARCH_MFA_SECRET, default=""): str,
            }),
            errors={"base": "monarch_auth_failed"},
            description_placeholders={
                "stock_result": self._stock_test_result,
            },
        )

    async def async_step_select_accounts(self, user_input=None):
        if user_input is not None:
            self._data[CONF_MONARCH_ACCOUNTS] = user_input.get(CONF_MONARCH_ACCOUNTS, [])
            self._data[CONF_PL_ACCOUNTS] = user_input.get(CONF_PL_ACCOUNTS, [])
            return self.async_create_entry(title="HA Stock App", data=self._data)

        account_options = {}
        investment_options = {}
        non_investment_types = {"depository", "credit", "loan", "real_estate", "other"}
        for acct in self._monarch_accounts:
            label = f"{acct.institution} - {acct.name}"
            account_options[acct.id] = label
            if acct.type_name.lower() not in non_investment_types:
                investment_options[acct.id] = label

        return self.async_show_form(
            step_id="select_accounts",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_MONARCH_ACCOUNTS,
                    default=[],
                ): cv.multi_select(account_options),
                vol.Optional(
                    CONF_PL_ACCOUNTS,
                    default=[],
                ): cv.multi_select(investment_options),
            }),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return HAStockAppOptionsFlow(config_entry)


class HAStockAppOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry
        self._options: dict = {}
        self._cached_accounts: dict[str, str] | None = None

    def _get_account_options(self) -> dict[str, str]:
        if self._cached_accounts is not None:
            return self._cached_accounts
        result: dict[str, str] = {}
        data = self.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id, {})
        coordinator = data.get("monarch_coordinator")
        if coordinator and coordinator.data:
            for acct_id, acct in coordinator.data.get("accounts", {}).items():
                result[acct_id] = f"{acct.institution} - {acct.name}"
        self._cached_accounts = result
        return result

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
                new_data[CONF_ALERT_COOLDOWN] = user_input.get(CONF_ALERT_COOLDOWN, str(DEFAULT_ALERT_COOLDOWN))

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
            vol.Optional(CONF_ALERT_COOLDOWN, default=str(current.get(CONF_ALERT_COOLDOWN, DEFAULT_ALERT_COOLDOWN))): vol.In(ALERT_COOLDOWN_OPTIONS),
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
            new_data[CONF_PL_ACCOUNTS] = user_input.get(CONF_PL_ACCOUNTS, [])
            self.hass.config_entries.async_update_entry(self._config_entry, data=new_data)

            if new_data[CONF_PL_ACCOUNTS]:
                return await self.async_step_pl_mapping()

            return await self._after_pl_mapping()

        account_options = self._get_account_options()
        investment_options: dict[str, str] = {}
        entry_data = self.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id, {})
        coordinator = entry_data.get("monarch_coordinator")
        if coordinator and coordinator.data:
            acct_tickers: dict[str, list[str]] = {}
            for h in coordinator.data.get("holdings", {}).values():
                ticker = (h.ticker or h.name[:10]).upper()
                acct_tickers.setdefault(h.account_id, []).append(ticker)

            for acct_id in account_options:
                if acct_id in acct_tickers:
                    acct = coordinator.data.get("accounts", {}).get(acct_id)
                    name = acct.name if acct else acct_id
                    tickers = ", ".join(sorted(set(acct_tickers[acct_id])))
                    investment_options[acct_id] = f"{name} [{tickers}]"

        if not account_options:
            return await self._after_pl_mapping()

        current_selected = self._config_entry.data.get(
            CONF_MONARCH_ACCOUNTS, []
        )
        current_pl = self._config_entry.data.get(
            CONF_PL_ACCOUNTS, []
        )
        return self.async_show_form(
            step_id="select_accounts",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_MONARCH_ACCOUNTS,
                    default=current_selected,
                ): cv.multi_select(account_options),
                vol.Optional(
                    CONF_PL_ACCOUNTS,
                    default=current_pl,
                ): cv.multi_select(investment_options),
            }),
        )

    async def _after_pl_mapping(self):
        needs_advanced = (
            self._options.get(CONF_ENABLE_PAYCHECK_DETECTION, False)
            or self._options.get(CONF_ENABLE_401K_REPORTING, False)
        )
        if needs_advanced:
            return await self.async_step_advanced()
        return self.async_create_entry(title="", data=self._options)

    async def async_step_pl_mapping(self, user_input=None):
        if user_input is not None:
            new_data = {**self._config_entry.data}
            new_data[CONF_PL_TICKER_MAP] = dict(user_input)
            self.hass.config_entries.async_update_entry(
                self._config_entry, data=new_data
            )
            return await self._after_pl_mapping()

        entry_data = self.hass.data.get(DOMAIN, {}).get(
            self._config_entry.entry_id, {}
        )
        monarch_coordinator = entry_data.get("monarch_coordinator")
        stock_coordinator = entry_data.get("stock_coordinator")

        if not monarch_coordinator or not monarch_coordinator.data:
            return await self._after_pl_mapping()

        pl_account_set = set(
            self._config_entry.data.get(CONF_PL_ACCOUNTS, [])
        )
        holdings = [
            h
            for h in monarch_coordinator.data.get("holdings", {}).values()
            if h.account_id in pl_account_set
        ]
        if not holdings:
            return await self._after_pl_mapping()

        stock_symbols = set(
            s.upper() for s in (stock_coordinator.stocks if stock_coordinator else [])
        )
        symbol_options = {"": "None (Monarch fallback)"}
        for s in sorted(stock_symbols):
            symbol_options[s] = s

        existing_map = self._config_entry.data.get(CONF_PL_TICKER_MAP, {})

        seen_tickers: set[str] = set()
        schema_dict = {}
        holding_lines: list[str] = []
        for h in sorted(holdings, key=lambda x: (x.account_name, x.ticker)):
            ticker = (h.ticker or "N/A").upper()
            if ticker in seen_tickers:
                continue
            seen_tickers.add(ticker)

            if ticker in existing_map:
                default = existing_map[ticker]
            elif ticker in stock_symbols:
                default = ticker
            else:
                default = ""

            schema_dict[vol.Optional(ticker, default=default)] = vol.In(
                symbol_options
            )

            accounts_for_ticker = sorted({
                hh.account_name for hh in holdings
                if (hh.ticker or "N/A").upper() == ticker
            })
            acct_str = ", ".join(accounts_for_ticker)
            name = h.name or ticker
            holding_lines.append(f"- **{ticker}** — {name} ({acct_str})")

        if not schema_dict:
            return await self._after_pl_mapping()

        holdings_summary = "\n".join(holding_lines)

        return self.async_show_form(
            step_id="pl_mapping",
            data_schema=vol.Schema(schema_dict),
            description_placeholders={"holdings_summary": holdings_summary},
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
            paycheck_options: dict[str, str] = {"": "All cash accounts (default)"}
            selected = set(self._config_entry.data.get(CONF_MONARCH_ACCOUNTS, []))
            for acct_id, label in self._get_account_options().items():
                if not selected or acct_id in selected:
                    paycheck_options[acct_id] = label
            schema_dict[vol.Optional(CONF_PAYCHECK_ACCOUNT, default=opts.get(CONF_PAYCHECK_ACCOUNT, ""))] = vol.In(paycheck_options)
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
