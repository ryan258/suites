import copy
import math
import unittest

from portfolio_suites.contracts import ContractError, generate_sample, validate_contract


class PublishedKeywordValidationTests(unittest.TestCase):
    def test_date_only_is_not_a_date_time(self):
        payload = generate_sample("SourceRecord")
        payload["acquired_at"] = "2026-08-23"
        with self.assertRaisesRegex(ContractError, "RFC 3339"):
            validate_contract("SourceRecord", payload)

    def test_date_time_requires_timezone_and_t_separator(self):
        for timestamp in ("2026-08-23T12:00:00", "2026-08-23 12:00:00+00:00"):
            payload = generate_sample("SourceRecord")
            payload["acquired_at"] = timestamp
            with self.subTest(timestamp=timestamp), self.assertRaises(ContractError):
                validate_contract("SourceRecord", payload)

    def test_min_length_and_minimum_are_enforced(self):
        for field, value in (("media_type", ""), ("origin", ""), ("size_bytes", -1)):
            payload = generate_sample("SourceRecord")
            payload[field] = value
            with self.subTest(field=field), self.assertRaises(ContractError):
                validate_contract("SourceRecord", payload)

    def test_boolean_is_not_an_integer(self):
        payload = generate_sample("SourceRecord")
        payload["size_bytes"] = True
        with self.assertRaisesRegex(ContractError, "JSON integer"):
            validate_contract("SourceRecord", payload)

    def test_non_finite_and_non_string_object_keys_are_not_strict_json(self):
        for bad in ({"bad": math.nan}, {1: "coerced-key"}):
            payload = generate_sample("ExperimentRun")
            payload["parameters"] = copy.deepcopy(bad)
            with self.subTest(bad=bad), self.assertRaises(ContractError):
                validate_contract("ExperimentRun", payload)


if __name__ == "__main__":
    unittest.main()
