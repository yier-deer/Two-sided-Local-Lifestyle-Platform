import unittest
from unittest.mock import patch
import graph


class BudgetCandidateTests(unittest.TestCase):
    def state(self, budget=80):
        return {'lat': 30.24, 'lng': 120.15, 'constraints': {'category': 'HOTPOT', 'budgetYuan': budget, 'radius': 5000}, 'profile': {}}

    def test_budget_feasible_packages_are_selected_before_evidence_generation(self):
        candidates = [{'id': 1, 'minSkuPrice': 9900}, {'id': 2, 'minSkuPrice': 5800}, {'id': 3, 'minSkuPrice': 7900}]
        with patch.object(graph.tools, 'search_shops', return_value=candidates):
            result = graph.search_shops(self.state())
        self.assertEqual([c['id'] for c in result['candidates']], [2, 3])
        self.assertEqual(result['constraints']['budgetReference'], 'packageStartingPrice')

    def test_unknown_price_or_no_affordable_candidate_does_not_invent_an_empty_neighborhood(self):
        candidates = [{'id': 1, 'minSkuPrice': 9900}, {'id': 2, 'minSkuPrice': None}]
        with patch.object(graph.tools, 'search_shops', return_value=candidates):
            result = graph.search_shops(self.state())
        self.assertEqual(result['candidates'], [candidates[0]])
        self.assertFalse(result['constraints']['hasBudgetOption'])

    def test_no_valid_budget_preserves_distance_order(self):
        candidates = [{'id': 1, 'minSkuPrice': 9900}, {'id': 2, 'minSkuPrice': 5800}]
        for budget in (None, True, -1, float('nan'), '80'):
            with self.subTest(budget=budget), patch.object(graph.tools, 'search_shops', return_value=candidates):
                self.assertEqual(graph.search_shops(self.state(budget))['candidates'], candidates)

    def test_unpriced_new_admissions_do_not_displace_available_budget_options(self):
        candidates = [{'id': 43, 'minSkuPrice': None}, {'id': 41, 'minSkuPrice': 9900}, {'id': 7, 'minSkuPrice': 3212}]
        with patch.object(graph.tools, 'search_shops', return_value=candidates) as search:
            result = graph.search_shops(self.state())
        self.assertEqual([shop['id'] for shop in result['candidates']], [7])
        self.assertEqual(search.call_args.kwargs['limit'], 40)


if __name__ == '__main__': unittest.main()
