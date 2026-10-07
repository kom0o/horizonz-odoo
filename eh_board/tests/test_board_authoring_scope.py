# -*- coding: utf-8 -*-
# Copyright (C) 2026 ERP Heritage.
"""Explicit-scope authoring: real ORM previews and writes, no live AI calls."""
import base64
import copy
import json
from pathlib import Path
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import HttpCase, TransactionCase, tagged


@tagged("post_install", "-at_install", "eh_board", "eh_board_authoring_scope")
class TestBoardAuthoringScope(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.other_company = cls.env["res.company"].create({"name": "Authoring scope other"})
        group_field = "group_ids" if "group_ids" in cls.env["res.users"]._fields else "groups_id"
        cls.builder = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Scoped author", "login": "scoped_author",
            "company_id": cls.env.company.id,
            "company_ids": [(6, 0, [cls.env.company.id, cls.other_company.id])],
            group_field: [(6, 0, [cls.env.ref("base.group_user").id,
                                  cls.env.ref("eh_board.group_board_builder").id])],
        })
        cls.board = cls.env["eh.board.dashboard"].create({
            "name": "Scoped authoring", "owner_id": cls.builder.id,
            "company_ids": [(6, 0, [cls.env.company.id, cls.other_company.id])],
        }).with_user(cls.builder).with_context(allowed_company_ids=[cls.env.company.id, cls.other_company.id])
        cls.model = cls.env["ir.model"]._get("res.partner")
        cls.partners = cls.env["res.partner"].create([
            {"name": "Scoped local", "company_id": cls.env.company.id, "is_company": True},
            {"name": "Scoped shared", "company_id": False, "is_company": False},
            {"name": "Scoped other", "company_id": cls.other_company.id, "is_company": True},
        ])
        cls.source = cls.env["eh.board.datasource"].create({
            "name": "Approved contact subset", "dashboard_id": cls.board.id,
            "provider_type": "orm", "model_id": cls.model.id,
            "domain": repr([("id", "in", cls.partners.ids)]),
        })
        cls.scope = {"models": [cls.model.id], "sources": []}
        cls.source_scope = {"models": [], "sources": [cls.source.id]}

    def metric(self, scope=None, verb="count"):
        scope = self.scope if scope is None else scope
        return next(spec for spec in self.board._authoring_catalog(scope).values()
                    if spec.get("scoped") and spec["builder_vals"].get("measure", {}).get("verb") == verb)

    def plan(self, scope=None, verb="count"):
        metric = self.metric(scope, verb)
        return {"version": 1, "items": [{"id": "w1", "metric_id": metric["id"],
                "title": "Readable contacts", "item_type": "kpi", "dimension": "",
                "date_preset": "none", "granularity": "month"}], "assumptions": [], "unavailable": []}

    def counts(self):
        return {name: self.env[name].search_count([]) for name in (
            "eh.board.item", "eh.board.datasource", "eh.board.measure", "eh.board.layout.version")}

    def test_new_model_preview_is_real_and_leaves_no_records(self):
        before = self.counts()
        result = self.board.preview_authoring_plan(self.plan(self.source_scope), self.source_scope)
        self.assertTrue(result["can_apply"], result)
        self.assertEqual(result["previews"][0]["payload"]["value"], 2)
        self.assertEqual(self.counts(), before)

    def test_generic_apply_preserves_source_and_current_company_scope(self):
        result = self.board.apply_authoring_plan(self.plan(self.source_scope), data_scope=self.source_scope)
        item = self.env["eh.board.item"].browse(result["item_ids"])
        self.assertEqual(item.datasource_id, self.source)
        self.assertIn(("company_id", "in", [False, self.env.company.id]), item._effective_domain({}))
        self.assertEqual(item.with_user(self.builder).get_payload()["value"], 2)
        self.assertFalse(item.business_metric_id)
        self.assertFalse(item.measure_ids.target_value)

    def test_non_monetary_sum_and_average_use_real_scoped_values(self):
        spec = self.metric(self.source_scope, "sum")
        field = spec["builder_vals"]["measure"]["field"]
        for partner, value in zip(self.partners, (4, 8, 1000)):
            partner[field] = value
        for verb, expected in (("sum", 12), ("avg", 6)):
            result = self.board.preview_authoring_plan(self.plan(self.source_scope, verb), self.source_scope)
            self.assertTrue(result["can_apply"], result)
            self.assertEqual(result["previews"][0]["payload"]["value"], expected)

    def test_model_scope_does_not_inherit_an_existing_source_filter(self):
        result = self.board.apply_authoring_plan(self.plan(), data_scope=self.scope)
        item = self.env["eh.board.item"].browse(result["item_ids"])
        self.assertNotEqual(item.datasource_id, self.source)
        self.assertEqual(item.datasource_id.get_domain(), [])

    def test_scope_is_explicit_and_cannot_be_injected(self):
        for scope in ([self.model.id], {"models": [True]}, {"models": [self.model.id] * 2},
                      {"models": [1, 2, 3], "sources": [self.source.id]},
                      {"models": [self.model.id], "domain": "[]"}, {"models": [self.model.id], "fields": ["password"]}):
            with self.subTest(scope=scope), self.assertRaises(ValidationError):
                self.board.get_authoring_options(scope)
        with self.assertRaises(AccessError):
            self.board.apply_authoring_plan(self.plan())

    def test_only_owned_active_sources_are_accepted(self):
        foreign = self.env["eh.board.dashboard"].create({"name": "Other scope board"})
        source = self.source.copy({"dashboard_id": foreign.id})
        with self.assertRaises(UserError):
            self.board.get_authoring_options({"sources": source.ids})
        self.source.active = False
        with self.assertRaises(AccessError):
            self.board.get_authoring_options(self.source_scope)

    def test_changed_source_definition_invalidates_reviewed_plan(self):
        plan = self.board.preview_authoring_plan(self.plan(self.source_scope), self.source_scope)["plan"]
        self.source.domain = "[]"
        with self.assertRaises(AccessError):
            self.board.apply_authoring_plan(plan, data_scope=self.source_scope)
        self.assertFalse(self.board.item_ids)

    def test_changed_company_context_invalidates_reviewed_plan(self):
        plan = self.plan()
        switched = self.board.with_context(allowed_company_ids=[self.other_company.id, self.env.company.id])
        with self.assertRaises(AccessError):
            switched.apply_authoring_plan(plan, data_scope=self.scope)

    def test_revoked_model_access_is_rechecked_before_apply(self):
        plan = self.plan()
        Model = self.env["res.partner"]
        access_method = "check_access" if hasattr(Model, "check_access") else "check_access_rights"
        with self.assertRaises(AccessError):
            with patch.object(type(Model), access_method, side_effect=AccessError("Read permission revoked")):
                self.board.apply_authoring_plan(plan, data_scope=self.scope)
        self.assertFalse(self.board.item_ids)

    def test_restricted_breakdown_is_not_offered_and_stale_plan_is_rejected(self):
        metric = self.metric()
        dimension = next(row["field"] for row in metric["allowed_dimensions"]
                         if row["field"] not in {"create_date", "write_date"})
        plan = self.plan()
        plan["items"][0].update(item_type="bar", dimension=dimension)
        with patch.object(self.env["res.partner"]._fields[dimension], "groups", "base.group_system"):
            restricted = self.metric()
            self.assertNotIn(dimension, [row["field"] for row in restricted["allowed_dimensions"]])
            with self.assertRaises(AccessError):
                self.board.apply_authoring_plan(plan, data_scope=self.scope)

    def test_numeric_field_groups_are_checked_without_metadata_escalation(self):
        sums = [spec for spec in self.board._authoring_catalog(self.scope).values()
                if spec.get("scoped") and spec["builder_vals"]["measure"]["verb"] == "sum"]
        self.assertTrue(sums)
        field = sums[0]["builder_vals"]["measure"]["field"]
        with patch.object(self.env["res.partner"]._fields[field], "groups", "base.group_system"):
            metrics = self.board._authoring_catalog(self.scope)
            self.assertNotIn(sums[0]["id"], metrics)
            self.assertFalse(any(spec.get("scoped") and spec["builder_vals"]["measure"].get("field") == field
                                 for spec in metrics.values()))

    def test_monetary_fields_never_become_generic_totals(self):
        Model = self.env["res.partner"]
        money = [name for name, field in Model._fields.items() if field.type == "monetary" and field.store]
        if not money and "account.move" in self.env:
            Model = self.env["account.move"]
            money = [name for name, field in Model._fields.items() if field.type == "monetary" and field.store]
        if not money:
            self.skipTest("No installed model with stored monetary fields")
        specs = self.board.sudo()._authoring_model_metrics(self.env["ir.model"]._get(Model._name).id)
        self.assertTrue(money)
        self.assertFalse(any(spec["builder_vals"]["measure"].get("field") in money for spec in specs))

    def test_saved_snapshot_counts_do_not_sum_untyped_money_columns(self):
        source = self.env["eh.board.datasource"].create({
            "name": "Mixed currency snapshot", "dashboard_id": self.board.id, "provider_type": "file",
            "file_name": "currencies.csv",
            "file_data": base64.b64encode(b"currency,amount\nUSD,100\nJPY,10000\n"),
        })
        source.action_parse_file()
        scope = {"sources": source.ids}
        specs = [spec for spec in self.board._authoring_catalog(scope).values() if spec.get("scoped")]
        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0]["builder_vals"]["measure"]["verb"], "count")
        preview = self.board.preview_authoring_plan(self.plan(scope), scope)
        self.assertTrue(preview["can_apply"], preview)
        self.assertEqual(preview["previews"][0]["payload"]["value"], 2)

    def test_date_basis_is_validated_and_saved(self):
        spec = self.metric()
        self.assertTrue(spec["allowed_date_fields"])
        selected = spec["allowed_date_fields"][-1]["field"]
        plan = self.plan()
        plan["items"][0].update(date_field=selected, date_preset="this_year")
        result = self.board.apply_authoring_plan(plan, data_scope=self.scope)
        item = self.env["eh.board.item"].browse(result["item_ids"])
        self.assertEqual(item.date_filter_field_id.name, selected)
        self.assertEqual(item.default_date_filter, "this_year")
        plan["items"][0]["date_field"] = "password"
        with self.assertRaises(ValidationError):
            self.board.apply_authoring_plan(plan, data_scope=self.scope)

    def test_partial_failure_rolls_back_all_items_sources_and_layout(self):
        plan = self.plan()
        plan["items"].append(dict(plan["items"][0], id="w2"))
        before = self.counts()
        real = type(self.board)._create_authoring_metric
        calls = []

        def create(board, *args):
            calls.append(True)
            if len(calls) == 2:
                raise ValidationError("Second selected item failed")
            return real(board, *args)

        with patch.object(type(self.board), "_create_authoring_metric", create), self.assertRaises(ValidationError):
            self.board.apply_authoring_plan(plan, data_scope=self.scope)
        self.assertEqual(self.counts(), before)
        self.assertFalse(self.board.item_ids)

    def test_provider_receives_only_accessible_metadata_and_real_preview(self):
        AI = self.env["eh.board.ai"]
        plan = self.plan(self.source_scope)
        with patch.object(type(AI), "ai_available", return_value=True), \
                patch.object(type(AI), "_call_llm", return_value=json.dumps(plan)) as transport:
            result = self.board.generate_authoring_plan("Count contacts", data_scope=self.source_scope)
        self.assertTrue(result["can_apply"], result)
        sent = transport.call_args.args[1]
        self.assertNotIn(self.partners[0].name, sent)
        self.assertNotIn('"domain"', sent)
        self.assertNotIn('"builder_vals"', sent)
        self.assertEqual(result["previews"][0]["payload"]["value"], 2)

    def test_catalogue_and_picker_bounds(self):
        self.assertLessEqual(len(self.board.search_authoring_models()), 40)
        scoped = [spec for spec in self.board._authoring_catalog(self.scope).values() if spec.get("scoped")]
        self.assertLessEqual(len(scoped), 5)
        self.assertTrue(all(len(spec["allowed_dimensions"]) <= 6 for spec in scoped))
        self.assertTrue(all(len(spec["allowed_date_fields"]) <= 3 for spec in scoped))
        with self.assertRaises(ValidationError):
            self.board.search_authoring_models("x" * 81)

    def test_saved_guided_query_preserves_fixed_definition_and_redacts_provider_metadata(self):
        plan = {"version": 1, "name": "Approved contact comparison", "company_id": self.env.company.id,
                "left": {"model": "res.partner", "key": "name", "aggregate": "count", "label": "Left",
                         "filters": [{"field": "name", "operator": "=", "value": self.partners[0].name}]},
                "right": {"model": "res.partner", "key": "name", "aggregate": "count", "label": "Right",
                          "filters": [{"field": "name", "operator": "=", "value": self.partners[0].name}]},
                "join_type": "full", "chart_type": "hbar", "limit": 100}
        result = self.board.apply_query(plan)
        source_id = result["source"]["id"]
        scope = {"sources": [source_id]}
        spec = next(value for value in self.board._authoring_catalog(scope).values() if value.get("scoped"))
        self.assertTrue(spec["fixed_grouping"])
        self.assertNotIn(self.partners[0].name, json.dumps(self.board._authoring_public_metric(spec)))
        proposed = {"version": 1, "items": [{"id": "w1", "metric_id": spec["id"],
                    "title": "Reviewed fixed comparison", "item_type": "hbar", "dimension": "",
                    "date_preset": "none", "granularity": "month"}], "assumptions": [], "unavailable": []}
        preview = self.board.preview_authoring_plan(proposed, scope)
        self.assertTrue(preview["can_apply"], preview)
        saved = self.board.apply_authoring_plan(proposed, data_scope=scope)
        item = self.env["eh.board.item"].browse(saved["item_ids"])
        self.assertEqual(item.datasource_id.id, source_id)
        self.assertFalse(item.measure_ids)
        self.assertFalse(item.primary_dimension_id)
        self.assertFalse(item.get_payload().get("error"))


@tagged("post_install", "-at_install", "eh_board", "eh_board_authoring_scope_ui")
class TestBoardAuthoringScopeUI(HttpCase):
    def test_data_picker_invalidates_old_preview_and_applies_scoped_metric(self):
        Dashboard = self.env["eh.board.dashboard"]
        Dashboard.search([]).unlink()
        board = Dashboard.create({"name": "Scope browser", "state": "published", "refresh_mode": "off"})
        partners = self.env["res.partner"].create([
            {"name": "Scope browser %s" % index, "company_id": self.env.company.id} for index in range(3)])
        model = self.env["ir.model"]._get("res.partner")
        source = self.env["eh.board.datasource"].create({
            "name": "Scope browser selected source", "dashboard_id": board.id,
            "provider_type": "orm", "model_id": model.id, "domain": repr([("id", "in", partners.ids)])})
        board._create_item_from_builder({"source_id": source.id, "item_type": "kpi", "title": "Existing contacts",
                                         "measure": {"verb": "count", "label": "Contacts"}, "show_trend": False})
        config = self.env["ir.config_parameter"].sudo()
        config.set_param("eh_board.authoring_usage.%s" % self.env.ref("base.user_admin").id, "{}")

        def provider(_system, user_context, **_kwargs):
            catalogue = json.loads(user_context)["catalogue"]
            metric = next(row for row in catalogue if row["id"].startswith("scope.source%s.count.records." % source.id))
            return json.dumps({"version": 1, "items": [{"id": "contacts", "metric_id": metric["id"],
                "title": "Scoped AI contacts", "item_type": "kpi", "dimension": "", "date_preset": "none",
                "granularity": "month"}], "assumptions": [], "unavailable": []})

        self.env.cr.flush()
        script = (Path(__file__).resolve().parents[1] / "static/tests/authoring_scope_tour.js").read_text()
        with patch.object(type(self.env["eh.board.ai"]), "ai_available", return_value=True), \
                patch.object(type(self.env["eh.board.ai"]), "_call_llm", side_effect=provider) as transport:
            self.browser_js("/web#action=eh_board.action_eh_board_open",
                script + "\nwindow.ehAuthoringScopeTour(%s).catch((error) => console.error(error));" % json.dumps(
                    {"sourceId": source.id, "modelId": model.id}),
                "!!document.querySelector('.eh_board_app .eh_board_widget')", login="admin", timeout=100)
        self.assertEqual(transport.call_count, 2)
        created = self.env["eh.board.item"].search([("dashboard_id", "=", board.id), ("title", "=", "Scoped AI contacts")])
        self.assertEqual(len(created), 1)
        self.assertEqual(created.datasource_id, source)
        self.assertEqual(created.get_payload()["value"], 3)
        self.assertEqual(len(board.item_ids), 2)
