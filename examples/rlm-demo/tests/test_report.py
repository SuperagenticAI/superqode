from __future__ import annotations

import unittest
from pathlib import Path

from deploy_audit.parser import parse_events
from deploy_audit.report import build_release_health

FIXTURE = Path(__file__).parents[1] / "fixtures" / "deployments.jsonl"


class ReleaseHealthTests(unittest.TestCase):
    def test_parser_counts_malformed_records_without_losing_valid_events(self):
        events, ignored = parse_events(
            [
                '{"service":"api","deployment_id":"d1","attempt":1,'
                '"status":"succeeded","duration_seconds":10,'
                '"timestamp":"2026-08-10T09:00:00Z"}',
                "not-json",
                '{"service":"","deployment_id":"d2","attempt":1,'
                '"status":"failed","duration_seconds":1,'
                '"timestamp":"2026-08-10T09:01:00Z"}',
            ]
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(ignored, 2)

    def test_report_applies_retry_recency_and_latency_rules(self):
        report = build_release_health(FIXTURE)

        self.assertEqual(report["services"], 4)
        self.assertEqual(report["healthy"], ["api", "worker"])
        self.assertEqual(report["unhealthy"], {"billing": "failed", "web": "slow"})
        self.assertEqual(report["ignored_records"], 2)

    def test_line_order_does_not_override_attempt_and_timestamp(self):
        temporary = Path(self._testMethodName + ".jsonl")
        self.addCleanup(temporary.unlink, missing_ok=True)
        temporary.write_text(
            "\n".join(
                [
                    '{"service":"api","deployment_id":"d2","attempt":2,'
                    '"status":"failed","duration_seconds":20,'
                    '"timestamp":"2026-08-10T10:03:00Z"}',
                    '{"service":"api","deployment_id":"d2","attempt":1,'
                    '"status":"succeeded","duration_seconds":10,'
                    '"timestamp":"2026-08-10T10:04:00Z"}',
                    '{"service":"api","deployment_id":"d1","attempt":1,'
                    '"status":"succeeded","duration_seconds":10,'
                    '"timestamp":"2026-08-10T10:00:00Z"}',
                ]
            ),
            encoding="utf-8",
        )

        self.assertEqual(build_release_health(temporary)["unhealthy"], {"api": "failed"})


if __name__ == "__main__":
    unittest.main()
