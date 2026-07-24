from __future__ import annotations

import logging
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from monarchmoney import MonarchMoney, RequireMFAException

_LOGGER = logging.getLogger(__name__)


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
        try:
            self._mm = MonarchMoney()

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
            return True
        except Exception as exc:
            _LOGGER.error("Monarch Money login failed: %s", type(exc).__name__)
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
            _LOGGER.error("Monarch Money fetch failed: %s", type(exc).__name__)
            _LOGGER.debug("Monarch Money fetch failure details", exc_info=True)
            self._mm = None
            return []

    async def get_holdings(self, account_id: str, account_name: str = "") -> list[MonarchHolding]:
        if self._mm is None:
            if not await self.authenticate():
                return []
        try:
            try:
                acct_id = int(account_id)
            except (ValueError, TypeError):
                acct_id = account_id
            data = await self._mm.get_account_holdings(acct_id)
            holdings: list[MonarchHolding] = []
            edges = (
                data.get("portfolio", {})
                .get("aggregateHoldings", {})
                .get("edges", [])
            )
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
            _LOGGER.error(
                "Monarch holdings fetch failed for account %s: %s",
                account_id,
                type(exc).__name__,
            )
            _LOGGER.debug("Monarch holdings failure details", exc_info=True)
            return []

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

    @property
    def is_authenticated(self) -> bool:
        return self._mm is not None
