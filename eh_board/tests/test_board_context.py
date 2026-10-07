"""Regression fixtures for one analysis context and exact aggregate totals."""
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged

from ..controllers.main import EhBoardController


@tagged("post_install", "-at_install", "eh_board")
class TestBoardContext(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.board = cls.env["eh.board.dashboard"].create({"name": "Scope fixture"})
        cls.partners = cls.env["res.partner"].create([
            {"name": "Context A", "color": 10, "country_id": cls.env.ref("base.au").id},
            {"name": "Context B", "color": 20, "country_id": cls.env.ref("base.au").id},
            {"name": "Context C", "color": 90, "country_id": cls.env.ref("base.us").id},
        ])
        cls.source = cls.env["eh.board.datasource"].create({
            "name": "Context partners", "provider_type": "orm",
            "dashboard_id": cls.board.id,
            "model_id": cls.env["ir.model"]._get("res.partner").id,
            "domain": repr([("id", "in", cls.partners.ids)]),
        })
        cls.country = cls.env["ir.model.fields"]._get("res.partner", "country_id")
        cls.measure = cls.env["eh.board.measure"].create({
            "name": "Average", "datasource_id": cls.source.id, "aggregate": "avg",
            "field_id": cls.env["ir.model.fields"]._get("res.partner", "color").id,
        })
        cls.item = cls.env["eh.board.item"].create({
            "title": "Average", "dashboard_id": cls.board.id, "datasource_id": cls.source.id,
            "item_type": "bar", "primary_dimension_id": cls.country.id,
            "measure_ids": [(6, 0, cls.measure.ids)], "record_limit": 1,
        })
        cls.au_options = {"filters": [{"field": "country_id", "model": "res.partner",
            "relation": "res.country", "values": [cls.env.ref("base.au").id]}]}

    def test_insight_and_pdf_follow_active_filter(self):
        self.item.item_type = "kpi"
        selected = self.board.get_export_data(self.au_options)["items"][0]
        self.assertEqual(selected["value"], 15)
        insights = self.board.get_insights(self.au_options)
        self.assertIn("15", insights[0]["text"])
        self.assertNotIn("40", insights[0]["text"])
        report = self.board.with_context(eh_board_options=self.au_options)._report_data()
        self.assertEqual(report[0]["value"], "15")
        self.assertEqual(self.board._report_data()[0]["value"], "40")

    def test_drilled_export_matches_visible_payload(self):
        field = self.env["ir.model.fields"]._get("res.partner", "is_company")
        self.item.drill_ids = [(0, 0, {"field_id": field.id})]
        path = [{"field": "country_id", "value": self.env.ref("base.au").id, "label": "Australia"}]
        shown = self.board.get_item_drilled(self.item.id, path, {})
        exported = self.board.get_export_data({"drill_paths": {str(self.item.id): path}})["items"][0]
        self.assertEqual(exported["rows"], shown["rows"])
        self.assertEqual(exported["drill_depth"], 1)
        self.assertIn("15", self.board.get_insights({"drill_paths": {str(self.item.id): path}})[0]["text"])

    def test_export_includes_lazy_widgets(self):
        for index in range(10):
            self.item.copy({"title": "Extra %s" % index})
        lazy = self.board.get_data(lazy=True)
        complete = self.board.get_export_data(self.au_options)
        self.assertTrue(lazy["lazy_ids"])
        self.assertEqual(len(complete["items"]), 11)
        self.assertFalse(complete["lazy_ids"])

    def test_average_snapshot_recomputes_full_scope(self):
        self.assertEqual(self.item._headline_value(), 40)
        self.assertEqual(self.item._headline_value(self.au_options), 15)
        self.board.capture_snapshot()
        snap = self.env["eh.board.snapshot"].search([("item_id", "=", self.item.id)], limit=1)
        self.assertEqual(snap.value, 40)

    def test_distinct_and_formula_are_recomputed_at_total_grain(self):
        self.measure.write({"aggregate": "count_distinct", "field_id": self.country.id})
        self.assertEqual(self.item._headline_value(), 2)
        self.measure.write({"aggregate": "sum", "field_id": self.env["ir.model.fields"]._get("res.partner", "color").id})
        count = self.measure.copy({"name": "Count", "aggregate": "count", "field_id": False, "sequence": 20})
        ratio = self.measure.copy({"name": "Ratio", "aggregate": "formula", "field_id": False,
                                   "formula": "a / b", "sequence": 1})
        self.measure.sequence = 10
        self.item.measure_ids = [(6, 0, (ratio | self.measure | count).ids)]
        self.assertEqual(self.item._headline_value(), 40)

    def test_alert_uses_full_scope_average(self):
        alert = self.env["eh.board.alert"].create({
            "name": "Average alert", "dashboard_id": self.board.id, "item_id": self.item.id,
            "threshold": 50, "operator": "gt", "user_id": self.env.uid,
        })
        self.assertEqual(alert._current_value(), 40)
        alert._evaluate()
        self.assertEqual(alert.state, "armed")

    def test_invalid_context_does_not_fall_back_to_unfiltered(self):
        for options in ([1], {"date_range": {"start": "bad", "end": "2026-01-01"}},
                        {"filters": [{"field": "id", "values": "all"}]},
                        {"drill_paths": {"99999999": []}}):
            with self.assertRaises(UserError):
                self.board.get_export_data(options)
        with self.assertRaises(AccessError):
            self.board.get_export_data({"company_ids": [99999999]})

    def test_relative_digest_dates_resolve_at_generation(self):
        self.board.save_digest_view(self.au_options, "this_month")
        self.assertNotIn("date_range", self.board.digest_view["options"])
        selected = self.board._scheduled_analysis_options()
        self.assertEqual(selected["date_range"]["start"], fields.Date.context_today(self.board).replace(day=1).isoformat())
        self.assertEqual(selected["filters"], self.au_options["filters"])

    def test_report_html_uses_export_context(self):
        self.item.item_type = "kpi"
        report = self.env.ref("eh_board.action_report_eh_board_dashboard").with_context(eh_board_options=self.au_options)
        html, _kind = report._render_qweb_html(report.report_name, self.board.ids)
        self.assertIn(b">15<", html)
        self.assertIn(b"Country", html)

    def test_csv_formula_guards_preserve_numeric_negative(self):
        self.assertEqual(EhBoardController._csv_value("=SUM(A1:A2)"), "'=SUM(A1:A2)")
        self.assertEqual(EhBoardController._csv_value(-12), -12)
        self.assertEqual(EhBoardController._csv_value("Safe"), "Safe")

    def test_digest_resolves_each_recipient_company_and_skips_no_access(self):
        company_a = self.env.company
        company_b = self.env["res.company"].create({"name": "Digest second company"})
        self.partners[:2].company_id = company_a
        self.partners[2:].company_id = company_b
        self.item.item_type = "kpi"
        User = self.env["res.users"].with_context(no_reset_password=True)
        groups_field = "group_ids" if "group_ids" in User._fields else "groups_id"
        users = User.browse()
        for suffix, company in (("a", company_a), ("b", company_b)):
            users |= User.create({"name": "Scoped recipient " + suffix,
                "login": "scoped_recipient_" + suffix, "email": suffix + "@example.com",
                "company_id": company.id, "company_ids": [(6, 0, company.ids)],
                groups_field: [(6, 0, [self.env.ref("base.group_user").id,
                                      self.env.ref("eh_board.group_board_viewer").id])]})
        outsider = User.create({"name": "No dashboard access", "login": "scoped_outsider",
            "email": "outsider@example.com", "company_id": company_a.id,
            "company_ids": [(6, 0, company_a.ids)]})
        self.board.write({"company_ids": [(6, 0, (company_a | company_b).ids)],
            "shared_user_ids": [(6, 0, users.ids)],
            "digest_user_ids": [(6, 0, (users | outsider).ids)]})
        seen = {}
        for recipient in users:
            recipient_board = self.board.with_user(recipient).with_context(allowed_company_ids=recipient.company_ids.ids)
            selected = recipient_board._scheduled_analysis_options()
            recipient_board._analysis_scope(selected)
            recipient_board.get_export_data(selected)

        def render(report, report_ref, res_ids=None, data=None):
            board = report.env["eh.board.dashboard"].browse(res_ids)
            opts = report.env.context["eh_board_options"]
            seen[report.env.uid] = board.get_export_data(opts)["items"][0]["value"]
            return b"%PDF-1.4 test", "pdf"

        with patch.object(type(self.env["ir.actions.report"]), "_render_qweb_pdf", render), \
                patch.object(type(self.env["mail.mail"]), "send"):
            self.board.send_digest()
        self.assertEqual(seen, {users[0].id: 15, users[1].id: 90})

    def test_metadata_access_never_grants_restricted_measure_access(self):
        User = self.env["res.users"].with_context(no_reset_password=True)
        groups_field = "group_ids" if "group_ids" in User._fields else "groups_id"
        viewer = User.create({"name": "Field-limited viewer", "login": "field_limited_viewer",
            groups_field: [(6, 0, [self.env.ref("base.group_user").id,
                                  self.env.ref("eh_board.group_board_viewer").id])]})
        self.board.shared_user_ids = [(6, 0, viewer.ids)]
        self.item.item_type = "kpi"
        board = self.board.with_user(viewer)
        self.assertEqual(board.get_export_data()["items"][0]["value"], 40)
        with patch.object(self.env["res.partner"]._fields["color"], "groups", "base.group_system"):
            denied = board.get_export_data()["items"][0]
        self.assertTrue(denied.get("error"), "Reading configured field metadata must not expose restricted measure data")
