"""Fetch your scale's `kl` secret from your own Withings account (one-time setup).

Usage: uv run tools/fetch_kl.py

The scale asks for proof that the client knows `kl`, a per-scale secret that Withings creates
when the scale is added to an account. The official app downloads it from the account API. This
script does the same:
1. Log in with your Withings email and password (typed here, never stored; sent only to Withings
   over HTTPS).
2. List the devices on your account, pick the Body Smart and save its `kl` to `secrets/scale.json`
   (git-ignored, readable only by you).
3. Log out.

Accounts that sign in with Google or Apple need a Withings password first (set one in the app).
Nothing secret is printed.
"""

import getpass
import json
import os
import ssl
import sys
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://scalews.withings.net/cgi-bin"
OUT = Path(__file__).resolve().parent.parent / "secrets" / "scale.json"
BODY_SMART_MODEL = 16
COMMON = {"appname": "wiscale", "apppfm": "android", "appliver": "202609240"}


def ssl_context() -> ssl.SSLContext:
    try:
        import certifi  # noqa: PLC0415 - optional, helps Pythons without system CAs

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def call(endpoint: str, params: dict) -> dict:
    data = urllib.parse.urlencode({**COMMON, **params}).encode()
    req = urllib.request.Request(f"{API}/{endpoint}", data=data, headers={"User-Agent": "withings-local"})
    with urllib.request.urlopen(req, timeout=20, context=ssl_context()) as resp:
        return json.loads(resp.read())


def fail(msg: str, resp: dict | None = None) -> None:
    status = resp.get("status") if isinstance(resp, dict) else None
    print(f"\n✗ {msg}" + (f" (status {status})" if status is not None else ""))
    sys.exit(1)


def find(obj, key):
    """Yield every value stored under `key` anywhere in a JSON tree."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                yield v
            yield from find(v, key)
    elif isinstance(obj, list):
        for v in obj:
            yield from find(v, key)


def main() -> None:
    print("Withings login (sent only to Withings over HTTPS; nothing is stored).")
    email = input("Email: ").strip()
    password = getpass.getpass("Password (hidden): ")

    login = call(
        "auth",
        {
            "action": "login",
            "email": email,
            "authprovider": "withings",
            "password": password,
            "duration": 900,
            "typename": "mobile",
            "os": "android",
        },
    )
    del password
    if login.get("status") != 0:
        fail("Login failed. Check email/password; Google/Apple accounts need a Withings password.", login)
    session = next(find(login, "sessionid"), None)
    if not session:
        fail("Login returned no session (two-factor authentication may be enabled).", login)
    print("✓ Logged in")

    try:
        assoc = call("association", {"action": "getbyaccountid", "sessionid": session, "type": -1, "enrich": "t"})
        if assoc.get("status") != 0:
            fail("Could not list devices.", assoc)
        entries = [a for a in find(assoc, "associations") for a in (a if isinstance(a, list) else [a])]
        print(f"✓ {len(entries)} device association(s) on the account")
        scales = []
        for a in entries:
            props = a.get("deviceproperties") or {}
            model = props.get("model", props.get("modelid"))
            print(f"  - model {model}, type {props.get('type')}, kl {'present' if a.get('kl') else 'missing'}")
            if a.get("kl") and str(model) == str(BODY_SMART_MODEL):
                scales.append(a)
        if not scales:
            fail("No Body Smart (model 16) with a kl secret found on this account.")
        if len(scales) > 1:
            print("! Several Body Smart scales found; saving the first one.")
        a = scales[0]
        props = a.get("deviceproperties") or {}
        record = {
            "model": BODY_SMART_MODEL,
            "deviceid": a.get("deviceid"),
            "mac": props.get("macaddress") or props.get("mac"),
            "kl": a["kl"],
        }
        OUT.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(OUT, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(record, f, indent=2)
        print(f"✓ Saved kl ({len(record['kl'])} characters) to secrets/scale.json (mode 600, git-ignored)")
    finally:
        try:
            call("auth", {"action": "logout", "sessionid": session})
            print("✓ Logged out")
        except Exception:  # noqa: BLE001 - logout is best effort
            pass


if __name__ == "__main__":
    main()
