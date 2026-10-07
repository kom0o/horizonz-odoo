# -*- coding: utf-8 -*-
# Copyright (C) 2026 ERP Heritage.
"""Authoring safety at the public RPC boundary; providers always stubbed."""
import copy
import json
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "eh_board")
class TestBoardAuthoring(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Dashboard = cls.env["eh.board.dashboard"]
        cls.AI = cls.env["eh.board.ai"]
        cls.ICP = cls.env["ir.config_parameter"].sudo()
        cls.dashboard = cls.Dashboard.create({"name": "Authoring fixture"})
        cls.foreign = cls.Dashboard.create({"name": "Other draft"})
        cls.model_id = cls.env["ir.model"]._get("res.partner").id
        cls.partners = cls.env["res.partner"].create([
            {"name": "Authoring first", "is_company": True},
            {"name": "Authoring second", "is_company": False},
        ])
        groups_field = "group_ids" if "group_ids" in cls.env["res.users"]._fields else "groups_id"
        cls.viewer = cls.env["res.users"].create({
            "name": "Authoring viewer", "login": "eh_board_authoring_viewer",
            groups_field: [(6, 0, [cls.env.ref("eh_board.group_board_viewer").id])],
        })
        cls.catalog = [{
            "id": "test.partner_count.v1", "title": "Fixture contacts",
            "description": "Count only fixture contacts.", "model": "res.partner",
            "builder_vals": {"item_type": "tile", "default_date_filter": "none"},
            "allowed_charts": ["tile", "bar", "line"],
            "allowed_dimensions": [{"field": "is_company", "label": "Company"},
                                   {"field": "create_date", "label": "Created"}],
            "date_field": "create_date", "allowed_date_presets": ["none", "this_year"],
            "assumptions": ["Fixture data only."],
        }]

    def setUp(self):
        super().setUp()
        self.ICP.set_param("eh_board.ai_authoring_daily_requests", "20")
        self.ICP.set_param("eh_board.authoring_usage.%s" % self.env.uid, "{}")
        self.catalog_patch = patch.object(type(self.dashboard), "_metric_authoring_catalog", return_value=copy.deepcopy(self.catalog))
        self.catalog_patch.start()
        self.addCleanup(self.catalog_patch.stop)
        test = self

        def create_metric(board, metric_id, overrides=None):
            if metric_id != "test.partner_count.v1":
                raise AccessError("Unexpected metric")
            vals = {
                "model_id": test.model_id, "item_type": "tile", "title": "Fixture contacts",
                "measure": {"verb": "count", "label": "Contacts"},
                "domain": repr([("id", "in", test.partners.ids)]),
                "date_field": "create_date", "record_limit": 20, "show_trend": False,
            }
            vals.update(overrides or {})
            return board._create_item_from_builder(vals)

        self.create_metric = create_metric
        self.create_patch = patch.object(type(self.dashboard), "_create_business_metric", create_metric)
        self.create_patch.start()
        self.addCleanup(self.create_patch.stop)

    def plan(self, count=1):
        return {"version": 1, "items": [
            {"id": "w%s" % index, "metric_id": "test.partner_count.v1", "title": "Contacts",
             "item_type": "tile", "dimension": "", "date_preset": "none", "granularity": "month"}
            for index in range(count)], "assumptions": [], "unavailable": []}

    def counts(self):
        return {name: self.env[name].search_count([]) for name in (
            "eh.board.item", "eh.board.datasource", "eh.board.measure", "eh.board.layout.version")}

    def test_preview_does_not_persist(self):
        before = self.counts()
        result = self.dashboard.preview_authoring_plan(self.plan())
        self.assertTrue(result["can_apply"])
        self.assertEqual(len(result["previews"]), 1)
        self.assertEqual(self.counts(), before)
        self.assertFalse(self.dashboard.item_ids)

    def test_apply_uses_trusted_metric_and_selection(self):
        plan = self.plan(2)
        result = self.dashboard.apply_authoring_plan(plan, ["w1"])
        self.assertEqual(result["created"], 1)
        item = self.env["eh.board.item"].browse(result["item_ids"])
        self.assertEqual(item.dashboard_id, self.dashboard)
        self.assertEqual(item.model_name, "res.partner")
        self.assertEqual(item.item_type, "tile")
        self.assertEqual(len(self.dashboard._active_layout().grid), 1)

    def test_rejects_injected_configuration(self):
        for key, value in [
            ("query", "SELECT * FROM res_users"), ("domain", "[]"),
            ("model_id", self.env["ir.model"]._get("res.users").id),
            ("target", 100000), ("python_code", "env['res.users'].sudo().search([])"),
            ("datasource_id", 1), ("measure_ids", [[6, 0, [1]]]),
        ]:
            proposal = self.plan()
            proposal["items"][0][key] = value
            with self.assertRaises(ValidationError):
                self.dashboard.apply_authoring_plan(proposal)
        self.assertFalse(self.dashboard.item_ids)

    def test_rejects_unknown_metrics_dimensions_and_periods(self):
        plan = self.plan()
        plan["items"][0]["metric_id"] = "forbidden.metric.v1"
        with self.assertRaises(AccessError):
            self.dashboard.apply_authoring_plan(plan)
        for key, value in [("dimension", "user_id.password"), ("date_preset", "2099"),
                           ("item_type", "richtext"), ("granularity", "second")]:
            plan = self.plan()
            plan["items"][0][key] = value
            with self.assertRaises(ValidationError):
                self.dashboard.preview_authoring_plan(plan)

    def test_card_and_chart_dimension_contract(self):
        plan = self.plan()
        plan["items"][0]["dimension"] = "is_company"
        with self.assertRaises(ValidationError):
            self.dashboard.preview_authoring_plan(plan)
        plan["items"][0].update({"item_type": "bar", "dimension": ""})
        with self.assertRaises(ValidationError):
            self.dashboard.preview_authoring_plan(plan)

    def test_viewer_cannot_generate_preview_or_apply(self):
        board = self.dashboard.with_user(self.viewer)
        for method, args in (("get_authoring_options", ()), ("generate_authoring_plan", ("Count contacts",)),
                             ("preview_authoring_plan", (self.plan(),)), ("apply_authoring_plan", (self.plan(),))):
            with self.assertRaises(AccessError):
                getattr(board, method)(*args)

    def test_catalog_rights_revalidated_at_apply(self):
        plan = self.dashboard.preview_authoring_plan(self.plan())["plan"]
        with patch.object(type(self.dashboard), "_metric_authoring_catalog", return_value=[]):
            with self.assertRaises(AccessError):
                self.dashboard.apply_authoring_plan(plan)
        self.assertFalse(self.dashboard.item_ids)

    def test_partial_failure_rolls_back_items_sources_measures_and_layout(self):
        old = self.create_metric(self.dashboard, "test.partner_count.v1")
        self.dashboard.save_layout({str(old.id): {"x": 0, "y": 0, "w": 3, "h": 4}})
        before = self.counts()
        grid = copy.deepcopy(self.dashboard._active_layout().grid)
        calls = []

        def fail_second(board, metric_id, overrides=None):
            calls.append(metric_id)
            if len(calls) == 2:
                raise ValidationError("Fixture second item failed")
            return self.create_metric(board, metric_id, overrides)

        with patch.object(type(self.dashboard), "_create_business_metric", fail_second):
            with self.assertRaises(ValidationError):
                self.dashboard.apply_authoring_plan(self.plan(2), replace_item_ids=[old.id])
        self.assertEqual(self.counts(), before)
        self.assertTrue(old.exists())
        self.assertEqual(self.dashboard.item_ids, old)
        self.assertEqual(self.dashboard._active_layout().grid, grid)

    def test_replacement_requires_same_board_and_draft(self):
        foreign_item = self.create_metric(self.foreign, "test.partner_count.v1")
        with self.assertRaises(UserError):
            self.dashboard.apply_authoring_plan(self.plan(), replace_item_ids=[foreign_item.id])
        old = self.create_metric(self.dashboard, "test.partner_count.v1")
        self.dashboard.state = "published"
        with self.assertRaises(ValidationError):
            self.dashboard.apply_authoring_plan(self.plan(), replace_item_ids=[old.id])
        self.assertTrue(old.exists())

    def test_only_explicitly_selected_old_widgets_replaced(self):
        old = self.create_metric(self.dashboard, "test.partner_count.v1")
        retained = self.create_metric(self.dashboard, "test.partner_count.v1")
        result = self.dashboard.apply_authoring_plan(self.plan(), replace_item_ids=[old.id])
        self.assertEqual(result["replaced"], 1)
        self.assertFalse(old.exists())
        self.assertTrue(retained.exists())

    def test_invalid_model_output_is_charged_and_never_applied(self):
        self.ICP.set_param("eh_board.ai_authoring_daily_requests", "1")
        with patch.object(type(self.AI), "ai_available", return_value=True), \
                patch.object(type(self.AI), "_call_llm", return_value="not json") as provider:
            result = self.dashboard.generate_authoring_plan("Count fixture contacts")
            self.assertFalse(result["ok"])
            self.assertEqual(result["limits"]["remaining"], 0)
            again = self.dashboard.generate_authoring_plan("Try again")
            self.assertFalse(again["ok"])
            provider.assert_called_once()
        self.assertFalse(self.dashboard.item_ids)

    def test_provider_receives_catalogue_without_record_data(self):
        with patch.object(type(self.AI), "ai_available", return_value=True), \
                patch.object(type(self.AI), "_call_llm", return_value=json.dumps(self.plan())) as provider:
            result = self.dashboard.generate_authoring_plan("Count fixture contacts")
        self.assertTrue(result["ok"])
        sent = json.loads(provider.call_args.args[1])
        self.assertEqual(sent["catalogue"][0]["id"], "test.partner_count.v1")
        self.assertNotIn("builder_vals", sent["catalogue"][0])
        self.assertNotIn("Authoring first", provider.call_args.args[1])
        self.assertNotIn(self.env.cr.dbname, provider.call_args.args[1])
        self.assertFalse(self.dashboard.item_ids)

    def test_refinement_is_preview_only_and_bounded(self):
        refined = self.plan()
        refined["items"][0].update({"item_type": "bar", "dimension": "is_company"})
        with patch.object(type(self.AI), "ai_available", return_value=True), \
                patch.object(type(self.AI), "_call_llm", return_value=json.dumps(refined)) as provider:
            result = self.dashboard.generate_authoring_plan("Group by company", self.plan())
        self.assertTrue(result["ok"])
        self.assertEqual(result["plan"]["items"][0]["dimension"], "is_company")
        self.assertIsNotNone(json.loads(provider.call_args.args[1])["existing_proposal"])
        self.assertFalse(self.dashboard.item_ids)
        with self.assertRaises(ValidationError):
            self.dashboard.preview_authoring_plan(self.plan(9))

    def test_unsupported_request_returns_explanation_without_widgets(self):
        unsupported = {"version": 1, "items": [], "assumptions": [], "unavailable": ["No forecast metric is available."]}
        with patch.object(type(self.AI), "ai_available", return_value=True), \
                patch.object(type(self.AI), "_call_llm", return_value=json.dumps(unsupported)):
            result = self.dashboard.generate_authoring_plan("Forecast next year's sales")
        self.assertTrue(result["ok"])
        self.assertFalse(result["can_apply"])
        self.assertTrue(result["plan"]["unavailable"])
        self.assertFalse(self.dashboard.item_ids)

    def test_transport_output_limit_and_json_mode(self):
        class Response:
            status_code = 200
            def json(self):
                return {"choices": [{"message": {"content": "{}"}}]}
        cfg = {"provider": "openai", "model": "fixture", "base_url": "", "credential": "fixture"}
        with patch.object(type(self.AI), "_provider_config", return_value=cfg), \
                patch.object(type(self.AI), "_get_secret", return_value="fixture-key"), \
                patch("requests.post", return_value=Response()) as post:
            self.assertEqual(self.AI._call_llm("System", "Request", max_tokens=999999, json_mode=True), "{}")
        body = json.loads(post.call_args.kwargs["data"])
        self.assertEqual(body["max_tokens"], 4096)
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertFalse(post.call_args.kwargs["allow_redirects"])

    def test_no_provider_call_when_off(self):
        with patch.object(type(self.AI), "ai_available", return_value=False), \
                patch.object(type(self.AI), "_call_llm") as provider:
            self.assertFalse(self.dashboard.generate_authoring_plan("Count fixture contacts")["ok"])
            provider.assert_not_called()

    def test_narration_rejects_changed_numbers_sign_and_percent(self):
        facts = ["Contacts: 12. Balance: -1,200.50. Conversion: 25%."]
        for output in ["There are 13 contacts.", "Balance is 1,200.50.", "Contacts increased 12%.",
                       "Five contacts matter.", "Contacts doubled."]:
            with patch.object(type(self.AI), "_call_llm", return_value=output):
                self.assertIsNone(self.AI._narrate(facts), output)
        with patch.object(type(self.AI), "_call_llm", return_value="12 contacts. Balance: -1200.50. Conversion: 25%."):
            self.assertIsNotNone(self.AI._narrate(facts))

    def test_narration_checks_simple_number_words(self):
        self.assertTrue(self.AI._narrative_numbers_supported(["2 companies, 1 person"], "Two companies, one person."))
        self.assertFalse(self.AI._narrative_numbers_supported(["2 companies, 1 person"], "Three companies."))
