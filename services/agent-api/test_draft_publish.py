"""Draft confirmation contract tests; no database or model requests."""
import unittest

from fastapi.testclient import TestClient

import drafts
from main import app


class DraftPublishTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.owner = {"X-User-Id": "12"}
        self.other = {"X-User-Id": "13"}
        self.draft_id = drafts.create(
            12, 47, {"taste": 5, "wait": 3, "env": 4}, "Original draft", ["Order #47"]
        )
        self.path = f"/agent/review-draft/{self.draft_id}"

    def tearDown(self):
        drafts.pop(self.draft_id, 12)
        self.client.close()

    def test_fetch_for_publish_keeps_draft_available_until_commit(self):
        first = self.client.post(self.path + "/publish", headers=self.owner).json()
        second = self.client.post(self.path + "/publish", headers=self.owner).json()
        self.assertEqual(first["code"], 0)
        self.assertEqual(second["code"], 0, "A failed Java validation must allow retry")
        self.assertEqual(first["data"]["orderId"], 47)
        self.assertTrue(drafts.exists(self.draft_id))

    def test_complete_consumes_only_the_owners_draft(self):
        self.client.post(self.path + "/publish", headers=self.owner)
        response = self.client.post(self.path + "/complete", headers=self.owner)
        self.assertEqual(response.status_code, 200, "Java needs a completion endpoint after commit")
        self.assertEqual(response.json()["code"], 0)
        self.assertFalse(drafts.exists(self.draft_id))
        retried = self.client.post(self.path + "/publish", headers=self.owner).json()
        self.assertEqual(retried["code"], 40001)

    def test_another_user_cannot_read_or_complete_a_draft(self):
        for operation in ("publish", "complete"):
            with self.subTest(operation=operation):
                response = self.client.post(self.path + "/" + operation, headers=self.other)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["code"], 40300)
                self.assertTrue(drafts.exists(self.draft_id))
        self.assertEqual(
            self.client.post(self.path + "/publish", headers=self.owner).json()["code"], 0
        )

    def test_internal_user_header_is_required(self):
        self.assertEqual(self.client.post(self.path + "/publish").status_code, 422)
        self.assertTrue(drafts.exists(self.draft_id))


if __name__ == "__main__":
    unittest.main()
