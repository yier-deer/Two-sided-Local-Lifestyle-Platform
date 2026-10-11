#!/usr/bin/env python
"""Prepare a repeatable live presentation using public APIs; never reset a database."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from urllib.request import Request, urlopen


def prepare(base_url, output):
    def api(path, method='GET', body=None, token=None, key=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        if key:
            headers['Idempotency-Key'] = key
        request = Request(base_url.rstrip('/') + path, data=json.dumps(body).encode() if body is not None else None, headers=headers, method=method)
        with urlopen(request, timeout=15) as response:
            envelope = json.load(response)
        if envelope.get('code') != 0:
            raise RuntimeError(f"{method} {path}: {envelope.get('code')} {envelope.get('message')}")
        return envelope['data']

    merchant = api('/api/auth/login', 'POST', {'phone': '13611110004', 'password': 'merchant123456'})
    user = api('/api/auth/login', 'POST', {'phone': '13611110001', 'password': 'user123456'})
    mt, ut = merchant['token'], user['token']
    # Preserve testing evidence while removing verification offers from the public catalog.
    # Only exact SKU IDs recorded by our verifiers and explicit test prefixes are eligible.
    report_root = Path(__file__).resolve().parent.parent / 'docs' / 'reports'
    retired_skus = set()
    for report_path in report_root.glob('*.json'):
        try:
            report = json.loads(report_path.read_text(encoding='utf-8'))
            if report.get('shopUrl', '').replace('localhost', '127.0.0.1').rstrip('/') != base_url.replace('localhost', '127.0.0.1').rstrip('/'):
                continue
            resources = report.get('resources', {})
            created = resources.get('created', {})
            for entry in created.get('skus', []):
                if isinstance(entry, dict) and isinstance(entry.get('id'), int):
                    retired_skus.add(entry['id'])
        except (ValueError, OSError, AttributeError):
            continue
    shops = api('/api/merchant/shops', token=mt)
    candidates = [s for s in shops if s['status'] == 'approved']
    if not candidates:
        raise RuntimeError('Demo merchant needs one approved own shop; do not overwrite existing ownership.')
    shop = sorted(candidates, key=lambda s: (-s.get('reviewCount', 0), s['id']))[0]
    skus = api('/api/merchant/skus?shopId=' + str(shop['id']), token=mt)
    for item in skus:
        explicit_test = (item['id'] in retired_skus and item['title'].startswith('验收双人套餐')) or item['title'].startswith('真实浏览器双人套餐')
        if item['onSale'] and explicit_test:
            api('/api/merchant/skus/' + str(item['id']), 'PATCH', {'onSale': False}, mt)
    skus = api('/api/merchant/skus?shopId=' + str(shop['id']), token=mt)
    sku = next((s for s in skus if s['title'] == '演示·双人火锅套餐' and s['onSale'] and s['stock'] > 0), None)
    if not sku:
        sku = api('/api/merchant/skus', 'POST', {'shopId': shop['id'], 'title': '演示·双人火锅套餐', 'price': 19800, 'stock': 50}, mt)
    coupons = api('/api/merchant/coupons?shopId=' + str(shop['id']), token=mt)
    held_coupons = api('/api/coupons/mine', token=ut)
    consumed_templates = {c['couponId'] for c in held_coupons if c['status'] in ('USED', 'FROZEN')}
    now = datetime.now(timezone.utc)
    def valid_coupon(c):
        return c['title'] == '演示·满100减20' and c.get('remaining', 0) > 0 and c['id'] not in consumed_templates and datetime.fromisoformat(c['startAt'].replace('Z', '+00:00')) <= now < datetime.fromisoformat(c['endAt'].replace('Z', '+00:00'))
    coupon = next((c for c in coupons if valid_coupon(c)), None)
    if not coupon:
        coupon = api('/api/merchant/coupons', 'POST', {'shopId': shop['id'], 'title': '演示·满100减20', 'threshold': 10000, 'amount': 2000, 'total': 1000}, mt)
    orders = api('/api/orders?unreviewed=true', token=ut)
    order = next((o for o in orders if o['shopId'] == shop['id'] and o['skuId'] == sku['id']), None)
    if not order:
        # A new candidate is prepared only when the previous presentation consumed its review.
        all_orders = api('/api/orders', token=ut)
        generation = sum(o['skuId'] == sku['id'] for o in all_orders)
        order = api('/api/orders', 'POST', {'skuId': sku['id']}, ut, f'demo-ready-{user["userId"]}-{sku["id"]}-{generation}')
        if order['status'] == 'CREATED':
            order = api(f'/api/orders/{order["id"]}/pay', 'POST', {}, ut)
        if order['status'] == 'PAID':
            order = api(f'/api/merchant/orders/{order["id"]}/redeem', 'POST', {}, mt)
        if order['status'] != 'REDEEMED':
            raise RuntimeError('Presentation candidate is not reviewable; inspect its recorded state before retry.')
    scenario = {'version': 1, 'shopId': shop['id'], 'shopName': shop['name'], 'skuId': sku['id'], 'skuTitle': sku['title'], 'price': sku['price'], 'couponId': coupon['id'], 'couponTitle': coupon['title'], 'discount': coupon['amount'], 'reviewableOrderId': order['id'], 'userPhone': '13611110001', 'merchantPhone': '13611110004', 'mode': 'live', 'payment': 'simulation', 'notes': 'Prepared through authenticated real APIs; no model request, database reset or hidden credentials.'}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(scenario, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Live presentation prepared: {shop["name"]}, SKU #{sku["id"]}, coupon #{coupon["id"]}, reviewable order #{order["id"]}.')
    print('Scenario:', output)
    return scenario


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--shop-url', default='http://127.0.0.1:8081')
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parent / 'logs' / 'demo-scenario.json')
    args = parser.parse_args()
    try:
        prepare(args.shop_url, args.output)
    except Exception as error:
        print('Demo preparation failed:', str(error), file=sys.stderr)
        sys.exit(1)
