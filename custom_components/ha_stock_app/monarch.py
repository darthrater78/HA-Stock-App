from __future__ import annotations

import logging
import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path

from monarchmoney import MonarchMoney, RequireMFAException

_LOGGER = logging.getLogger(__name__)

# The monarchmoney client defaults to a 10s timeout, which is tight for a login
# round trip; a timeout then looks identical to a rejected credential. There is
# no official Monarch API contract to design against -- the package is
# reverse-engineered -- so this is deliberately forgiving.
REQUEST_TIMEOUT = 30

# Backoff floors for a failed login. The package does not handle HTTP 429, so a
# rate-limit answer arrives as an ordinary error. Retrying one of those in a
# minute is pointless and prolongs the lockout, and the limit applies to the
# Monarch account rather than the caller -- so it also affects anything else
# signed in as the same user.
LOGIN_BACKOFF_MIN = 60.0
LOGIN_BACKOFF_RATE_LIMITED = 900.0
LOGIN_BACKOFF_MAX = 3600.0


def _is_rate_limited(exc: Exception) -> bool:
    text = str(exc).lower()
    return "429" in text or "too many requests" in text


class MonarchHoldingsError(Exception):
    """An account's holdings could not be retrieved.

    Distinct from an account genuinely holding nothing, which is an empty
    list. Callers need to tell the two apart: treating a failed fetch as
    "no holdings" is what let a transient error look like a deletion.
    """


@dataclass
class MonarchAccount:
    id: str
    name: str
    institution: str
    balance: float
    account_type: str
    subtype: str
    type_name: str = ""


@dataclass
class MonarchHolding:
    id: str
    ticker: str
    name: str
    quantity: float
    value: float
    cost_basis: float
    price: float
    one_day_change_pct: float
    account_id: str
    account_name: str


class MonarchClient:
    def __init__(
        self,
        email: str,
        password: str,
        mfa_secret: str = "",
        session_dir: str = "",
    ) -> None:
        self._email = email
        self._password = password
        self._mfa_secret = mfa_secret
        self._session_dir = session_dir
        self._mm: MonarchMoney | None = None
        # Monarch rate-limits logins (HTTP 429). A persistent fault must not turn
        # every poll into a fresh login attempt -- that is what turns one broken
        # dependency into an account-wide lockout affecting other integrations.
        self._last_login_attempt: float = 0.0
        self._login_backoff: float = 0.0

    @property
    def _session_file(self) -> Path | None:
        if self._session_dir:
            return Path(self._session_dir) / "monarch_session.json"
        return None

    def _save_session(self) -> None:
        if not self._session_file:
            return
        self._session_file.parent.mkdir(parents=True, exist_ok=True)
        if self._session_file.parent.exists():
            os.chmod(str(self._session_file.parent), stat.S_IRWXU)
        self._mm.save_session(str(self._session_file))
        os.chmod(str(self._session_file), stat.S_IRUSR | stat.S_IWUSR)
        _LOGGER.debug("Monarch Money: session saved successfully")

    def _clear_credentials(self) -> None:
        self._password = ""
        self._mfa_secret = ""

    async def authenticate(self) -> bool:
        now = time.monotonic()
        if self._login_backoff and now - self._last_login_attempt < self._login_backoff:
            remaining = int(self._login_backoff - (now - self._last_login_attempt))
            _LOGGER.debug(
                "Monarch Money: skipping login, backing off for another %ds", remaining
            )
            return False
        self._last_login_attempt = now
        try:
            self._mm = MonarchMoney(timeout=REQUEST_TIMEOUT)

            if self._session_file and self._session_file.exists():
                try:
                    self._mm.load_session(str(self._session_file))
                    accounts = await self._mm.get_accounts()
                    if accounts:
                        _LOGGER.debug("Monarch Money: resumed saved session")
                        self._clear_credentials()
                        return True
                except Exception:
                    _LOGGER.debug("Monarch Money: saved session expired, re-authenticating")

            try:
                if self._mfa_secret:
                    await self._mm.login(self._email, self._password, mfa_secret_key=self._mfa_secret)
                else:
                    await self._mm.login(self._email, self._password)
            except RequireMFAException:
                if self._mfa_secret:
                    await self._mm.multi_factor_authenticate(self._email, self._password, self._mfa_secret)
                else:
                    _LOGGER.error(
                        "Monarch Money requires MFA but no TOTP secret was provided. "
                        "Go to Monarch Settings > Security > Enable MFA and copy the "
                        "'Two-factor text code' into the integration config."
                    )
                    self._mm = None
                    return False

            self._save_session()
            self._clear_credentials()
            self._login_backoff = 0.0
            return True
        except Exception as exc:
            # Exponential backoff, starting higher when the failure looks like a
            # rate limit since those clear on Monarch's clock, not ours.
            floor = LOGIN_BACKOFF_RATE_LIMITED if _is_rate_limited(exc) else LOGIN_BACKOFF_MIN
            self._login_backoff = min(
                max(self._login_backoff * 2, floor), LOGIN_BACKOFF_MAX
            )
            _LOGGER.error(
                "Monarch Money login failed: %s%s (next attempt in %ds)",
                type(exc).__name__,
                " — rate limited by Monarch" if _is_rate_limited(exc) else "",
                int(self._login_backoff),
            )
            _LOGGER.debug("Monarch Money login failure details", exc_info=True)
            self._mm = None
            return False

    async def get_accounts(self) -> list[MonarchAccount]:
        if self._mm is None:
            if not await self.authenticate():
                return []
        try:
            data = await self._mm.get_accounts()
            accounts: list[MonarchAccount] = []
            for acct in data.get("accounts", []):
                accounts.append(
                    MonarchAccount(
                        id=str(acct["id"]),
                        name=acct.get("displayName", acct.get("name", "Unknown")),
                        institution=acct.get("institution", {}).get("name", "Unknown"),
                        balance=float(acct.get("currentBalance", 0)),
                        account_type=acct.get("type", {}).get("display", "Unknown"),
                        subtype=acct.get("subtype", {}).get("display", ""),
                        type_name=acct.get("type", {}).get("name", ""),
                    )
                )
            return accounts
        except Exception as exc:
            # Deliberately does NOT discard the session. A failure here is
            # usually a data or dependency fault, not an expired login -- and
            # discarding it forced a fresh login on the very next poll, which
            # is how a persistent error became a stream of 429s.
            _LOGGER.error("Monarch Money fetch failed: %s", type(exc).__name__)
            _LOGGER.debug("Monarch Money fetch failure details", exc_info=True)
            return []

    async def get_holdings(self, account_id: str, account_name: str = "") -> list[MonarchHolding]:
        if self._mm is None:
            if not await self.authenticate():
                raise MonarchHoldingsError(
                    f"not authenticated while fetching holdings for {account_id}"
                )
        try:
            try:
                acct_id = int(account_id)
            except (ValueError, TypeError):
                acct_id = account_id
            data = await self._mm.get_account_holdings(acct_id)
            holdings: list[MonarchHolding] = []
            portfolio = data.get("portfolio")
            if not portfolio:
                _LOGGER.debug(
                    "No portfolio key in holdings response for account %s. Keys: %s",
                    account_id, list(data.keys()) if isinstance(data, dict) else type(data),
                )
                return []
            agg = portfolio.get("aggregateHoldings")
            if not agg:
                _LOGGER.debug(
                    "No aggregateHoldings in portfolio for account %s. Keys: %s",
                    account_id, list(portfolio.keys()),
                )
                return []
            edges = agg.get("edges", [])
            for edge in edges:
                node = edge.get("node", {})
                security = node.get("security") or {}
                ticker = security.get("ticker", "")
                if not ticker:
                    for h in node.get("holdings", []):
                        if h.get("ticker"):
                            ticker = h["ticker"]
                            break
                name = security.get("name", "")
                if not name and node.get("holdings"):
                    name = node["holdings"][0].get("name", "Unknown")
                holdings.append(
                    MonarchHolding(
                        id=str(node.get("id", "")),
                        ticker=ticker or "N/A",
                        name=name or "Unknown",
                        quantity=float(node.get("quantity", 0)),
                        value=float(node.get("totalValue", 0)),
                        cost_basis=float(node.get("basis") or 0),
                        price=float(
                            security.get("currentPrice")
                            or security.get("closingPrice")
                            or 0
                        ),
                        one_day_change_pct=float(
                            security.get("oneDayChangePercent") or 0
                        ),
                        account_id=str(account_id),
                        account_name=account_name,
                    )
                )
            return holdings
        except Exception as exc:
            _LOGGER.debug("Monarch holdings failure details", exc_info=True)
            raise MonarchHoldingsError(
                f"holdings fetch failed for account {account_id}: {type(exc).__name__}"
            ) from exc

    async def get_cashflow_summary(self) -> dict:
        if self._mm is None:
            if not await self.authenticate():
                return {}
        try:
            return await self._mm.get_cashflow_summary()
        except Exception as exc:
            _LOGGER.error("Monarch cashflow fetch failed: %s", type(exc).__name__)
            _LOGGER.debug("Monarch cashflow failure details", exc_info=True)
            return {}

    async def request_sync(self, timeout: int = 600) -> bool:
        import asyncio

        if self._mm is None:
            _LOGGER.debug("Monarch sync: no active session, authenticating first")
            if not await self.authenticate():
                _LOGGER.warning("Monarch sync: authentication failed, aborting")
                return False
        _LOGGER.debug("Monarch sync: calling request_accounts_refresh_and_wait (timeout=%ds)", timeout)
        try:
            await asyncio.wait_for(
                self._mm.request_accounts_refresh_and_wait(),
                timeout=timeout,
            )
            _LOGGER.debug("Monarch sync: request_accounts_refresh_and_wait returned successfully")
            return True
        except asyncio.TimeoutError:
            _LOGGER.warning("Monarch account sync timed out after %ds", timeout)
            return False
        except Exception as exc:
            _LOGGER.error("Monarch account sync failed: %s", type(exc).__name__)
            _LOGGER.debug("Monarch sync failure details", exc_info=True)
            return False

    @property
    def is_authenticated(self) -> bool:
        return self._mm is not None
