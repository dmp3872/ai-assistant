"""Secret access via the macOS Keychain (through the `keyring` library).

Nothing secret is ever read from the repo or .env. On macOS, `keyring` uses the
native Keychain. In CI / non-mac dev, it falls back to an env var of the same
uppercased name so tests can run without a Keychain.
"""
from __future__ import annotations

import os

SERVICE = "radar-assistant"

try:
    import keyring  # type: ignore
    _HAVE_KEYRING = True
except Exception:  # pragma: no cover - keyring optional in some envs
    keyring = None  # type: ignore
    _HAVE_KEYRING = False


def get_secret(account: str, required: bool = False) -> str | None:
    """Fetch a secret by account name (e.g. 'anthropic_api_key')."""
    value: str | None = None
    if _HAVE_KEYRING:
        try:
            value = keyring.get_password(SERVICE, account)
        except Exception:
            value = None
    if value is None:
        value = os.getenv(account.upper())
    if value is None and required:
        raise RuntimeError(
            f"Missing secret '{account}'. Run scripts/setup_wizard.py to store it "
            f"in the macOS Keychain (service='{SERVICE}')."
        )
    return value


def set_secret(account: str, value: str) -> None:
    if not _HAVE_KEYRING:
        raise RuntimeError("keyring/Keychain unavailable; cannot store secret securely.")
    keyring.set_password(SERVICE, account, value)
