"""Native query fixtures: preaggregation, scope, access and atomic persistence."""
from copy import deepcopy
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged

from ..lib import aggregation
from ..lib.registry import get_datasource


@tagged("post_install", "-at_install", "eh_board", "eh_board_query")
class TestBoardQuery(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.board = cls.env["eh.board.dashboard"].create({"name": "Guided query fixture"})
        cls.partners = cls.env["res.partner"].create([
            {"name": "Query fixture shared", "ref": "query-shared", "color": 10},
            {"name": "Query fixture left", "ref": "query-left", "color": 20},
            {"name": "Query fixture right", "ref": "query-right", "color": 30},
        ])
        group_field = "group_ids" if "group_ids" in cls.env["res.users"]._fields else "groups_id"
        cls.builder = cls.env["res.users"].create({
            "name": "Query builder", "login": "query_builder_fixture",
            "company_id": cls.env.company.id, "company_ids": [(6, 0, cls.env.company.ids)],
            group_field: [(6, 0, [cls.env.ref("eh_board.group_board_builder").id])],
        })
        cls.viewer = cls.env["res.users"].create({
            "name": "Query viewer", "login": "query_viewer_fixture",
            "company_id": cls.env.company.id, "company_ids": [(6, 0, cls.env.company.ids)],
            group_field: [(6, 0, [cls.env.ref("eh_board.group_board_viewer").id])],
        })

    def _plan(self):
        return {"version": 1, "name": "Customer comparison", "company_id": self.env.company.id,
                "left": {"model": "res.partner", "key": "ref", "aggregate": "count", "label": "Left",
                         "filters": [{"field": "id", "operator": "in", "value": self.partners[:2].ids}]},
                "right": {"model": "res.partner", "key": "ref", "aggregate": "count", "label": "Right",
                          "filters": [{"field": "id", "operator": "in", "value": (self.partners[0] + self.partners[2]).ids}]},
                "join_type": "full", "chart_type": "hbar", "limit": 100}

    def _portable_plan(self):
        plan = self._plan()
        for side in ("left", "right"):
            plan[side]["filters"] = [{"field": "name", "operator": "ilike", "value": "Query fixture"}]
        return plan

    def test_builder_gets_readable_fields_using_model_metadata_ids(self):
        model_id = self.env.ref("base.model_res_partner").id
        options = self.board.with_user(self.builder).query_options([model_id])
        self.assertIn("ref", [field["name"] for field in options["fields"][str(model_id)]])
        with patch.object(self.env["res.partner"]._fields["color"], "groups", "base.group_system"):
            options = self.board.with_user(self.builder).query_options([model_id])
            self.assertNotIn("color", [field["name"] for field in options["fields"][str(model_id)]])
        plan = self._plan()
        for side in ("left", "right"):
            plan[side].pop("model")
            plan[side]["model_id"] = model_id
        self.assertEqual(len(self.board.with_user(self.builder).preview_query(plan)["rows"]), 3)

    def test_full_left_and_inner_have_explicit_unmatched_keys(self):
        plan = self._plan()
        expected = {"full": 3, "left": 2, "inner": 1}
        for mode, count in expected.items():
            plan["join_type"] = mode
            result = self.board.preview_query(plan)
            self.assertEqual(len(result["rows"]), count)
            shared = next(row for row in result["rows"] if row["keys"] == ["query-shared"])
            self.assertEqual(shared["values"], {"left": 1, "right": 1})
            self.assertTrue(shared["matched"])
            if mode == "full":
                right = next(row for row in result["rows"] if row["keys"] == ["query-right"])
                self.assertEqual(right["values"], {"left": 0, "right": 1})
                self.assertFalse(right["left_present"])

    def test_cross_model_preaggregation_prevents_record_fanout(self):
        if "sale.order" not in self.env:
            self.skipTest("Sales must be installed for cross-model native fixture.")
        product = self.env["product.product"].create({"name": "Query service", "type": "service"})
        Line = self.env["sale.order.line"]
        tax_field = "tax_ids" if "tax_ids" in Line._fields else "tax_id"
        orders = self.env["sale.order"]
        for amounts in ((10, 20), (30,)):
            orders |= orders.create({"partner_id": self.partners[0].id, "company_id": self.env.company.id,
                "order_line": [(0, 0, {"product_id": product.id, "name": "Query line", "product_uom_qty": 1,
                                         "price_unit": amount, tax_field: [(5, 0, 0)]}) for amount in amounts]})
        plan = self._plan()
        plan["left"] = {"model": "sale.order", "key": "partner_id", "aggregate": "count", "label": "Orders",
                        "filters": [{"field": "id", "operator": "in", "value": orders.ids}]}
        plan["right"] = {"model": "sale.order.line", "key": "order_partner_id", "aggregate": "count", "label": "Lines",
                         "filters": [{"field": "id", "operator": "in", "value": orders.order_line.ids}]}
        result = self.board.preview_query(plan)
        self.assertEqual(len(result["rows"]), 1)
        self.assertEqual(result["rows"][0]["values"], {"left": 2, "right": 3})
        plan["left"].update({"aggregate": "sum", "field": "amount_untaxed"})
        plan["right"].update({"aggregate": "sum", "field": "price_subtotal"})
        monetary = self.board.preview_query(plan)
        self.assertAlmostEqual(monetary["rows"][0]["values"]["left"], 60)
        self.assertAlmostEqual(monetary["rows"][0]["values"]["right"], 60)
        self.assertEqual(monetary["unit"], self.env.company.currency_id.name)
        plan.update({"formula": "a/b", "formula_label": "Ratio"})
        saved = self.board.apply_query(plan)
        self.assertEqual(saved["payload"]["series"][0]["currency"]["id"], self.env.company.currency_id.id)
        self.assertFalse(saved["payload"]["series"][2]["currency"])
        currency = self.env["res.currency"].search([("id", "!=", self.env.company.currency_id.id)], limit=1)
        if currency:
            currency.active = True
            pricelist = self.env["product.pricelist"].create({"name": "Query foreign currency", "currency_id": currency.id})
            orders[:1].write({"pricelist_id": pricelist.id, "currency_id": currency.id})
            with self.assertRaises(ValidationError):
                self.board.preview_query(plan)

    def test_unassigned_keys_do_not_match_each_other(self):
        self.partners[:2].write({"ref": False})
        plan = self._plan()
        plan["left"]["filters"][0]["value"] = self.partners[:1].ids
        plan["right"]["filters"][0]["value"] = self.partners[1:2].ids
        result = self.board.preview_query(plan)
        self.assertEqual(len(result["rows"]), 2)
        self.assertTrue(all(not row["matched"] for row in result["rows"]))
        plan["join_type"] = "inner"
        self.assertEqual(self.board.preview_query(plan)["rows"], [])

    def test_each_side_filters_and_dates_are_independent(self):
        plan = self._plan()
        plan["left"]["filters"].append({"field": "color", "operator": ">", "value": 15})
        plan["right"].update({"date_field": "create_date", "date_start": "1900-01-01", "date_end": "1900-01-02"})
        result = self.board.preview_query(plan)
        self.assertEqual(len(result["rows"]), 1)
        self.assertEqual(result["rows"][0]["keys"], ["query-left"])
        self.assertEqual(result["rows"][0]["values"], {"left": 1, "right": 0})
        self.assertIn("1900-01-01", result["definition"])
        self.assertIn("filters", result["definition"])

    def test_preview_does_not_create_records_and_failed_apply_rolls_back(self):
        names = ["eh.board.datasource", "eh.board.item", "eh.board.measure", "eh.board.layout.version"]
        counts = {name: self.env[name].search_count([]) for name in names}
        result = self.board.preview_query(self._plan())
        self.assertEqual(len(result["rows"]), 3)
        self.assertEqual({name: self.env[name].search_count([]) for name in names}, counts)
        with patch.object(type(self.board), "_create_item_from_builder", side_effect=ValidationError("fixture write failure")):
            with self.assertRaises(ValidationError):
                self.board.apply_query(self._plan())
        self.assertEqual({name: self.env[name].search_count([]) for name in names}, counts)

    def test_apply_creates_reusable_source_with_fixed_definition(self):
        result = self.board.apply_query(self._plan())
        source = self.env["eh.board.datasource"].browse(result["source"]["id"])
        self.assertEqual(source.dashboard_id, self.board)
        self.assertFalse(result["source"]["editable"])
        self.assertFalse(result["payload"].get("error"), result)
        item = self.board._create_item_from_builder({"source_id": source.id, "item_type": "list", "title": "Reuse"})
        self.assertFalse(item.get_payload().get("error"))
        self.assertEqual(source._guided_authoring_metric()["allowed_dimensions"], [])
        with self.assertRaises(ValidationError):
            self.board._create_item_from_builder({"source_id": source.id, "item_type": "bar", "dimension": "name"})
        with self.assertRaises(ValidationError):
            source.write({"config": dict(source.config, guided_query=dict(source.config["guided_query"], formula="a-b"))})
        with self.assertRaises(UserError):
            source.copy()

    def test_division_by_zero_is_explicit_and_empty_results_are_valid(self):
        plan = self._plan()
        plan.update({"formula": "a / b * 100", "formula_label": "Ratio"})
        result = self.board.preview_query(plan)
        left = next(row for row in result["rows"] if row["keys"] == ["query-left"])
        self.assertEqual(left["values"]["formula"], 0)
        self.assertTrue(left["zero_divisor"])
        self.assertTrue(result["warnings"])
        self.assertTrue(self.board.apply_query(plan)["payload"]["warning"])
        for side in ("left", "right"):
            plan[side]["filters"] = [{"field": "id", "operator": "=", "value": -1}]
        empty = self.board.preview_query(plan)
        self.assertEqual(empty["rows"], [])
        self.assertEqual(empty["group_count"], 0)

    def test_query_tampering_and_incompatible_keys_are_rejected(self):
        patches = [{"company_id": self.env.company.id + 100000}, {"company_id": True}, {"version": True},
                   {"sql": "SELECT 1"}, {"formula": "__import__('os')"}, {"formula": "c+1"}, {"limit": 1001}]
        for updates in patches:
            plan = dict(self._plan(), **updates)
            with self.assertRaises(AccessError if "company_id" in updates else ValidationError):
                self.board.preview_query(plan)
        plan = self._plan()
        plan["right"]["key"] = "company_id"
        with self.assertRaises(ValidationError):
            self.board.preview_query(plan)
        plan = self._plan()
        plan["right"]["filters"].append({"field": "company_id.name", "operator": "=", "value": "Secret"})
        with self.assertRaises(ValidationError):
            self.board.preview_query(plan)

    def test_selected_company_scope_cannot_leak_other_company_records(self):
        company = self.env["res.company"].create({"name": "Query other company"})
        self.partners[2].company_id = company
        plan = self._plan()
        result = self.board.with_context(allowed_company_ids=[self.env.company.id, company.id]).preview_query(plan)
        self.assertFalse(any(row["keys"] == ["query-right"] for row in result["rows"]))
        with self.assertRaises(AccessError):
            self.board.with_user(self.builder).preview_query(dict(plan, company_id=company.id))

    def test_field_groups_are_rechecked_for_both_sides_and_saved_sources(self):
        plan = self._plan()
        plan["right"]["filters"].append({"field": "color", "operator": ">=", "value": 0})
        result = self.board.apply_query(plan)
        source = self.env["eh.board.datasource"].browse(result["source"]["id"])
        with patch.object(self.env["res.partner"]._fields["color"], "groups", "base.group_system"):
            with self.assertRaises(AccessError):
                self.board.with_user(self.builder).preview_query(plan)
            with self.assertRaises(AccessError):
                source.with_user(self.builder)._guided_authoring_metric()
            with self.assertRaises(AccessError):
                get_datasource("join").aggregate(source.with_user(self.builder), {})

    def test_viewer_cannot_author_but_saved_results_use_viewer_record_rules(self):
        for method, args in (("query_options", []), ("preview_query", [self._plan()]), ("apply_query", [self._plan()])):
            with self.assertRaises(AccessError):
                getattr(self.board.with_user(self.viewer), method)(*args)
        saved = self.board.apply_query(self._plan())
        self.board.write({"shared_user_ids": [(4, self.viewer.id)]})
        self.env["ir.rule"].create({"name": "Query restricted partner fixture", "model_id": self.env.ref("base.model_res_partner").id,
                                    "domain_force": "[('id', '!=', %s)]" % self.partners[0].id})
        source = self.env["eh.board.datasource"].browse(saved["source"]["id"]).with_user(self.viewer)
        rows = get_datasource("join").aggregate(source, {})["rows"]
        self.assertFalse(any(row["keys"] == ["query-shared"] for row in rows))
        self.assertEqual(len(rows), 2)

    def test_group_cap_refuses_partial_totals(self):
        with patch.object(aggregation, "grouped_read", return_value=[("key-%s" % i, 1) for i in range(1001)]):
            with self.assertRaises(ValidationError):
                self.board.preview_query(self._plan())

    def test_mixed_measure_units_are_rejected(self):
        plan = self._plan()
        plan["right"].update({"aggregate": "sum", "field": "color"})
        with self.assertRaises(ValidationError):
            self.board.preview_query(plan)

    def test_portable_source_rebinds_company_and_rejects_database_ids(self):
        saved = self.board.apply_query(self._portable_plan())
        source = self.env["eh.board.datasource"].browse(saved["source"]["id"])
        config = source._guided_portable_config()
        self.assertNotIn("company_id", config["guided_query"])
        self.assertEqual(config["guided_query_company"], "current_company")
        target = self.env["res.company"].create({"name": "Query import company"})
        board = self.env["eh.board.dashboard"].with_company(target).create({"name": "Query import"})
        restored = board._restore_guided_query_config(config)
        self.assertEqual(restored["guided_query"]["company_id"], target.id)
        self.assertEqual(restored["guided_query"]["left"]["model"], "res.partner")
        with self.assertRaises(ValidationError):
            board._restore_guided_query_config(dict(config, guided_query=dict(config["guided_query"], company_id=self.env.company.id)))
        bad = deepcopy(config)
        bad["guided_query"]["left"].pop("model")
        bad["guided_query"]["left"]["model_id"] = self.env.ref("base.model_res_partner").id
        with self.assertRaises(ValidationError):
            board._restore_guided_query_config(bad)
        saved = self.board.apply_query(self._plan())
        with self.assertRaises(ValidationError):
            self.env["eh.board.datasource"].browse(saved["source"]["id"])._guided_portable_config()

    def test_source_cannot_be_reused_on_another_dashboard(self):
        saved = self.board.apply_query(self._plan())
        source = self.env["eh.board.datasource"].browse(saved["source"]["id"])
        other = self.env["eh.board.dashboard"].create({"name": "Foreign query board"})
        item = self.env["eh.board.item"].create({"title": "Foreign", "dashboard_id": other.id,
                                                "datasource_id": source.id, "item_type": "bar"})
        with self.assertRaises(AccessError):
            get_datasource("join").aggregate(source, {"item_id": item.id})
        with self.assertRaises(ValidationError):
            get_datasource("join").aggregate(source, {"domain": [("id", "=", 1)]})
