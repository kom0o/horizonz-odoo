# Copyright (C) 2026 ERP Heritage.
"""Native browser workflows for guided queries and editable KPI scorecards."""
import json
from pathlib import Path

from odoo import fields
from odoo.tests import HttpCase, tagged


@tagged('eh_board', 'eh_board_advantage_ui', 'post_install', '-at_install')
class TestBoardAdvantageUI(HttpCase):
    def _seed_board(self):
        Dashboard = self.env['eh.board.dashboard']
        Dashboard.search([]).unlink()
        board = Dashboard.create({'name': 'Advantage browser fixture', 'state': 'published', 'refresh_mode': 'off'})
        partners = self.env['res.partner'].create([
            {'name': 'Advantage fixture %s' % i, 'company_id': self.env.company.id,
             'country_id': self.env.ref('base.au').id} for i in range(3)])
        item = board._create_item_from_builder({
            'model_id': self.env['ir.model']._get('res.partner').id,
            'domain': repr([('id', 'in', partners.ids)]),
            'title': 'Fixture contact count', 'item_type': 'kpi', 'date_field': 'create_date',
            'measures': [{'verb': 'count', 'label': 'Contacts'}],
        })
        self.env.cr.flush()
        return board, item, partners

    def _browser_check(self, scenario, data):
        script = (Path(__file__).resolve().parents[1] / 'static/tests/advantage_tour.js').read_text()
        self.browser_js('/web#action=eh_board.action_eh_board_open',
                        script + '\nwindow.ehBoardAdvantageTour(%s, %s).catch((error) => console.error(error));' % (json.dumps(scenario), json.dumps(data)),
                        "!!document.querySelector('.eh_board_app .eh_board_widget')", login='admin', timeout=120)

    def test_scorecard_create_preview_save_and_reopen(self):
        board, item, _partners = self._seed_board()
        day = fields.Date.to_string(fields.Date.context_today(board))
        self._browser_check('scorecard', {'day': day, 'itemId': item.id})
        nodes = board.scorecard_node_ids
        self.assertEqual(len(nodes), 2, 'Previews must not leave persisted nodes')
        metric = nodes.filtered(lambda node: node.kind == 'metric')
        self.assertEqual(metric.item_id, item)
        self.assertEqual(metric.target, 6)
        self.assertEqual(metric.baseline, 0)
        self.assertEqual(metric.parent_id.name, 'Contact coverage')
        result = board.get_scorecard({'date_range': {'start': day, 'end': day}})
        self.assertTrue(all(row['score'] == 50 for row in result['results']))

    def test_guided_query_preview_stale_edit_and_save(self):
        board, _item, _partners = self._seed_board()
        model = self.env['ir.model']._get('res.partner')
        self._browser_check('query', {'modelName': model.name})
        sources = self.env['eh.board.datasource'].search([('dashboard_id', '=', board.id), ('provider_type', '=', 'join')])
        self.assertEqual(len(sources), 1, 'Previews must not leave analysis sources')
        self.assertEqual(len(board.item_ids), 2)
        query_item = board.item_ids.filtered(lambda item: item.datasource_id == sources)
        self.assertEqual(query_item.title, 'Reviewed contact comparison')
        payload = query_item.get_payload({})
        self.assertFalse(payload.get('error'))
        self.assertEqual(payload['rows'][0]['values'], {'left': 3.0, 'right': 3.0, 'formula': 1.0})
