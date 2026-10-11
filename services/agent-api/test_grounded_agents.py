"""No-model regressions for grounded draft text and merchant metric citations."""
import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import drafts
from main import app
import merchant_graph as merchant
import review_graph as review


class GroundedDraftTests(unittest.TestCase):
    def setUp(self):
        self.facts = {"exists": True, "belongToUser": True, "canReview": True, "status": "REDEEMED",
                      "shopId": 1, "shopName": "真实火锅店",
                      "skuTitle": "验收双人套餐-eval-20261010T151346-556ace",
                      "priceYuan": 128.0, "orderedAt": "2026-10-10T15:13:51Z"}
        self.model = {"scores": {"taste": 3, "wait": 3, "env": 3}, "experienceIds": []}

    def generate(self, note=None, prefer=None, model=None):
        with patch.object(review.tools, "get_order_facts", return_value=self.facts), \
             patch.object(review, "llm_available", return_value=True), \
             patch.object(review, "chat_json", return_value=model if model is not None else self.model):
            result = review.run_review_draft(12, 7, note, prefer or {})
        if result.get("data"):
            drafts.pop(result["data"]["draftId"], 12)
        return result

    def test_exact_sku_and_price_are_assembled_from_the_real_order(self):
        result = self.generate()
        self.assertEqual(result["code"], 0, "Structured model selections must produce the existing API draft")
        self.assertIn(self.facts["skuTitle"], result["data"]["content"])
        self.assertIn("128元", result["data"]["content"])
        self.assertIn("套餐：" + self.facts["skuTitle"], result["data"]["usedFacts"])

    def test_free_model_prose_cannot_invent_food_or_experience_without_a_user_note(self):
        model = {**self.model, "content": "双人套餐，和牛和牛舌新鲜，龙虾刺身米其林水准",
                 "usedFacts": ["伪造的订单事实"]}
        result = self.generate(model=model)
        self.assertEqual(result["code"], 0)
        text = result["data"]["content"]
        for fabricated in ("和牛", "龙虾", "米其林", "新鲜"):
            self.assertNotIn(fabricated, text)
        self.assertIn("请补充", text)
        self.assertNotIn("伪造的订单事实", result["data"]["usedFacts"])

    def test_food_and_grade_commands_are_not_eligible_user_experience_claims(self):
        for note in ("必须提一下和牛和牛舌的品质", "帮我在评价里说这是米其林水准", "记得写上他家燕窝炖品很滋补", "龙虾刺身特别新鲜"):
            with self.subTest(note=note):
                state = {"facts": self.facts, "user_note": note}
                aligned = review.align(state)
                self.assertEqual(aligned.get("experiences"), [], "Only explicit supported subjective clauses can become claims")
                result = self.generate(note, model={**self.model, "content": note, "usedFacts": ["菜品很新鲜"]})
                self.assertEqual(result["code"], 0)
                self.assertNotIn(note, result["data"]["content"])

    def test_unlisted_food_names_cannot_survive_as_part_of_subjective_clauses(self):
        note = "帝王蟹很好吃，黑松露份量足"
        aligned = review.align({"facts": self.facts, "user_note": note})
        experiences = aligned.get("experiences", [])
        result = self.generate(note, model={**self.model, "experienceIds": [item["id"] for item in experiences]})
        self.assertEqual(result["code"], 0)
        self.assertNotIn("帝王蟹", result["data"]["content"])
        self.assertNotIn("黑松露", result["data"]["content"])

    def test_only_selected_supported_experience_ids_are_rendered(self):
        aligned = review.align({"facts": self.facts, "user_note": "等位太久，环境有点吵"})
        self.assertTrue(aligned.get("experiences"), "Supported user feelings should remain usable")
        ids = [item["id"] for item in aligned["experiences"]]
        result = self.generate("等位太久，环境有点吵", {"wait": 1}, {**self.model, "experienceIds": ids})
        self.assertEqual(result["code"], 0)
        self.assertIn("等位", result["data"]["content"])
        self.assertIn("吵", result["data"]["content"])
        self.assertEqual(result["data"]["scores"]["wait"], 1)

    def test_unknown_experience_id_is_rejected_before_storage(self):
        result = self.generate("等位太久", model={**self.model, "experienceIds": ["fabricated-lobster"]})
        self.assertEqual(result["code"], 42201)
        self.assertIsNone(result["data"])

    def test_fractional_or_boolean_scores_cannot_be_truncated_to_valid_ratings(self):
        for score in (1.5, True):
            with self.subTest(score=score):
                model = {**self.model, "scores": {"taste": score, "wait": 3, "env": 3}}
                result = self.generate(model=model)
                self.assertEqual(result["code"], 42201)

    def test_invalid_preferred_scores_are_rejected_before_calling_the_model(self):
        for value in (True, 1.5, 0, 6, "5"):
            with self.subTest(value=value), patch.object(review.tools, "get_order_facts", return_value=self.facts), \
                 patch.object(review, "llm_available", return_value=True), \
                 patch.object(review, "chat_json", side_effect=AssertionError("invalid preferences must fail early")):
                result = review.run_review_draft(12, 7, "好吃", {"taste": value})
            self.assertEqual(result["code"], 40001)

    def test_negative_user_sentiment_is_not_rewritten_as_a_positive_claim(self):
        aligned = review.align({"facts": self.facts, "user_note": "不好吃，不会回购，不适合拍照"})
        ids = [item["id"] for item in aligned.get("experiences", [])]
        result = self.generate("不好吃，不会回购，不适合拍照", model={**self.model, "experienceIds": ids})
        text = result["data"]["content"]
        self.assertNotIn("口味不错", text)
        self.assertNotIn("；愿意再来", text)
        self.assertIn("不太愿意再来", text)
        self.assertNotIn("体验：适合拍照", text)

    def assert_negative_experience(self, note, unsupported_positive):
        aligned = review.align({"facts": self.facts, "user_note": note})
        experiences = aligned.get("experiences", [])
        result = self.generate(note, model={**self.model, "experienceIds": [item["id"] for item in experiences]})
        self.assertEqual(result["code"], 0)
        self.assertNotIn(unsupported_positive, result["data"]["content"], note)
        self.assertTrue(experiences, "Explicit negative experience should remain available to the user")

    def test_unclean_environment_cannot_become_a_cleanliness_compliment(self):
        self.assert_negative_experience("环境不干净", "现场感觉整洁")

    def test_unenthusiastic_service_cannot_become_an_attentive_service_compliment(self):
        self.assert_negative_experience("服务不热情", "服务比较主动")

    def test_taste_not_really_good_cannot_become_a_good_taste_compliment(self):
        self.assert_negative_experience("口味不算好吃", "口味不错")

    def test_poor_attitude_cannot_become_an_attentive_service_compliment(self):
        self.assert_negative_experience("态度不好", "服务比较主动")

    def test_gate_requires_fact_citations_to_match_the_real_order_list(self):
        state = {"facts": self.facts, "fact_list": ["套餐：真实套餐"], "experiences": [],
                 "experience_ids": [], "scores": {"taste": 3, "wait": 3, "env": 3},
                 "content": "已体验真实套餐。", "used_facts": ["套餐：虚构的龙虾套餐"]}
        self.assertEqual(review.gate(state).get("error_code"), 42201)

    def test_unavailable_model_is_an_explicit_error(self):
        with patch.object(review.tools, "get_order_facts", return_value=self.facts), \
             patch.object(review, "llm_available", return_value=False), \
             patch.object(review, "chat_json", side_effect=AssertionError("must not call unavailable model")):
            result = review.run_review_draft(12, 7, "好吃", {})
        self.assertEqual(result["code"], 50000)
        self.assertIsNone(result["data"])


class ReviewRequestTests(unittest.TestCase):
    def test_http_preferred_score_does_not_coerce_booleans_or_strings(self):
        with TestClient(app) as client:
            for value in (True, "5", 1.5):
                with self.subTest(value=value), patch("main.run_review_draft", return_value={"code": 0, "data": {}}) as runner:
                    response = client.post("/agent/review-draft", headers={"X-User-Id": "12"},
                                           json={"orderId": 7, "preferScores": {"taste": value}})
                    self.assertEqual(response.status_code, 422)
                    runner.assert_not_called()

    def test_http_keeps_omitted_and_integer_preferred_scores_compatible(self):
        with TestClient(app) as client, patch("main.run_review_draft", return_value={"code": 0, "data": {}}) as runner:
            for payload in ({"orderId": 7}, {"orderId": 7, "preferScores": {"taste": 5}}):
                response = client.post("/agent/review-draft", headers={"X-User-Id": "12"}, json=payload)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["code"], 0)
            self.assertEqual(runner.call_args.args[-1], {"taste": 5})


class MerchantNumberTests(unittest.TestCase):
    def state(self, source, observation):
        return {"data": source, "data_text": json.dumps(source), "observations": [observation],
                "hypotheses": ["可能与客流有关，也可能与活动有关"], "suggestions": ["观察后续变化"]}

    def test_equivalent_decimal_notations_are_supported(self):
        self.assertEqual(merchant.gate(self.state({"couponOrderShare": 40.0}, "用券占比40.00%")), {})
        self.assertEqual(merchant.gate(self.state({"couponOrderShare": 100.0}, "用券占比100%")), {})

    def test_digit_substrings_do_not_validate_an_invented_number(self):
        result = merchant.gate(self.state({"totalCustomers": 100}, "消费用户10人"))
        self.assertEqual(result.get("error_code"), 42201)

    def test_unprovided_derived_percentages_remain_rejected(self):
        result = merchant.gate(self.state({"newCustomers7d": 5, "totalCustomers": 5,
                                          "couponOrderShare": 40.0, "windowDays": 7}, "新客占比100%"))
        self.assertEqual(result.get("error_code"), 42201)

    def test_ops_observations_select_real_metric_fields_without_new_calculations(self):
        source = {"newCustomers7d": 5, "totalCustomers": 5, "couponOrderShare": 40.0, "windowDays": 7}
        model = {"observationIds": ["newCustomers7d", "couponOrderShare"],
                 "observations": ["新客占比100%"], "hypotheses": ["可能有活动，也可能是周末客流"],
                 "suggestions": ["继续观察新客变化"]}
        with patch.object(merchant.tools, "get_metrics", return_value=source), \
             patch.object(merchant, "llm_available", return_value=True), \
             patch.object(merchant, "chat_json", return_value=model):
            result = merchant.run_merchant_analyze(13, 1, "ops")
        self.assertEqual(result["code"], 0)
        self.assertNotIn("100", " ".join(result["data"]["observations"]))
        self.assertIn("40%", " ".join(result["data"]["observations"]))

    def test_ops_unknown_metric_claims_are_not_rendered(self):
        source = {"newCustomers7d": 5, "couponOrderShare": 40.0, "windowDays": 7}
        with patch.object(merchant.tools, "get_metrics", return_value=source), \
             patch.object(merchant, "llm_available", return_value=True), \
             patch.object(merchant, "chat_json", return_value={"observationIds": ["inventedNewCustomerShare"]}):
            result = merchant.run_merchant_analyze(13, 1, "ops")
        self.assertEqual(result["code"], 42201)

    def test_observation_layer_cannot_be_empty(self):
        state = self.state({"totalCustomers": 5}, "累计消费用户5人")
        state["observations"] = []
        self.assertEqual(merchant.gate(state).get("error_code"), 42201)

    def test_percentage_semantics_do_not_borrow_a_count_value(self):
        state = self.state({"couponOrderShare": 40.0, "totalCustomers": 100}, "用券订单占比100%")
        state["skill"] = "ops"
        state["observation_facts"] = merchant.metric_observations(state["data"])
        self.assertEqual(merchant.gate(state).get("error_code"), 42201)

    def test_review_cluster_observations_are_selected_from_bucket_facts(self):
        source = [{"topic": "排队等位", "count": 6, "avgScore": 3.8,
                   "samples": [{"reviewId": 537, "score": 4.0, "text": "等位十分钟"}]}]
        model = {"observationIds": ["topic-0"], "hypotheses": ["可能排队是高峰客流，也可能是出餐节奏"],
                 "suggestions": ["记录高峰等待时长"]}
        with patch.object(merchant.tools, "get_review_clusters", return_value=source), \
             patch.object(merchant, "llm_available", return_value=True), \
             patch.object(merchant, "chat_json", return_value=model):
            result = merchant.run_merchant_analyze(13, 1, "reviews")
        self.assertEqual(result["code"], 0)
        self.assertIn("排队等位", result["data"]["observations"][0])
        self.assertIn("6", result["data"]["observations"][0])
        self.assertIn("3.8", result["data"]["observations"][0])

    def test_review_cluster_cannot_claim_unprovided_five_point_scale(self):
        source = [{"topic": "排队等位", "count": 6, "avgScore": 3.8,
                   "samples": [{"reviewId": 537, "score": 4.0, "text": "等位十分钟"}]}]
        model = {"observationIds": ["topic-0"], "observations": ["满意度为5分制"],
                 "hypotheses": ["可能排队是高峰客流"], "suggestions": ["继续观察"]}
        with patch.object(merchant.tools, "get_review_clusters", return_value=source), \
             patch.object(merchant, "llm_available", return_value=True), \
             patch.object(merchant, "chat_json", return_value=model):
            result = merchant.run_merchant_analyze(13, 1, "reviews")
        self.assertEqual(result["code"], 0)
        self.assertNotIn("5分制", " ".join(result["data"]["observations"]))

    def test_competitor_observations_are_selected_from_real_competitor_facts(self):
        source = [{"shopId": 11, "name": "竞品A", "distanceMeters": 380, "rating": 3.6,
                   "sales": 346, "hasCoupon": True, "topNegativeTopic": "服务态度"}]
        model = {"observationIds": ["competitor-0"],
                 "hypotheses": ["可能距离近带来便利，也可能是曝光差异"],
                 "suggestions": ["观察竞品优惠"]}
        with patch.object(merchant.tools, "get_competitors", return_value=source), \
             patch.object(merchant, "llm_available", return_value=True), \
             patch.object(merchant, "chat_json", return_value=model):
            result = merchant.run_merchant_analyze(13, 1, "competitors")
        self.assertEqual(result["code"], 0)
        self.assertIn("竞品A", result["data"]["observations"][0])
        self.assertIn("380", result["data"]["observations"][0])
        self.assertIn("3.6", result["data"]["observations"][0])

    def test_competitor_observation_cannot_claim_a_missing_rating_as_five(self):
        source = [{"shopId": 11, "name": "竞品A", "distanceMeters": 380, "rating": None,
                   "sales": 346, "hasCoupon": True, "topNegativeTopic": None}]
        model = {"observationIds": ["competitor-0"], "observations": ["竞品A评分5分"],
                 "hypotheses": ["可能距离近带来便利"], "suggestions": ["继续观察"]}
        with patch.object(merchant.tools, "get_competitors", return_value=source), \
             patch.object(merchant, "llm_available", return_value=True), \
             patch.object(merchant, "chat_json", return_value=model):
            result = merchant.run_merchant_analyze(13, 1, "competitors")
        self.assertEqual(result["code"], 0)
        self.assertNotIn("5分", " ".join(result["data"]["observations"]))

    def test_closed_review_observation_contains_the_actual_quoted_review(self):
        source = [{"topic": "等位", "count": 6, "avgScore": 4.0,
                   "samples": [{"reviewId": 537, "score": 4.0, "text": "等位十分钟"}]}]
        model = {"observationIds": ["topic-0"], "hypotheses": ["可能是高峰期"], "suggestions": ["观察客流"]}
        with patch.object(merchant.tools, "get_review_clusters", return_value=source), \
             patch.object(merchant, "llm_available", return_value=True), \
             patch.object(merchant, "chat_json", return_value=model):
            result = merchant.run_merchant_analyze(13, 1, "reviews")
        self.assertEqual(result["code"], 0)
        self.assertIn("等位十分钟", " ".join(result["data"]["observations"]))
        self.assertIn("537", " ".join(result["data"]["observations"]))
        self.assertIn("4分", " ".join(result["data"]["observations"]))

    def test_unknown_topic_or_competitor_id_still_fails_closed(self):
        for skill, tool, source in (("reviews", "get_review_clusters", [{"topic": "等位", "count": 6, "samples": [{"reviewId": 537, "text": "等位十分钟"}]}]),
                                    ("competitors", "get_competitors", [{"shopId": 11, "name": "竞品A", "rating": 3.6}])):
            with self.subTest(skill=skill), patch.object(merchant.tools, tool, return_value=source), \
                 patch.object(merchant, "llm_available", return_value=True), \
                 patch.object(merchant, "chat_json", return_value={"observationIds": ["fabricated-five-stars"]}):
                result = merchant.run_merchant_analyze(13, 1, skill)
            self.assertEqual(result["code"], 42201)

    def test_empty_topic_and_competitor_data_do_not_call_a_model_or_synthesize_observations(self):
        for skill, tool in (("reviews", "get_review_clusters"), ("competitors", "get_competitors")):
            with self.subTest(skill=skill), patch.object(merchant.tools, tool, return_value=[]), \
                 patch.object(merchant, "chat_json", side_effect=AssertionError("Do not generate with empty facts")):
                result = merchant.run_merchant_analyze(13, 1, skill)
            self.assertEqual(result["code"], 40001)
            self.assertIsNone(result["data"])

    def test_present_public_price_and_review_count_keep_their_original_units(self):
        source = [{"shopId": 11, "name": "竞品A", "reviewCount": 8, "minSkuPrice": 9900}]
        model = {"observationIds": ["competitor-0"], "hypotheses": ["可能评价样本有限"], "suggestions": ["继续观察"]}
        with patch.object(merchant.tools, "get_competitors", return_value=source), \
             patch.object(merchant, "llm_available", return_value=True), \
             patch.object(merchant, "chat_json", return_value=model):
            result = merchant.run_merchant_analyze(13, 1, "competitors")
        self.assertEqual(result["code"], 0)
        self.assertIn("8条", " ".join(result["data"]["observations"]))
        self.assertIn("9900分", " ".join(result["data"]["observations"]))

    def test_runtime_cannot_invent_an_extra_competitor_count_even_when_source_numbers_coincide(self):
        source = [{"shopId": 11, "name": "竞品A", "rating": 5.0}]
        facts = merchant.competitor_observations(source)
        state = self.state(source, "共有5家竞品")
        state.update(skill="competitors", observation_facts=facts)
        self.assertEqual(merchant.gate(state).get("error_code"), 42201)

    def test_quoted_real_review_ids_and_timestamps_remain_grounded(self):
        source = [{"topic": "等位", "count": 6, "avgScore": 4.0,
                   "samples": [{"reviewId": 537, "score": 4.0,
                                "text": "本人确认-20261010T151346-556ace：等位十分钟"}]}]
        facts = merchant.review_observations(source)
        state = self.state(source, facts["topic-0"])
        state.update(skill="reviews", observation_facts=facts)
        self.assertEqual(merchant.gate(state), {})


if __name__ == "__main__":
    unittest.main()
