"""Withings account API: fetch the scale's `kl` secret (one-time setup).

Transport-agnostic: build the form parameters with these functions and parse the JSON responses,
using any HTTP client (urllib in the CLI tool, aiohttp in Home Assistant). Credentials go only to
Withings over HTTPS and are never stored.
"""

from __future__ import annotations

from dataclasses import dataclass

API = "https://scalews.withings.net/cgi-bin"
LOGIN_URL = f"{API}/auth"
ASSOCIATION_URL = f"{API}/association"
ACCOUNT_URL = f"{API}/account"
COMMON = {"appname": "wiscale", "apppfm": "android", "appliver": "202609240"}
BODY_SMART_MODEL = 16


class AccountError(Exception):
    """Login or lookup failed. `status` is the API status code when there is one."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message if status is None else f"{message} (status {status})")
        self.status = status


class InvalidCredentials(AccountError):
    pass


@dataclass(frozen=True)
class ScaleSecret:
    deviceid: int | None
    model: int | None
    mac: str | None
    kl: str
    accountid: int | None = None


def login_params(email: str, password: str) -> dict:
    return {
        **COMMON,
        "action": "login",
        "email": email,
        "authprovider": "withings",
        "password": password,
        "duration": 900,
        "typename": "mobile",
        "os": "android",
    }


def logout_params(session: str) -> dict:
    return {**COMMON, "action": "logout", "sessionid": session}


def association_params(session: str) -> dict:
    return {**COMMON, "action": "getbyaccountid", "sessionid": session, "type": -1, "enrich": "t"}


def users_params(session: str, accountid: int) -> dict:
    return {
        **COMMON,
        "action": "getuserslist",
        "sessionid": session,
        "accountid": accountid,
        "recurse_use": 1,
        "recurse_devtype": 1,
        "listmask": 5,
        "allusers": "t",
    }


def _find(obj, key):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                yield v
            yield from _find(v, key)
    elif isinstance(obj, list):
        for v in obj:
            yield from _find(v, key)


def parse_login(resp: dict) -> str:
    status = resp.get("status")
    if status != 0:
        raise InvalidCredentials("Withings login failed", status)
    session = next(_find(resp, "sessionid"), None)
    if not session:
        raise AccountError("login returned no session (two-factor authentication?)")
    return session


def parse_scales(resp: dict, model: int | None = BODY_SMART_MODEL) -> list[ScaleSecret]:
    if resp.get("status") != 0:
        raise AccountError("could not list devices", resp.get("status"))
    entries = [e for found in _find(resp, "associations") for e in (found if isinstance(found, list) else [found])]
    scales = []
    for e in entries:
        props = e.get("deviceproperties") or {}
        m = props.get("model", props.get("modelid"))
        m = int(m) if m is not None and str(m).isdigit() else None
        if e.get("kl") and (model is None or m == model):
            scales.append(
                ScaleSecret(e.get("deviceid"), m, props.get("macaddress") or props.get("mac"), e["kl"], e.get("accountid"))
            )
    return scales


def parse_users(resp: dict) -> dict[int, str]:
    """Map Withings user IDs to first names (the IDs the scale tags weigh-ins with)."""
    if resp.get("status") != 0:
        raise AccountError("could not list users", resp.get("status"))
    users = {}
    for found in _find(resp, "users"):
        for u in found if isinstance(found, list) else [found]:
            if isinstance(u, dict) and u.get("id") is not None:
                users[int(u["id"])] = (u.get("firstname") or "").strip() or f"User {u['id']}"
    return users
