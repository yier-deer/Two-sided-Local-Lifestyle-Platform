"""Offline checks for the real verifier. No services or model calls are made."""
import importlib.util
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def verifier():
    path = Path(__file__).with_name("verify_real.py")
    if not path.exists():
        raise AssertionError("真实验收脚本尚未存在")
    spec = importlib.util.spec_from_file_location("scoutbite_verify_real", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class VerifierOfflineTest(unittest.TestCase):
    def instant_check(self):
        module = verifier()
        check = getattr(module, "equal_instant", None)
        self.assertTrue(callable(check), "时间对账应按真实时刻与数据库微秒精度比较")
        return module, check

    def test_database_timestamp_truncation_and_rounding_within_microsecond_are_equivalent(self):
        _, check = self.instant_check()
        check("2026-10-10T15:09:25.451506Z", "2026-10-10T15:09:25.451506400Z", "startAt")
        check("2026-10-10T15:09:25.451507Z", "2026-10-10T15:09:25.451506900Z", "startAt")
        check("2026-10-10T23:09:25.451506+08:00", "2026-10-10T15:09:25.451506Z", "startAt")

    def test_timestamp_precision_tolerance_never_accepts_more_than_one_microsecond(self):
        module, check = self.instant_check()
        with self.assertRaises(module.VerificationFailure):
            check("2026-10-10T15:09:25.451508Z", "2026-10-10T15:09:25.451506900Z", "startAt")
        with self.assertRaises(module.VerificationFailure):
            check("2026-10-11T15:09:25.451506Z", "2026-10-10T15:09:25.451506Z", "endAt")

    def test_timestamp_precision_check_requires_valid_aware_instants(self):
        module, check = self.instant_check()
        for invalid in ("2026-10-10T15:09:25.451506", "invalid", "2026-10-10T15:09:25.1234567890Z", None):
            with self.assertRaises(module.VerificationFailure):
                check(invalid, "2026-10-10T15:09:25.451506Z", "endAt")

    def test_business_fault_never_becomes_expected_rejection(self):
        module = verifier()
        with self.assertRaises(module.VerificationFailure):
            module.expect_code({"code": 50000, "message": "model down", "data": None}, {40001, 40903}, "gate")

    def test_model_fault_is_fail_and_explicit_skip_is_distinct(self):
        module = verifier()
        report = module.Reporter("test-run", "http://localhost:8081")
        report.check("agent", lambda: module.expect_code({"code": 50000}, {0}, "agent"))
        report.skip("other-agent", "--skip-agent")
        self.assertEqual("FAIL", report.summary()["status"])
        only_skip = module.Reporter("test-run", "http://localhost:8081")
        only_skip.check("core", lambda: True)
        only_skip.skip("agent", "--skip-agent")
        self.assertEqual("PASS_WITH_SKIPS", only_skip.summary()["status"])

    def test_report_redacts_tokens_and_auth_passwords(self):
        module = verifier()
        token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.signature1234567890"
        cleaned = module.redact({"token": token, "password": "do-not-print", "safe": "ok", "error": "Bearer " + token})
        serialized = module.json.dumps(cleaned)
        self.assertNotIn(token, serialized)
        self.assertNotIn("do-not-print", serialized)
        self.assertEqual("ok", cleaned["safe"])

    def test_postgres_reader_refuses_mutation(self):
        module = verifier()
        args = module.parser().parse_args(["--db-mode", "native", "--psql", "psql"])
        reader = module.ReadOnlySources(args)
        with self.assertRaises(module.VerificationFailure):
            reader.sql("DELETE FROM orders")
        with self.assertRaises(module.VerificationFailure):
            reader.sql("SELECT 1; UPDATE skus SET stock=0")

    def test_native_readonly_postgres_uses_psql_and_environment(self):
        module = verifier()
        args = module.parser().parse_args(["--db-mode", "native", "--psql", "E:/PSG/bin/psql.exe"])
        reader = module.ReadOnlySources(args)
        with patch.object(module.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="1\n", stderr="")) as run:
            self.assertEqual("1", reader.sql("SELECT 1"))
        command = run.call_args.args[0]
        self.assertEqual("E:/PSG/bin/psql.exe", command[0])
        self.assertIn("default_transaction_read_only=on", run.call_args.kwargs["env"]["PGOPTIONS"])
        self.assertIn("--no-password", command)

    def test_redis_reader_only_allows_read_commands(self):
        module = verifier()
        reader = module.ReadOnlySources(module.parser().parse_args([]))
        with self.assertRaises(module.VerificationFailure):
            reader.redis("SET", "coupon:1:stock", "0")

    def test_evidence_reference_must_exist_and_match_shop(self):
        module = verifier()
        sources = SimpleNamespace(row=lambda sql: {"id": 9, "shop_id": 12})
        with self.assertRaises(module.VerificationFailure):
            module.verify_evidence_ids(["ev-11-9"], sources)
        sources.row = lambda sql: {"id": 9, "shop_id": 11}
        self.assertEqual(["ev-11-9"], module.verify_evidence_ids(["ev-11-9"], sources))

    def test_no_agent_fixture_output_contains_password_value(self):
        module = verifier()
        fixture = module.eval_fixture_entry(2, "13800000001", "SCOUTBITE_EVAL_PASSWORD", 7, 11, 3)
        self.assertEqual("SCOUTBITE_EVAL_PASSWORD", fixture["passwordEnv"])
        self.assertNotIn("password", fixture)

    def test_main_fails_nonzero_and_writes_report_when_service_is_unavailable(self):
        module = verifier()
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "report.json"
            with patch.object(module.Verification, "readiness", side_effect=module.VerificationFailure("HTTP unavailable")), contextlib.redirect_stdout(io.StringIO()):
                exit_code = module.main(["--output", str(output), "--skip-agent"])
            self.assertEqual(1, exit_code)
            data = module.json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual("FAIL", data["status"])
            self.assertEqual(1, data["counts"]["FAIL"])

    def test_skip_agent_mode_does_not_call_any_model_path(self):
        module = verifier()
        report = module.Reporter("test-run", "http://localhost:8081")
        runner = module.Verification(module.parser().parse_args(["--skip-agent"]), report)
        called = []
        for name in ("readiness", "setup", "visibility", "permissions", "checkout", "manual_publish", "reply_and_reconcile"):
            setattr(runner, name, lambda name=name: called.append(name) or {"ok": True})
        runner.restoration = lambda kind: called.append(kind) or {"ok": True}
        runner.agent_publish = lambda: self.fail("Skipped mode must not request a draft")
        runner.recommend = lambda: self.fail("Skipped mode must not request a recommendation")
        runner.merchant_analyze = lambda skill: self.fail("Skipped mode must not request model analysis")
        with contextlib.redirect_stdout(io.StringIO()):
            runner.run()
        self.assertIn("manual_publish", called)
        self.assertEqual("PASS_WITH_SKIPS", report.summary()["status"])
        self.assertEqual(5, report.summary()["counts"]["SKIP"])

    def test_real_model_failure_stays_fail_and_does_not_publish_manually(self):
        module = verifier()
        report = module.Reporter("test-run", "http://localhost:8081")
        runner = module.Verification(module.parser().parse_args([]), report)
        for name in ("readiness", "setup", "visibility", "permissions", "checkout", "recommend"):
            setattr(runner, name, lambda: {"ok": True})
        runner.restoration = lambda kind: {"ok": True}
        runner.merchant_analyze = lambda skill: {"ok": True}
        runner.agent_publish = lambda: module.expect_code({"code": 50000}, {0}, "real draft")
        runner.manual_publish = lambda: self.fail("A model fault cannot become a manual success")
        runner.reply_and_reconcile = lambda: self.fail("No successful review may be fabricated")
        with contextlib.redirect_stdout(io.StringIO()):
            runner.run()
        self.assertEqual("FAIL", report.summary()["status"])
        self.assertEqual(1, report.summary()["counts"]["FAIL"])

    def test_prepare_eval_emits_real_api_ids_and_password_environment_names(self):
        module = verifier()
        with tempfile.TemporaryDirectory() as temp:
            args = module.parser().parse_args(["--prepare-eval", "--eval-fixtures", str(Path(temp) / "fixtures.json")])
            runner = module.Verification(args, module.Reporter("test-run", "http://localhost:8081"))
            runner.actors["merchant"] = {"userId": 5}
            runner.records["shop"] = {"id": 11}
            actors = iter([{"userId": 8, "phone": "13800000001"}, {"userId": 9, "phone": "13800000002"}])
            runner.register = lambda **kw: next(actors)
            runner.new_sku = lambda *args: {"id": 7, "shopId": 11}
            runner.order = lambda actor, sku, label: ({"id": 21 + int(label[-1])}, "key")
            runner.api = SimpleNamespace(ok=lambda *args, **kwargs: {})
            runner.sources = SimpleNamespace(scalar=lambda sql: "REDEEMED" if "SELECT status" in sql else "0")
            with patch.dict(module.os.environ, {"SCOUTBITE_EVAL_FIXTURE_PASSWORD": "private-fixture-password"}):
                result = runner.prepare_eval()
            data_text = args.eval_fixtures.read_text(encoding="utf-8")
            data = module.json.loads(data_text)
            self.assertNotIn("private-fixture-password", data_text)
            self.assertEqual([21, 22, 23], data["review"]["orderIds"])
            self.assertEqual("SCOUTBITE_EVAL_FIXTURE_PASSWORD", data["review"]["account"]["passwordEnv"])
            self.assertEqual(11, data["merchant"]["shopIds"]["41"])
            self.assertEqual(9, result["coldUserId"])


if __name__ == "__main__":
    unittest.main()
