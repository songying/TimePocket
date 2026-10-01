"""Server-side validation of Telegram Mini Apps ``initData``.

Reference: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
Only the bot-token HMAC method is implemented here. Its data-check-string
includes ``signature`` when present and excludes only ``hash``.
"""

import hashlib
import hmac
import json
import math
import re
import time
from urllib.parse import parse_qsl


_MAX_INIT_DATA_LENGTH = 65536
_MAX_FIELDS = 64
_FUTURE_TOLERANCE = 30
_BAD_ESCAPE = re.compile(r"%(?![0-9a-fA-F]{2})")
_HASH = re.compile(r"[0-9a-fA-F]{64}\Z")
_AUTH_DATE = re.compile(r"[0-9]{1,20}\Z")


def _number(value, label):
    if type(value) not in (int, float):
        raise ValueError(f"Invalid {label}")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"Invalid {label}") from exc
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"Invalid {label}")
    return result


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate user JSON key")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("Invalid user JSON constant")


def validate_init_data(raw, token, owners: set[int], now: float = None,
                       max_age=3600) -> int:
    """Return the authenticated, allowlisted Telegram user ID.

    ``raw`` must be the unmodified Telegram.WebApp.initData query string.
    Reject invalid input, bad signatures, dates older than ``max_age`` seconds,
    dates over 30 seconds in the future, and users outside ``owners`` by raising
    ``ValueError``. An empty owner allowlist denies every user. Raw credentials
    and signed data are never included in error messages.
    """
    if not isinstance(raw, str) or not raw or len(raw) > _MAX_INIT_DATA_LENGTH:
        raise ValueError("Invalid Telegram init data")
    if not isinstance(token, str) or not token:
        raise ValueError("Invalid bot token configuration")
    if not isinstance(owners, (set, frozenset)) or any(
        type(owner) is not int or owner <= 0 for owner in owners
    ):
        raise ValueError("Invalid owner configuration")
    current_time = _number(time.time() if now is None else now, "current time")
    max_age = _number(max_age, "maximum age")

    if _BAD_ESCAPE.search(raw):
        raise ValueError("Malformed Telegram query encoding")
    try:
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True,
                         encoding="utf-8", errors="strict",
                         max_num_fields=_MAX_FIELDS)
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ValueError("Malformed Telegram query data") from exc

    fields = {}
    for key, value in pairs:
        if not key or key in fields:
            raise ValueError("Empty or duplicate Telegram query field")
        # Line feeds delimit the canonical representation, so do not accept
        # fields that could be interpreted as extra canonical key-value pairs.
        if any(char in key or char in value for char in ("\r", "\n")):
            raise ValueError("Invalid Telegram query field")
        fields[key] = value

    supplied_hash = fields.pop("hash", None)
    if supplied_hash is None or not _HASH.fullmatch(supplied_hash):
        raise ValueError("Missing or malformed Telegram hash")
    if "auth_date" not in fields or "user" not in fields:
        raise ValueError("Missing Telegram authentication fields")

    data_check_string = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    try:
        secret = hmac.new(b"WebAppData", token.encode("utf-8"), hashlib.sha256).digest()
        expected = hmac.new(secret, data_check_string.encode("utf-8"),
                            hashlib.sha256).digest()
    except UnicodeError as exc:
        raise ValueError("Invalid Telegram text encoding") from exc
    if not hmac.compare_digest(expected, bytes.fromhex(supplied_hash)):
        raise ValueError("Invalid Telegram signature")

    if not _AUTH_DATE.fullmatch(fields["auth_date"]):
        raise ValueError("Invalid Telegram authentication date")
    auth_date = int(fields["auth_date"])
    if auth_date > current_time + _FUTURE_TOLERANCE:
        raise ValueError("Telegram authentication date is in the future")
    if current_time - auth_date > max_age:
        raise ValueError("Telegram authentication data has expired")

    try:
        user = json.loads(fields["user"], object_pairs_hook=_unique_object,
                          parse_constant=_reject_constant)
    except (ValueError, TypeError, RecursionError) as exc:
        raise ValueError("Malformed Telegram user data") from exc
    if not isinstance(user, dict):
        raise ValueError("Malformed Telegram user data")
    uid = user.get("id")
    if type(uid) is not int or uid <= 0:
        raise ValueError("Invalid Telegram user ID")
    if uid not in owners:
        raise ValueError("Telegram user is not authorized")
    return uid
