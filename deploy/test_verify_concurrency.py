"""Offline concurrency verifier tests; no project services are contacted."""
import contextlib
import importlib.util
import io
from pathlib import Path
import threading
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch


def verifier():
    path = Path(__file__).with_name("verify_concurrency.py")
    if not path.exists():
        raise AssertionError("独立并发验收脚本尚未存在")
    spec = importlib.util.spec_from_file_location("verify_concurrency_tested", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ConcurrencyOfflineTest(unittest.TestCase):
    def test_all_workers_are_live_before_any_request_is_released(self):
        module = verifier()
        second_barrier = threading.Barrier(8, timeout=3)
        threads = set()
        lock = threading.Lock()
        def operation(index):
            with lock:
                threads.add(threading.get_ident())
            second_barrier.wait()
            return {"code": 0, "data": {"id": index}}
        results = module.concurrent_batch(list(range(8)), operation, barrier_timeout=3)
        self.assertEqual(8, len(results))
        self.assertEqual(8, len(threads), "每个请求独立线程，不能被连接池串行化")
        self.assertTrue(all(item["code"] == 0 for item in results))

    def test_server_errors_and_transport_errors_are_not_business_rejections(self):
        module = verifier()
        summary = module.summarize_outcomes([{"code": 0}, {"code": 40902}, {"code": 50000}, {"error": "transport timeout"}])
        self.assertEqual(1, summary["success"])
        self.assertEqual(1, summary["rejected"])
        self.assertEqual(1, summary["unexpected"])
        self.assertEqual(1, summary["exceptions"])

    def test_overclaim_never_passes_total_assertion(self):
        module = verifier()
        with self.assertRaises(module.real.VerificationFailure):
            module.assert_outcomes([{"code": 0}] * 101 + [{"code": 40902}] * 99, 100, 100)

    def test_deadline_poll_stops_after_the_actual_order_is_closed(self):
        module = verifier()
        states = iter(["CREATED", "CREATED", "CANCELLED_TIMEOUT"])
        clock = [0.0]
        def delay(seconds):
            self.assertLessEqual(seconds, 1)
            clock[0] += seconds
        result = module.poll_until_closed(lambda: next(states), max_wait=5, monotonic=lambda: clock[0], sleep=delay)
        self.assertEqual("CANCELLED_TIMEOUT", result)
        self.assertLessEqual(clock[0], 5)

    def test_poll_timeout_is_failure_and_never_sleeps_past_bound(self):
        module = verifier()
        clock = [0.0]
        def delay(seconds):
            clock[0] += seconds
        with self.assertRaises(module.real.VerificationFailure):
            module.poll_until_closed(lambda: "CREATED", max_wait=2, monotonic=lambda: clock[0], sleep=delay)
        self.assertEqual(2, clock[0])

    def test_paid_order_cannot_be_counted_as_successful_timeout_close(self):
        module = verifier()
        with self.assertRaises(module.real.VerificationFailure):
            module.poll_until_closed(lambda: "PAID", max_wait=2)

    def test_defaults_are_real_native_sources_and_isolated_timeout_service(self):
        module = verifier()
        args = module.parser().parse_args([])
        self.assertEqual("native", args.db_mode)
        self.assertEqual("http://localhost:8082", args.timeout_shop_url)
        self.assertEqual(40, args.prepare_workers)
        self.assertEqual(30, args.max_timeout_wait)
        self.assertEqual("concurrency-20261010.json", args.output.name)

    def test_generated_idempotency_keys_fit_sixty_four_characters(self):
        module = verifier()
        self.assertLessEqual(len(module.idem_key("20261010T150000-abcdef", "timeout-coupon", 199)), 64)
        with self.assertRaises(module.real.VerificationFailure):
            module.idem_key("x" * 70, "oversize", 1)

    def test_false_or_unknown_write_results_are_retained_for_review(self):
        module = verifier()
        report = module.ConcurrencyReporter("test-run", "http://localhost:8081")
        runner = module.ConcurrencyVerification(module.parser().parse_args([]), report)
        runner.coupon = lambda label, total: {"id": 9, "total": 100}
        runner.users = [{"userId": index + 1, "token": "in-memory-only"} for index in range(200)]
        runner.sources = SimpleNamespace(scalar=lambda sql: "0")
        outcomes = [{"index": index, "code": 0, "data": {"userCouponId": index + 1}} for index in range(99)]
        outcomes += [{"index": 99, "error": "UNKNOWN: write may have committed"}]
        outcomes += [{"index": index, "code": 40902} for index in range(100, 200)]
        with patch.object(module, "concurrent_batch", return_value=outcomes):
            with self.assertRaises(module.real.VerificationFailure):
                runner.claims()
        self.assertEqual(1, report.resources["claim200"]["summary"]["exceptions"])
        self.assertIn("UNKNOWN", report.resources["claim200"]["outcomes"][99]["error"])

    def test_unavailable_real_service_produces_nonzero_and_failed_report(self):
        module = verifier()
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "report.json"
            with patch.object(module.ConcurrencyVerification, "readiness", side_effect=module.real.VerificationFailure("timeout service down")), contextlib.redirect_stdout(io.StringIO()):
                status = module.main(["--output", str(output)])
            report = module.real.json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(1, status)
            self.assertEqual("FAIL", report["status"])
            self.assertEqual(1, report["counts"]["FAIL"])


if __name__ == "__main__":
    unittest.main()
