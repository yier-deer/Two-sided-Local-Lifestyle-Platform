"""Free regression tests for the evaluation CLI's data and model boundaries."""
import base64
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import httpx

import run_eval as ev


def token(user_id):
    payload = base64.urlsafe_b64encode(json.dumps({"sub": str(user_id)}).encode()).decode().rstrip("=")
    return "test." + payload + ".test"


class EvalCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name)
        self.path = self.directory / "fixtures.json"
        self.fixture = {
            "version": 1, "runId": "test-fixture",
            "users": {
                "13700000001": {"phone": "preset-one", "passwordEnv": "EVAL_TEST_PASSWORD"},
                "13700000002": {"phone": "preset-two", "passwordEnv": "EVAL_TEST_PASSWORD"},
                "13611110003": {"phone": "preset-coffee", "passwordEnv": "EVAL_TEST_PASSWORD"},
                "13900000888": {"phone": "cold-user", "passwordEnv": "EVAL_TEST_PASSWORD"},
            },
            "review": {
                "account": {"phone": "order-owner", "passwordEnv": "EVAL_TEST_PASSWORD"},
                "orderIds": [71, 72, 73],
            },
            "merchant": {
                "account": {"phone": "real-merchant", "passwordEnv": "EVAL_TEST_PASSWORD"},
                "shopIds": {str(sid): 4 for sid in (41, 1, 11, 10, 5)},
            },
        }
        self.path.write_text(json.dumps(self.fixture), encoding="utf-8")
        self.account_ids = {
            "preset-one": 1, "preset-two": 2, "preset-coffee": 3,
            "cold-user": 4, "order-owner": 5, "real-merchant": 6,
        }
        self.requests = []
        self.cold_profile = True
        self.client = httpx.Client(base_url="http://shop.test", transport=httpx.MockTransport(self.respond))
        self.patchers = [
            patch.object(ev, "http", self.client),
            patch.object(ev.agent_tools, "_client", self.client),
            patch.object(ev, "SHOP", "http://shop.test"),
            patch.object(ev.llm, "API_KEY", ""),
            patch.dict(os.environ, {"EVAL_TEST_PASSWORD": "never-log-this-password"}),
        ]
        for patcher in self.patchers:
            patcher.start()
        for cache in (ev._shop_cache, ev._review_cache, ev._sku_cache):
            cache.clear()

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.client.close()
        self.tmp.cleanup()

    def respond(self, request):
        self.requests.append((request.method, request.url.path))
        path = request.url.path
        if path == "/actuator/health":
            return httpx.Response(200, json={"status": "UP"})
        if path == "/api/auth/login":
            body = json.loads(request.content)
            uid = self.account_ids.get(body["phone"])
            self.assertEqual(body["password"], "never-log-this-password")
            return httpx.Response(200, json={"code": 0, "data": {
                "token": token(uid), "userId": uid,
                "role": "MERCHANT" if uid == 6 else "USER",
            }})
        if path == "/api/merchant/shops":
            return self.ok([{"id": 4, "ownerId": 6, "status": "approved"}])
        if path.endswith("/profile"):
            return self.ok({"coldStart": self.cold_profile if "/users/4/" in path else False,
                            "topCategories": [] if "/users/4/" in path else ["HOTPOT"]})
        if path.endswith("/facts"):
            return self.ok({"exists": True, "belongToUser": True, "canReview": True,
                            "status": "REDEEMED", "shopId": 4, "shopName": "Real shop",
                            "skuTitle": "Actual two person meal", "priceYuan": 99})
        if path == "/api/shops/nearby" or path == "/internal/shops/search":
            return self.ok([{"id": 4, "name": "Real shop", "category": "HOTPOT", "lat": 30.24, "lng": 120.15}])
        if path == "/api/shops/4/reviews":
            return self.ok([{"id": 18, "orderId": -18, "content": "Real review"}])
        if path == "/api/shops/4":
            return self.ok({"id": 4, "name": "Real shop", "status": "approved", "category": "HOTPOT"})
        if path.endswith("/metrics"):
            return self.ok({"shopId": 4, "totalCustomers": 2, "windowDays": 7})
        if path.endswith("/review-clusters"):
            return self.ok([{"topic": "Actual opinions", "count": 2}])
        if path.endswith("/competitors"):
            return self.ok([{"shopId": 8, "name": "Real competitor", "rating": 4.1}])
        if path.endswith("/evidence"):
            return self.ok({"shopId": 4, "positiveReviews": [{"evidenceId": "ev-4-18", "text": "Real review"}],
                            "negativeReviews": []})
        self.fail("Unexpected data mutation or unsupported request: " + str((request.method, path)))

    @staticmethod
    def ok(data):
        return httpx.Response(200, json={"code": 0, "message": "ok", "data": data})

    def run_cli(self, args):
        with patch("sys.argv", ["run_eval.py", *args]):
            try:
                code = ev.main()
            except SystemExit as error:
                return error.code
        return code if code is not None else 0

    def test_smoke_only_review_selects_three_cases_without_index_errors(self):
        self.assertTrue(hasattr(ev, "select_cases"), "Smoke selection must precede account setup")
        rec, rev, mer = ev.select_cases("smoke", "review")
        self.assertEqual((len(rec), len(rev), len(mer)), (0, 3, 0))

    def test_check_uses_existing_data_without_registering_ordering_or_calling_models(self):
        with patch.object(ev.llm, "chat_json", side_effect=AssertionError("check must be free")), \
             patch.object(ev, "write_report", side_effect=AssertionError("check must not write report")):
            output = io.StringIO()
            with redirect_stdout(output):
                result = self.run_cli(["--check", "--fixtures", str(self.path)])
        self.assertEqual(result, 0)
        self.assertNotIn("never-log-this-password", output.getvalue())
        self.assertNotIn(token(5), output.getvalue())
        self.assertTrue(self.requests)
        self.assertTrue(all(method == "GET" or path == "/api/auth/login" for method, path in self.requests))

    def test_full_without_key_fails_before_any_http_or_generation(self):
        with patch.object(ev.llm, "chat_json", side_effect=AssertionError("must fail before model")):
            result = self.run_cli(["--mode", "full", "--fixtures", str(self.path), "--skip-judge"])
        self.assertEqual(result, 2)
        self.assertEqual(self.requests, [])

    def test_setup_maps_accounts_orders_and_owned_shops_without_mutations(self):
        self.assertTrue(hasattr(ev, "select_cases"), "Fixture setup requires explicit selected cases")
        rec, rev, mer = ev.select_cases("full", None)
        runtime = ev.setup(self.path, rec, rev, mer)
        self.assertEqual(ev.user_id_from_token(runtime["user_tokens"]["13700000001"]), 1)
        self.assertEqual(runtime["review_uid"], 5)
        self.assertEqual(runtime["review_order_ids"], [71, 72, 73])
        self.assertEqual(runtime["merchant_uid"], 6)
        self.assertEqual(runtime["merchant_shops"][41], 4)
        self.assertEqual(runtime["review_titles"][71], "Actual two person meal")
        self.assertFalse(any(path in ("/api/orders", "/api/auth/register") for _, path in self.requests))

    def test_missing_password_environment_fails_without_exposing_password(self):
        with patch.dict(os.environ, {"EVAL_TEST_PASSWORD": ""}), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(self.run_cli(["--check", "--fixtures", str(self.path)]), 2)
        self.assertEqual(self.requests, [])
        self.assertNotIn("never-log-this-password", output.getvalue())

    def test_merchant_fixture_cannot_claim_another_owners_shop(self):
        self.fixture["merchant"]["shopIds"]["41"] = 99
        self.path.write_text(json.dumps(self.fixture), encoding="utf-8")
        with redirect_stdout(io.StringIO()):
            result = self.run_cli(["--check", "--only", "merchant", "--fixtures", str(self.path)])
        self.assertEqual(result, 2)

    def test_failed_model_case_exits_nonzero_and_saves_failure_report(self):
        report = self.directory / "model-failed.md"
        with patch.object(ev.llm, "API_KEY", "configured-test-key"), \
             patch.object(ev, "run_merchant_analyze", return_value={"code": 50000, "message": "provider failed", "data": None}):
            code = self.run_cli(["--mode", "smoke", "--only", "merchant", "--fixtures", str(self.path),
                            "--report", str(report), "--skip-judge"])
        self.assertEqual(code, 1)
        self.assertIn("50000", report.read_text(encoding="utf-8"))
        self.assertIn("0%", report.read_text(encoding="utf-8"))

    def test_cold_clarification_requires_the_actual_graph_cold_start_flag(self):
        self.cold_profile = False
        with redirect_stdout(io.StringIO()):
            result = self.run_cli(["--check", "--fixtures", str(self.path)])
        self.assertEqual(result, 2, "An empty warm profile does not trigger the current graph's clarification")

    def test_review_fixture_rejects_already_reviewed_order(self):
        original = ev.agent_tools.get_order_facts
        with patch.object(ev.agent_tools, "get_order_facts", side_effect=lambda oid, uid: {
                **original(oid, uid), "canReview": False, "status": "REVIEWED"}), redirect_stdout(io.StringIO()):
            result = self.run_cli(["--check", "--only", "review", "--fixtures", str(self.path)])
        self.assertEqual(result, 2)

    def test_full_case_selection_keeps_the_complete_65_sample_suite(self):
        selected = ev.select_cases("full", None)
        self.assertEqual(tuple(len(group) for group in selected), (30, 20, 15))

    def test_recommendation_retains_the_exact_evidence_read_during_generation(self):
        def recommendation(*args):
            ev.agent_tools.get_evidence(4)
            return {"code": 0, "data": {"answer": "No matching result", "shops": []}}
        with patch.object(ev, "run_recommend", side_effect=recommendation):
            result = ev.run_recommend_case({"id": "rec-025", "user": "alias", "message": "question",
                                            "expect": {"expectEmpty": True}}, {"alias": token(1)})
        self.assertTrue(result.evidence, "Judge must retain the evidence used by the generated answer")
        self.assertEqual(result.evidence[0]["positiveReviews"][0]["text"], "Real review")

    def test_swallowed_intent_provider_failure_is_not_a_passing_clarification(self):
        with patch.object(ev.llm, "API_KEY", "configured-test-key"), \
             patch("graph.chat_json", side_effect=RuntimeError("model offline")):
            result = ev.run_recommend_case({"id": "rec-027", "user": "alias", "message": "anywhere",
                                            "expect": {"expectClarify": True}}, {"alias": token(4)})
        self.assertFalse(ev.passed(result), "Model failure must not pass via cold-start fallback")
        self.assertIn("RuntimeError", result.detail)

    def test_judge_uses_recorded_answer_and_evidence_without_rerunning_the_graph(self):
        result = ev.CaseResult("rec-001")
        result.answer = {"answer": "The evaluated answer", "shops": [{"id": 4}], "evidenceIds": ["ev-4-18"]}
        with patch.object(ev, "run_recommend", side_effect=AssertionError("Do not rerun recommendation")), \
             patch.object(ev.llm, "chat_json", return_value={"usefulness": 4, "comparison": 5}) as judge:
            output = ev.run_judge_samples([("The actual user question", result)], {})
        self.assertEqual(len(output), 1, "Judge must evaluate the recorded sample instead of skipping it")
        self.assertEqual(output[0]["usefulness"], 4)
        prompt = judge.call_args.args[1]
        self.assertIn("The evaluated answer", prompt)
        self.assertIn("Real review", prompt)

    def test_judge_failure_remains_an_explicit_failure(self):
        result = ev.CaseResult("rec-001")
        result.answer = {"shops": [{"id": 4}]}
        with patch.object(ev.llm, "chat_json", side_effect=RuntimeError("provider unavailable")):
            output = ev.run_judge_samples([("question", result)], {})
        self.assertEqual(len(output), 1, "Failed judges remain represented in the report")
        self.assertEqual(output[0]["status"], "FAILED")
        self.assertEqual(output[0]["error"], "RuntimeError")

    def test_reports_never_overwrite_existing_evidence(self):
        report = self.directory / "preserve.md"
        report.write_text("Original evidence", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            try:
                ev.write_report("full", [], [], [], True, [], ev.llm.get_usage(), False, report_path=report)
            except TypeError:
                self.fail("CLI needs an explicit exclusive report path")
        self.assertEqual(report.read_text(encoding="utf-8"), "Original evidence")

    def test_report_snapshot_keeps_the_answer_and_evidence_without_credentials(self):
        result = ev.CaseResult("rec-001")
        result.answer = {"answer": "Original evaluated answer", "shops": [{"id": 4}]}
        result.evidence = [{"shopId": 4, "positiveReviews": [{"text": "Actual fact"}]}]
        result.add("api_ok", True)
        report = self.directory / "recorded.md"
        ev.write_report("full", [result], [], [], True, [], ev.llm.get_usage(), False,
                        report_path=report, judge_samples=[("original question", result)])
        saved = json.loads(report.with_suffix(".json").read_text(encoding="utf-8"))
        self.assertEqual(saved["judgeSamples"][0]["answer"], result.answer)
        self.assertEqual(saved["judgeSamples"][0]["evidence"], result.evidence)
        self.assertNotIn("never-log-this-password", json.dumps(saved))
        self.assertNotIn(token(5), json.dumps(saved))

    def test_judge_only_reuses_the_snapshot_without_login_or_regeneration(self):
        snapshot = self.directory / "full.json"
        snapshot.write_text(json.dumps({"version": 1, "judgeSamples": [{
            "id": "rec-001", "question": "original question", "answer": {"answer": "Original evaluated answer", "shops": [{"id": 4}]},
            "evidence": [{"shopId": 4, "positiveReviews": [{"text": "Actual fact"}]}],
        }]}), encoding="utf-8")
        report = self.directory / "judge.md"
        with patch.object(ev.llm, "API_KEY", "configured-test-key"), \
             patch.object(ev.llm, "chat_json", return_value={"usefulness": 4, "comparison": 5}) as judge, \
             patch.object(ev, "run_recommend", side_effect=AssertionError("No generation allowed")), \
             patch.object(ev, "setup", side_effect=AssertionError("No login or facts setup required")):
            code = self.run_cli(["--judge-only", str(snapshot), "--report", str(report)])
        self.assertEqual(code, 0)
        self.assertEqual(self.requests, [])
        self.assertIn("Original evaluated answer", judge.call_args.args[1])
        self.assertIn("Actual fact", judge.call_args.args[1])
        self.assertIn("PASSED", report.read_text(encoding="utf-8"))

    def test_judge_only_model_failure_sets_exit_code_one(self):
        snapshot = self.directory / "full.json"
        snapshot.write_text(json.dumps({"version": 1, "judgeSamples": [{
            "id": "rec-001", "question": "question", "answer": {"answer": "evaluated answer"},
            "evidence": [{"shopId": 4}],
        }]}), encoding="utf-8")
        with patch.object(ev.llm, "API_KEY", "configured-test-key"), \
             patch.object(ev.llm, "chat_json", side_effect=RuntimeError("offline provider")), redirect_stdout(io.StringIO()) as output:
            code = self.run_cli(["--judge-only", str(snapshot), "--report", str(self.directory / "judge-failed.md")])
        self.assertEqual(code, 1)
        self.assertEqual(self.requests, [])
        self.assertIn("Judge：0 通过 / 1 失败", output.getvalue())

    def test_two_default_reports_have_distinct_paths(self):
        with patch.object(ev, "BASE", str(self.directory)):
            first = ev.write_report("full", [], [], [], True, [], ev.llm.get_usage(), False)
            second = ev.write_report("full", [], [], [], True, [], ev.llm.get_usage(), False)
        self.assertNotEqual(first, second)
        self.assertNotEqual(Path(first).name, "latest.md")
        self.assertTrue(Path(first).is_file())
        self.assertTrue(Path(second).is_file())

    def test_order_assignment_is_stable_and_checks_that_orders_own_sku_anchor(self):
        seen = []
        with patch.object(ev, "run_review_draft", side_effect=lambda uid, oid, note, prefer: (
                seen.append(oid) or {"code": 0, "data": {
                    "scores": {"taste": 5, "wait": 3, "env": 4}, "content": "Actual meal", "usedFacts": ["actual"],
                }})):
            try:
                first = ev.run_review_case({"id": "rev-001"}, [71, 72], 5,
                                           {71: "Actual meal", 72: "Different meal"})
                second = ev.run_review_case({"id": "rev-001"}, [71, 72], 5,
                                            {71: "Actual meal", 72: "Different meal"})
            except TypeError:
                self.fail("Content anchor must use the assigned order's own SKU title")
        self.assertEqual(seen[0], seen[1])
        self.assertEqual(first.checks["content_anchor"], seen[0] == 71)
        self.assertEqual(first.checks, second.checks)

    def test_review_result_snapshot_retains_actual_output_and_source_facts(self):
        def draft(uid, oid, note, prefer):
            ev.agent_tools.get_order_facts(oid, uid)
            return {"code": 0, "data": {"content": "Actual meal", "usedFacts": ["Actual order"],
                                        "scores": {"taste": 3, "wait": 3, "env": 3}}}
        with patch.object(ev, "run_review_draft", side_effect=draft):
            result = ev.run_review_case({"id": "rev-001"}, [71], 5, {71: "Actual meal"})
        self.assertIsNotNone(result.answer, "Draft diagnostics must save the complete generated output")
        self.assertEqual(result.answer["content"], "Actual meal")
        self.assertTrue(result.evidence, "Draft diagnostics must save the actual order facts")
        self.assertEqual(result.evidence[0]["skuTitle"], "Actual two person meal")

    def test_merchant_recheck_uses_exact_decimal_values_not_digit_substrings(self):
        def analysis(uid, sid, skill):
            ev.agent_tools.get_metrics(sid)
            return {"code": 0, "data": {"observations": ["Total customers 1"],
                                        "hypotheses": ["可能与活动有关"], "suggestions": ["Continue checking"]}}
        with patch.object(ev, "run_merchant_analyze", side_effect=analysis), \
             patch.object(ev.agent_tools, "get_metrics", return_value={"totalCustomers": 100}):
            result = ev.run_merchant_case({"id": "mer-001", "shopId": 4, "skill": "ops"}, 6)
        self.assertFalse(result.checks["numbers_in_source"], "1 must not validate against the characters in 100")
        self.assertIsNotNone(result.answer)
        self.assertTrue(result.evidence)

    def test_merchant_recheck_accepts_equivalent_decimal_spellings(self):
        with patch.object(ev, "run_merchant_analyze", return_value={"code": 0, "data": {
            "observations": ["Coupon share 40.00%"], "hypotheses": ["可能与活动有关"], "suggestions": ["Continue checking"],
        }}), patch.object(ev.agent_tools, "get_metrics", return_value={"couponOrderShare": 40.0}):
            result = ev.run_merchant_case({"id": "mer-001", "shopId": 4, "skill": "ops"}, 6)
        self.assertTrue(result.checks["numbers_in_source"])

    def test_merchant_recheck_accepts_an_actual_date_in_quoted_review_text(self):
        source = [{"topic": "等位", "count": 8, "avgScore": 4.0, "samples": [{
            "reviewId": 539, "text": "本人修改确认-20261010T161812-49f468：等位较久。", "score": 4.0,
        }]}]
        observation = "观点‘等位’共8条，均分4分；评价#539：本人修改确认-20261010T161812-49f468：等位较久。"
        with patch.object(ev, "run_merchant_analyze", return_value={"code": 0, "data": {
            "observations": [observation], "hypotheses": ["可能与客流有关"], "suggestions": ["记录等位时长"],
        }}), patch.object(ev.agent_tools, "get_review_clusters", return_value=source):
            result = ev.run_merchant_case({"id": "mer-002", "shopId": 4, "skill": "reviews"}, 6)
        self.assertTrue(result.checks["numbers_in_source"], result.detail)

    def test_merchant_recheck_accepts_exact_mixed_identifiers_from_source_shop_names(self):
        name = "验收专用异店-20261010T150924-9c2f60"
        source = [{"shopId": 43, "name": name, "distanceMeters": 478, "sales": 0}]
        with patch.object(ev, "run_merchant_analyze", return_value={"code": 0, "data": {
            "observations": ["竞品‘" + name + "’；距离478米；销量0"],
            "hypotheses": ["可能尚未有稳定客流"], "suggestions": ["继续观察"],
        }}), patch.object(ev.agent_tools, "get_competitors", return_value=source):
            result = ev.run_merchant_case({"id": "mer-003", "shopId": 4, "skill": "competitors"}, 6)
        self.assertTrue(result.checks["numbers_in_source"], result.detail)

    def test_merchant_recheck_preserves_exact_signed_decimal_values(self):
        with patch.object(ev, "run_merchant_analyze", return_value={"code": 0, "data": {
            "observations": ["净变化-10.00"], "hypotheses": ["可能存在周期波动"], "suggestions": ["继续观察"],
        }}), patch.object(ev.agent_tools, "get_metrics", return_value={"netChange": -10.0, "other": 100}):
            result = ev.run_merchant_case({"id": "mer-001", "shopId": 4, "skill": "ops"}, 6)
        self.assertTrue(result.checks["numbers_in_source"], result.detail)

    def test_rejected_merchant_model_claim_is_retained_for_diagnosis(self):
        original = {"observations": ["New customer share 100%"], "hypotheses": ["可能与活动有关"], "suggestions": ["Continue checking"]}
        with patch.object(ev.llm, "API_KEY", "configured-test-key"), patch("merchant_graph.chat_json", return_value=original):
            result = ev.run_merchant_case({"id": "mer-001", "shopId": 4, "skill": "ops"}, 6)
        self.assertFalse(ev.passed(result))
        self.assertTrue(getattr(result, "model_outputs", []), "Rejected prose must not disappear behind data=null")
        self.assertEqual(result.model_outputs[0], original)


if __name__ == "__main__":
    unittest.main()
