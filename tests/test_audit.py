import json
import os
import tempfile
import unittest

from investment_pipeline.audit import AuditLog, verify_log, verify_records
from investment_pipeline.config import HAIKU_4_5, OPUS_5


class HashChain(unittest.TestCase):
    def test_a_clean_log_verifies(self):
        log = AuditLog()
        log.record("analyst", "stage_output", {"ideas": 3})
        log.record("risk_manager", "enforcement", {"approved": 2})
        ok, problem = verify_records(log.records)
        self.assertTrue(ok, problem)

    def test_editing_a_record_breaks_the_chain(self):
        log = AuditLog()
        log.record("analyst", "stage_output", {"ideas": 3})
        log.record("executor", "order_check", {"accepted": 1})
        tampered = [dict(r) for r in log.records]
        tampered[0]["payload"] = {"ideas": 99}
        ok, problem = verify_records(tampered)
        self.assertFalse(ok)
        self.assertIn("modified", problem)

    def test_removing_a_record_breaks_the_chain(self):
        log = AuditLog()
        for i in range(3):
            log.record("analyst", "note", {"i": i})
        ok, problem = verify_records([log.records[0], log.records[2]])
        self.assertFalse(ok)
        self.assertIn("out of order", problem)

    def test_log_round_trips_through_a_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "nested", "run.jsonl")
            log = AuditLog(path=path)
            log.record("pipeline", "run_started", {"as_of": "2026-09-17"})
            log.record("pipeline", "run_completed", {"ok": True})
            self.assertTrue(os.path.exists(path))
            ok, problem = verify_log(path)
            self.assertTrue(ok, problem)
            with open(path, encoding="utf-8") as fh:
                lines = [json.loads(line) for line in fh if line.strip()]
            self.assertEqual(len(lines), 2)

    def test_file_tampering_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "run.jsonl")
            log = AuditLog(path=path)
            log.record("executor", "order_check", {"accepted": 1})
            log.record("pipeline", "run_completed", {"ok": True})
            with open(path, encoding="utf-8") as fh:
                lines = fh.read().splitlines()
            first = json.loads(lines[0])
            first["payload"]["accepted"] = 42
            lines[0] = json.dumps(first)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")
            ok, _ = verify_log(path)
            self.assertFalse(ok)


class CostAccounting(unittest.TestCase):
    def test_costs_and_tokens_roll_up_by_stage(self):
        log = AuditLog()
        usage = {
            "input_tokens": 100_000,
            "output_tokens": 10_000,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        }
        log.llm_call(
            "analyst",
            model_id=OPUS_5.model_id,
            effort="high",
            usage=usage,
            cost_usd=OPUS_5.cost_usd(usage),
            latency_ms=10,
            request_id="req_1",
            stop_reason="end_turn",
            prompt_sha256="a" * 64,
            response_sha256="b" * 64,
        )
        log.llm_call(
            "reporter",
            model_id=HAIKU_4_5.model_id,
            effort=None,
            usage=usage,
            cost_usd=HAIKU_4_5.cost_usd(usage),
            latency_ms=10,
            request_id="req_2",
            stop_reason="end_turn",
            prompt_sha256="c" * 64,
            response_sha256="d" * 64,
        )
        # Opus 5: 0.1M * $5 + 0.01M * $25 = $0.75. Haiku 4.5: 0.1M * $1 + 0.01M * $5 = $0.15.
        self.assertAlmostEqual(log.cost_by_stage()["analyst"], 0.75, places=6)
        self.assertAlmostEqual(log.cost_by_stage()["reporter"], 0.15, places=6)
        self.assertAlmostEqual(log.total_cost_usd(), 0.90, places=6)
        self.assertEqual(log.total_tokens()["input_tokens"], 200_000)

    def test_cache_reads_are_priced_below_fresh_input(self):
        fresh = OPUS_5.cost_usd({"input_tokens": 1_000_000, "output_tokens": 0})
        cached = OPUS_5.cost_usd({"input_tokens": 0, "cache_read_input_tokens": 1_000_000})
        self.assertAlmostEqual(fresh, 5.0, places=6)
        self.assertAlmostEqual(cached, 0.5, places=6)

    def test_narrative_includes_every_record(self):
        log = AuditLog()
        log.record("analyst", "stage_output", {"idea_count": 2})
        log.record("risk_manager", "override_attempt", {"attempts": [{"symbol": "AAA"}]})
        narrative = log.narrative()
        self.assertIn("analyst/stage_output", narrative)
        self.assertIn("risk_manager/override_attempt", narrative)


if __name__ == "__main__":
    unittest.main()
