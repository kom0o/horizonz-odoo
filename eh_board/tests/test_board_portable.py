# Copyright (C) 2026 ERP Heritage.
"""Reusable scorecard imports bind fresh widgets, never database-local IDs."""
import copy
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('eh_board', 'eh_board_advantage', 'post_install', '-at_install')
class TestBoardPortable(TransactionCase):
    def setUp(self):
        super().setUp()
        self.env = self.env(user=self.env.ref('base.user_admin').id)
        self.board = self.env['eh.board.dashboard'].create({'name': 'Portable objectives'})
        self.item = self.board._create_item_from_builder({
            'model_id': self.env['ir.model']._get('res.partner').id,
            'title': 'Contacts', 'item_type': 'kpi',
            'measures': [{'verb': 'count', 'label': 'Contacts'}],
        })
        day = fields.Date.to_string(fields.Date.context_today(self.board))
        self.options = {'date_range': {'start': day, 'end': day}}
        self.nodes = [
            {'key': 'root', 'parent_key': '', 'name': 'Team objective', 'kind': 'group',
             'owner_id': self.env.uid, 'date_from': day, 'date_to': day, 'weight': 1},
            {'key': 'contacts', 'parent_key': 'root', 'name': 'Contact target', 'kind': 'metric',
             'item_id': self.item.id, 'owner_id': self.env.uid, 'date_from': day, 'date_to': day,
             'weight': 2, 'direction': 'higher', 'baseline': 0, 'target': 10,
             'note': 'An explicit example target, not a benchmark.'},
        ]
        self.board.save_scorecard(self.nodes, self.board._scorecard_revision(), self.options)

    def test_scorecard_round_trip_rebinds_widget_and_preserves_targets(self):
        payload = self.board.export_definition()
        self.assertEqual(payload['scorecard']['owner_policy'], 'importing_user')
        for row in payload['scorecard']['nodes']:
            self.assertNotIn('item_id', row)
            self.assertNotIn('owner_id', row)
        result = self.env['eh.board.dashboard'].import_definition(payload)
        imported = self.env['eh.board.dashboard'].browse(result['dashboard_id'])
        self.assertEqual(imported.state, 'draft')
        metric = imported.scorecard_node_ids.filtered(lambda node: node.kind == 'metric')
        self.assertEqual(metric.item_id.dashboard_id, imported)
        self.assertNotEqual(metric.item_id, self.item)
        self.assertEqual(metric.target, 10)
        self.assertEqual(metric.weight, 2)
        self.assertEqual(metric.owner_id, self.env.user)
        self.assertEqual(metric.parent_id.name, 'Team objective')
        self.assertEqual(metric.date_from, self.board.scorecard_node_ids[0].date_from)
        self.assertEqual(metric.note, self.nodes[1]['note'])

    def test_template_round_trip_preserves_scorecard(self):
        saved = self.board.save_as_template('Reusable team objective')
        imported = self.env['eh.board.template'].browse(saved['template_id']).create_from_template()
        self.assertEqual(len(imported.scorecard_node_ids), 2)
        self.assertEqual(imported.scorecard_node_ids.filtered(lambda node: node.kind == 'metric').item_id.dashboard_id, imported)

    def test_missing_widget_reference_fails_atomically(self):
        payload = self.board.export_definition()
        payload['scorecard']['nodes'][1]['item_ref'] = 'missing_widget'
        before = self.env['eh.board.dashboard'].search_count([])
        with self.assertRaises(ValidationError):
            self.env['eh.board.dashboard'].import_definition(payload)
        self.assertEqual(self.env['eh.board.dashboard'].search_count([]), before)

    def test_database_local_ids_are_rejected(self):
        payload = self.board.export_definition()
        payload['scorecard']['nodes'][1]['item_id'] = self.item.id
        with self.assertRaises(ValidationError):
            self.env['eh.board.dashboard'].import_definition(payload)

    def test_duplicate_widget_reference_is_rejected(self):
        payload = self.board.export_definition()
        payload['items'].append(copy.deepcopy(payload['items'][0]))
        with self.assertRaises(UserError):
            self.env['eh.board.dashboard'].import_definition(payload)

    def test_previous_schema_without_scorecard_still_imports(self):
        payload = self.board.export_definition()
        payload.pop('scorecard')
        for item in payload['items']:
            item.pop('ref')
        result = self.env['eh.board.dashboard'].import_definition(payload)
        imported = self.env['eh.board.dashboard'].browse(result['dashboard_id'])
        self.assertEqual(len(imported.item_ids), 1)
        self.assertFalse(imported.scorecard_node_ids)

    def test_guided_query_round_trip_revalidates_source_and_definition(self):
        side = {'model': 'res.partner', 'key': 'country_id', 'aggregate': 'count',
                'field': '', 'label': 'Contacts', 'filters': [
                    {'field': 'name', 'operator': 'ilike', 'value': 'Portable fixture'}]}
        result = self.board.apply_query({'version': 1, 'name': 'Portable comparison',
                                        'left': dict(side), 'right': dict(side),
                                        'formula': 'a - b', 'formula_label': 'Difference'})
        original = self.env['eh.board.item'].browse(result['meta']['id'])
        original.description = 'Old display definition must not override the restored query scope.'
        imported = self.env['eh.board.dashboard'].browse(
            self.env['eh.board.dashboard'].import_definition(self.board.export_definition())['dashboard_id'])
        item = imported.item_ids.filtered(lambda row: row.datasource_id.provider_type == 'join')
        self.assertEqual(len(item), 1)
        self.assertNotEqual(item.datasource_id, original.datasource_id)
        self.assertEqual(item.datasource_id.dashboard_id, imported)
        plan = item.datasource_id.config['guided_query']
        self.assertEqual(plan['company_id'], self.env.company.id)
        self.assertNotIn('model_id', plan['left'])
        self.assertEqual(item.description, imported._query_definition(plan))
        self.assertEqual(item.default_date_filter, 'none')
        self.assertFalse(item.get_payload({}).get('error'))

    def _plain_builder(self):
        group_field = "group_ids" if "group_ids" in self.env["res.users"]._fields else "groups_id"
        return self.env["res.users"].create({
            "name": "Portable ordinary builder", "login": "portable_ordinary_builder",
            "company_id": self.env.company.id, "company_ids": [(6, 0, self.env.company.ids)],
            group_field: [(6, 0, [self.env.ref("eh_board.group_board_builder").id])],
        })

    def test_nonadmin_metadata_round_trip_keeps_fields_filters_and_drills(self):
        builder = self._plain_builder()
        self.assertFalse(builder.has_group("base.group_erp_manager"))
        Dash = self.env["eh.board.dashboard"].with_user(builder)
        board = Dash.create({"name": "Ordinary builder portable chart"})
        model_id = self.env.ref("base.model_res_partner").id
        board._create_item_from_builder({
            "model_id": model_id, "title": "Contacts by country", "item_type": "bar",
            "measures": [{"verb": "sum", "field": "color", "label": "Color total"}],
            "dimension": "country_id", "secondary_dimension": "is_company",
            "date_field": "create_date", "sort_field": "name", "click_action": "drill",
            "drill_fields": ["state_id", "city"],
        })
        board._create_item_from_builder({
            "model_id": model_id, "title": "Contact rows", "item_type": "list",
            "list_mode": "records", "list_fields": ["name", "color"],
            "measures": [{"verb": "count", "label": "Contacts"}],
        })
        added = board.add_filter({"model_id": model_id, "field": "is_company", "name": "Companies"})
        self.assertEqual(added["filter"]["field"], "is_company")
        original = board.export_definition()
        imported = Dash.browse(Dash.import_definition(original)["dashboard_id"])
        copied = imported.export_definition()
        self.assertEqual(len(imported.item_ids), 2)
        self.assertEqual(len(imported.filter_ids), 1)
        first = copied["items"][0]
        for key in ("dimension", "secondary_dimension", "date_field", "sort_field", "drills", "measures"):
            self.assertEqual(first[key], original["items"][0][key])
        self.assertEqual(copied["items"][1]["list_fields"], ["name", "color"])
        self.assertEqual(copied["filters"], original["filters"])
        saved = board.save_as_template("Ordinary builder reusable chart")
        reapplied = self.env["eh.board.template"].with_user(builder).browse(saved["template_id"]).create_from_template()
        self.assertEqual(len(reapplied.item_ids), 2)
        self.assertEqual(len(reapplied.item_ids[0].drill_ids), 2)

    def test_restricted_field_metadata_is_not_exported_or_added_as_filter(self):
        builder = self._plain_builder()
        board = self.board.with_user(builder)
        model_id = self.env.ref("base.model_res_partner").id
        board._create_item_from_builder({"model_id": model_id, "title": "Restricted dimension",
                                         "item_type": "bar", "dimension": "color",
                                         "measures": [{"verb": "count", "label": "Contacts"}]})
        with patch.object(self.env["res.partner"]._fields["color"], "groups", "base.group_system"):
            with self.assertRaises(AccessError):
                board.export_definition()
            with self.assertRaises(AccessError):
                board.save_as_template("Must not expose hidden field metadata")
            with self.assertRaises(AccessError):
                board.add_filter({"model_id": model_id, "field": "color"})

    def test_restricted_filter_and_drill_imports_fail_without_partial_boards(self):
        builder = self._plain_builder()
        model_id = self.env.ref("base.model_res_partner").id
        self.board._create_item_from_builder({"model_id": model_id, "title": "Drilled contacts",
            "item_type": "bar", "dimension": "country_id", "drill_fields": ["color"],
            "click_action": "drill", "measures": [{"verb": "count", "label": "Contacts"}]})
        with_drill = self.board.export_definition()
        with_filter = copy.deepcopy(with_drill)
        with_filter["items"] = with_filter["items"][:1]
        with_filter["filters"] = [{"name": "Hidden filter", "type": "field", "model": "res.partner", "field": "color"}]
        models = ["eh.board.dashboard", "eh.board.item", "eh.board.datasource", "eh.board.scorecard.node"]
        before = {name: self.env[name].search_count([]) for name in models}
        with patch.object(self.env["res.partner"]._fields["color"], "groups", "base.group_system"):
            with self.assertRaises(UserError):
                self.env["eh.board.dashboard"].with_user(builder).import_definition(with_drill)
            with self.assertRaises(AccessError):
                self.env["eh.board.dashboard"].with_user(builder).import_definition(with_filter)
        self.assertEqual({name: self.env[name].search_count([]) for name in models}, before)
