"""Repeatable live scene preparation, verified without service writes or models."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('prepare_demo', Path(__file__).with_name('prepare-demo.py'))
prepare_demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare_demo)


class Response:
    def __init__(self, value): self.value = json.dumps({'code': 0, 'data': value}).encode()
    def read(self, *args): return self.value
    def __enter__(self): return self
    def __exit__(self, *args): return False


class PrepareDemoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name) / 'scenario.json'
        self.posts = []
        self.coupon_status = 'USED'

    def tearDown(self): self.temp.cleanup()

    def respond(self, request, **kwargs):
        path = request.full_url.split('http://service.test')[-1]
        method = request.get_method()
        body = json.loads(request.data) if request.data else None
        if method != 'GET': self.posts.append((path, body))
        if path == '/api/auth/login': return Response({'token': 'test-only', 'userId': 2})
        if path == '/api/merchant/shops': return Response([{'id': 1, 'name': 'Owned shop', 'status': 'approved', 'reviewCount': 10}])
        if path == '/api/merchant/skus?shopId=1': return Response([{'id': 98, 'title': '演示·双人火锅套餐', 'price': 19800, 'stock': 10, 'onSale': True}])
        if path == '/api/merchant/coupons?shopId=1': return Response([{'id': 64, 'title': '演示·满100减20', 'amount': 2000, 'remaining': 999, 'startAt': '2020-01-01T00:00:00Z', 'endAt': '2099-01-01T00:00:00Z'}])
        if path == '/api/coupons/mine': return Response([{'couponId': 64, 'status': self.coupon_status}])
        if path == '/api/orders?unreviewed=true': return Response([{'id': 20, 'shopId': 1, 'skuId': 98, 'status': 'REDEEMED'}])
        if path == '/api/merchant/coupons' and method == 'POST': return Response({**body, 'id': 65})
        self.fail('Unexpected scene mutation/request: ' + str((method, path, body)))

    def test_consumed_coupon_is_replaced_without_resetting_old_data(self):
        with patch.object(prepare_demo, 'urlopen', side_effect=self.respond):
            result = prepare_demo.prepare('http://service.test', self.output)
        self.assertEqual(result['couponId'], 65)
        self.assertEqual(result['reviewableOrderId'], 20)
        self.assertEqual([p for p, _ in self.posts if p != '/api/auth/login'], ['/api/merchant/coupons'])
        self.assertNotIn('test-only', self.output.read_text(encoding='utf-8'))

    def test_unused_held_coupon_is_reused_for_the_next_presentation(self):
        self.coupon_status = 'UNUSED'
        with patch.object(prepare_demo, 'urlopen', side_effect=self.respond):
            result = prepare_demo.prepare('http://service.test', self.output)
        self.assertEqual(result['couponId'], 64)
        self.assertEqual([p for p, _ in self.posts if p != '/api/auth/login'], [])


if __name__ == '__main__': unittest.main()
