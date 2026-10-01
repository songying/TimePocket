"""Focused security tests for Telegram Mini Apps authentication."""

import hashlib
import hmac
import json
import unittest
from unittest.mock import patch
from urllib.parse import parse_qsl, urlencode

from auth import validate_init_data


TOKEN = "123456789:example-test-token-not-a-secret"
NOW = 1_800_000_000
OWNER = 1234567890123


def signed_data(fields=None, *, token=TOKEN):
    payload = {
        "query_id": "test-query",
        "user": json.dumps({"id": OWNER, "first_name": "Test"}),
        "auth_date": str(NOW),
    }
    if fields:
        payload.update(fields)
    canonical = "\n".join(f"{key}={value}" for key, value in sorted(payload.items()))
    secret = hmac.digest(b"WebAppData", token.encode(), "sha256")
    payload["hash"] = hmac.digest(secret, canonical.encode(), "sha256").hex()
    return urlencode(payload)


class ValidateInitDataTests(unittest.TestCase):
    def validate(self, raw, **kwargs):
        options = {"token": TOKEN, "owners": {OWNER}, "now": NOW}
        options.update(kwargs)
        return validate_init_data(raw, **options)

    def test_valid_data_returns_integer_user_id(self):
        self.assertEqual(self.validate(signed_data()), OWNER)

    def test_optional_signature_is_part_of_hmac(self):
        raw = signed_data({"signature": "signed-third-party-value_-"})
        self.assertEqual(self.validate(raw), OWNER)
        with self.assertRaises(ValueError):
            self.validate(raw.replace("signed-third-party-value_-", "changed"))

    def test_signature_appended_after_signing_is_rejected(self):
        with self.assertRaises(ValueError):
            self.validate(signed_data() + "&signature=unverified")

    def test_field_order_and_url_encoding_do_not_affect_validation(self):
        raw = signed_data({"user": json.dumps({"id": OWNER, "first_name": "A + B & café"}),
                           "optional": ""})
        pairs = list(reversed(parse_qsl(raw, keep_blank_values=True)))
        reordered = urlencode(pairs).replace("+", "%20")
        self.assertEqual(self.validate(reordered), OWNER)

    def test_tampered_data_is_rejected(self):
        with self.assertRaises(ValueError):
            self.validate(signed_data().replace("test-query", "tampered"))

    def test_wrong_token_is_rejected(self):
        with self.assertRaises(ValueError):
            self.validate(signed_data(), token="different-token")

    def test_stale_data_is_rejected(self):
        with self.assertRaises(ValueError):
            self.validate(signed_data({"auth_date": str(NOW - 3601)}))

    def test_maximum_age_boundary_is_allowed(self):
        self.assertEqual(self.validate(signed_data({"auth_date": str(NOW - 3600)})), OWNER)

    def test_configured_maximum_age_is_used(self):
        with self.assertRaises(ValueError):
            self.validate(signed_data({"auth_date": str(NOW - 61)}), max_age=60)
        self.assertEqual(self.validate(signed_data(), max_age=0), OWNER)

    def test_future_data_is_rejected(self):
        with self.assertRaises(ValueError):
            self.validate(signed_data({"auth_date": str(NOW + 31)}))

    def test_future_tolerance_boundary_is_allowed(self):
        self.assertEqual(self.validate(signed_data({"auth_date": str(NOW + 30)})), OWNER)

    def test_real_clock_is_used_when_now_omitted(self):
        with patch("auth.time.time", return_value=NOW):
            self.assertEqual(validate_init_data(signed_data(), TOKEN, {OWNER}), OWNER)

    def test_wrong_owner_or_empty_allowlist_is_rejected(self):
        for owners in ({OWNER + 1}, set()):
            with self.subTest(owners=owners), self.assertRaises(ValueError):
                self.validate(signed_data(), owners=owners)

    def test_duplicate_query_fields_are_rejected(self):
        raw = signed_data()
        digest = dict(parse_qsl(raw))["hash"]
        for extra in ("auth_date=" + str(NOW), "hash=" + digest,
                      "%75ser=%7B%22id%22%3A1%7D", "query_id=duplicate"):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.validate(raw + "&" + extra)

    def test_malformed_queries_raise_value_error(self):
        bad = [None, b"user=x", 1, [], {}, "", "garbage", "a=b&", "=x",
               "a=%", "a=%ZZ", "a=%FF", "a=%C3%28", "a=b&&c=d",
               "a=b&" * 65, "x" * 65537, "hash=" + "x" * 64,
               "hash=" + "é" * 64, "hash=00", "hash=" + "0" * 64]
        for raw in bad:
            with self.subTest(raw=str(raw)[:80]), self.assertRaises(ValueError):
                self.validate(raw)

    def test_signed_newlines_and_invalid_unicode_are_rejected(self):
        for fields in ({"extra": "line\nbreak"}, {"extra\rkey": "value"}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.validate(signed_data(fields))
        with self.assertRaises(ValueError):
            self.validate(signed_data() + "&extra=\ud800")

    def test_missing_required_fields_are_rejected(self):
        pairs = dict(parse_qsl(signed_data()))
        for field in ("user", "auth_date", "hash"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.validate(urlencode({key: value for key, value in pairs.items() if key != field}))

    def test_malformed_signed_dates_are_rejected(self):
        for value in ("", "-1", "+1", "1.0", "1e9", " 1800000000", "١٨٠٠٠٠٠٠٠٠",
                      "NaN", "9" * 5000):
            with self.subTest(value=value[:30]), self.assertRaises(ValueError):
                self.validate(signed_data({"auth_date": value}))

    def test_user_must_have_positive_non_boolean_integer_id(self):
        for value in (True, False, 0, -1, 1.0, str(OWNER), None, [], {}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.validate(signed_data({"user": json.dumps({"id": value})}))

    def test_malformed_signed_user_json_is_rejected(self):
        for value in ("", "{", "null", "[]", "1", '"text"', "{}",
                      '{"id":1,"id":' + str(OWNER) + '}',
                      '{"id":NaN}', '{"id":Infinity}',
                      "[" * 2000 + "]" * 2000):
            with self.subTest(value=value[:80]), self.assertRaises(ValueError):
                self.validate(signed_data({"user": value}))

    def test_invalid_configuration_raises_value_error(self):
        for kwargs in ({"token": ""}, {"token": None}, {"token": "\ud800"},
                       {"owners": None}, {"owners": [OWNER]}, {"owners": {True}},
                       {"owners": {-1}}, {"owners": {str(OWNER)}},
                       {"now": True}, {"now": "bad"}, {"now": float("nan")},
                       {"now": float("inf")}, {"now": -1}, {"now": 10 ** 1000},
                       {"max_age": None}, {"max_age": True}, {"max_age": -1},
                       {"max_age": float("nan")}, {"max_age": float("inf")}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.validate(signed_data(), **kwargs)

    def test_hmac_comparison_uses_constant_time_primitive(self):
        with patch("auth.hmac.compare_digest", wraps=hmac.compare_digest) as compare:
            self.assertEqual(self.validate(signed_data()), OWNER)
            compare.assert_called_once()
            left, right = compare.call_args.args
            self.assertIsInstance(left, bytes)
            self.assertIsInstance(right, bytes)
            self.assertEqual(len(left), hashlib.sha256().digest_size)


if __name__ == "__main__":
    unittest.main()
