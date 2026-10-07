"""Business fixtures verify meaning, access, dynamic dates and preview rollback."""
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, tagged

from ..lib.business_metrics import metric_definition, metric_domain


@tagged("post_install", "-at_install", "eh_board")
class TestBoardBusiness(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Dash = cls.env["eh.board.dashboard"]
        cls.board = cls.Dash.create({"name": "Business fixture"})
        cls.partner = cls.env["res.partner"].create({"name": "Business fixture customer"})

    def test_versioned_definitions_are_caller_owned(self):
        definition = metric_definition("sales.confirmed_untaxed.v1")
        definition["domain"].append(("state", "=", "draft"))
        self.assertNotIn(("state", "=", "draft"), metric_definition("sales.confirmed_untaxed.v1")["domain"])
        self.assertIsNone(metric_definition("sales.unknown.v9"))

    def test_current_balance_definitions_explicitly_include_refunds(self):
        domain = metric_domain("receivables.open_balance.v1", 7, 3)
        self.assertIn(("state", "=", "posted"), domain)
        self.assertIn(("move_type", "in", ["out_invoice", "out_refund"]), domain)
        self.assertIn(("company_id", "=", 7), domain)
        self.assertFalse(metric_definition("receivables.open_balance.v1")["date_field"])
        first = metric_domain("receivables.overdue_balance.v1", 7, 3, today="2026-01-01")
        second = metric_domain("receivables.overdue_balance.v1", 7, 3, today="2026-01-02")
        self.assertIn(("invoice_date_due", "<", "2026-01-01"), first)
        self.assertIn(("invoice_date_due", "<", "2026-01-02"), second)

    def test_viewer_cannot_preview_create_or_enumerate_metric_metadata(self):
        group_field = "group_ids" if "group_ids" in self.env["res.users"]._fields else "groups_id"
        viewer = self.env["res.users"].create({
            "name": "Business pack viewer", "login": "business_pack_viewer",
            group_field: [(6, 0, [self.env.ref("eh_board.group_board_viewer").id])],
        })
        for method, args in (("get_business_packs", []), ("preview_business_pack", ["sales.v1"]),
                             ("create_business_pack", ["sales.v1"]), ("_metric_authoring_catalog", [])):
            with self.assertRaises(AccessError):
                getattr(self.Dash.with_user(viewer), method)(*args)

    def test_seed_is_idempotent_and_preserves_existing_template_and_board(self):
        Template = self.env["eh.board.template"]
        saved = Template.create({"name": "My own template", "payload": {"items": []}})
        Template._seed_predefined()
        first = Template.search([("business_pack_key", "!=", False)])
        self.assertEqual(len(first), 3)
        existing_payload = first[:1].payload
        Template._seed_predefined()
        self.assertEqual(Template.search([("business_pack_key", "!=", False)]).ids, first.ids)
        self.assertEqual(first[:1].payload, existing_payload)
        self.assertEqual(saved.name, "My own template")
        self.assertEqual(self.board.name, "Business fixture")

    def _sale_orders(self):
        if "sale.order" not in self.env:
            self.skipTest("Sales must be installed for native business fixtures.")
        Product = self.env["product.product"]
        product = Product.create({"name": "Business fixture service", "type": "service", "list_price": 100})
        Line = self.env["sale.order.line"]
        tax_field = "tax_ids" if "tax_ids" in Line._fields else "tax_id"
        orders = self.env["sale.order"]
        for state, amount in (("sale", 100), ("sale", 300), ("draft", 999), ("cancel", 888)):
            orders |= orders.create({
                "partner_id": self.partner.id, "company_id": self.env.company.id,
                "currency_id": self.env.company.currency_id.id,
                "date_order": fields.Datetime.now(), "state": state,
                "order_line": [(0, 0, {"product_id": product.id, "name": product.name,
                                       "product_uom_qty": 1, "price_unit": amount, tax_field: [(5, 0, 0)]})],
            })
        return orders

    def test_sales_values_exclude_drafts_and_cancelled_orders(self):
        orders = self._sale_orders()
        expected = {"sales.confirmed_untaxed.v1": 400, "sales.average_order.v1": 200,
                    "sales.confirmed_orders.v1": 2}
        for metric_id, amount in expected.items():
            item = self.board._create_business_metric(metric_id)
            payload = item.get_payload({"domain": [("id", "in", orders.ids)]})
            self.assertFalse(payload.get("error"), payload)
            self.assertAlmostEqual(payload["value"], amount)
            self.assertFalse(item.measure_ids.target_value)
            self.assertIn("company", item.description.lower())

    def test_sales_foreign_currency_orders_are_explicitly_excluded(self):
        orders = self._sale_orders()
        currency = self.env["res.currency"].search([("id", "!=", self.env.company.currency_id.id)], limit=1)
        if not currency:
            self.skipTest("A second currency is required for the exclusion fixture.")
        currency.active = True
        pricelist = self.env["product.pricelist"].create({"name": "Business foreign currency", "currency_id": currency.id})
        orders[:1].write({"pricelist_id": pricelist.id, "currency_id": currency.id})
        item = self.board._create_business_metric("sales.confirmed_untaxed.v1")
        self.assertAlmostEqual(item.get_payload({"domain": [("id", "in", orders.ids)]})["value"], 300)
        self.assertIn("Foreign-currency orders are excluded", item.description)

    def test_metric_create_rejects_unknown_query_overrides_and_historical_current_balance(self):
        self._sale_orders()
        with self.assertRaises(ValidationError):
            self.board._create_business_metric("sales.confirmed_untaxed.v1", {"domain": "[]"})
        with self.assertRaises(ValidationError):
            self.board._create_business_metric("sales.confirmed_untaxed.v1", {"dimension": "access_token", "item_type": "bar"})
        if "account.move" in self.env:
            with self.assertRaises(ValidationError):
                self.board._create_business_metric("receivables.open_balance.v1", {"default_date_filter": "last_month"})

    def test_preview_leaves_no_dashboard_items_sources_or_measures(self):
        self._sale_orders()
        models = ["eh.board.dashboard", "eh.board.item", "eh.board.datasource", "eh.board.measure", "eh.board.layout.version"]
        before = {name: self.env[name].search_count([]) for name in models}
        preview = self.Dash.preview_business_pack("sales.v1")
        self.assertEqual(len(preview["items"]), 6)
        self.assertTrue(all(not entry["payload"].get("error") for entry in preview["items"]), preview)
        self.assertEqual({name: self.env[name].search_count([]) for name in models}, before)
        action = self.Dash.create_business_pack("sales.v1")
        dash = self.Dash.browse(action["params"]["dashboard_id"])
        self.assertEqual(dash.state, "draft")
        self.assertEqual(dash.company_ids, self.env.company)
        self.assertFalse(dash.shared_user_ids)
        self.assertEqual(len(dash.item_ids), 6)

    def test_unreadable_models_are_not_offered(self):
        self._sale_orders()
        group_field = "group_ids" if "group_ids" in self.env["res.users"]._fields else "groups_id"
        builder = self.env["res.users"].create({
            "name": "Business builder without sales", "login": "business_builder_no_sales",
            group_field: [(6, 0, [self.env.ref("eh_board.group_board_builder").id])],
        })
        offered = self.Dash.with_user(builder)._metric_authoring_catalog()
        self.assertFalse(any(m["model"] == "sale.order" for m in offered))

    def test_company_scope_is_fixed_and_cannot_leak_when_company_unselected(self):
        self._sale_orders()
        item = self.board._create_business_metric("sales.confirmed_untaxed.v1")
        other = self.env["res.company"].create({"name": "Other metric company"})
        self.assertIn(("company_id", "=", self.env.company.id), item._effective_domain({}))
        with self.assertRaises(AccessError):
            item.with_context(allowed_company_ids=other.ids)._business_scope_domain()

    def test_provenance_survives_identical_editor_write_but_rejects_semantic_changes(self):
        self._sale_orders()
        metric_id = "sales.confirmed_untaxed.v1"
        item = self.board._create_business_metric(metric_id)
        vals = self.board._builder_item_vals(self.board._metric_authoring_spec(metric_id))
        item.write(vals)
        self.assertEqual(item.business_metric_id, metric_id)
        for record, change in ((item, {"domain": "[]"}),
                               (item.measure_ids, {"aggregate": "avg"}),
                               (item.datasource_id, {"domain": "[('state', '=', 'draft')]"})):
            with self.assertRaises(ValidationError):
                record.write(change)
        self.assertEqual(item.measure_ids.aggregate, "sum")
        self.assertEqual(item.business_metric_id, metric_id)
        self.board.detach_business_metric(item.id)
        self.assertFalse(item.business_metric_id)
        self.assertFalse(item.business_company_id)
        self.assertFalse(item.description)
        item.measure_ids.aggregate = "avg"
        self.assertEqual(item.measure_ids.aggregate, "avg")

    def test_direct_create_cannot_label_different_measure_as_business_definition(self):
        self._sale_orders()
        vals = self.board._metric_authoring_spec("sales.confirmed_untaxed.v1")
        vals["measure"]["verb"] = "avg"
        item_vals = self.board._builder_item_vals(vals)
        item_vals.update({"business_metric_id": "sales.confirmed_untaxed.v1", "business_company_id": self.env.company.id})
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.env["eh.board.item"].create(item_vals)

    def test_definition_round_trip_retains_version_and_rebinds_company(self):
        self._sale_orders()
        item = self.board._create_business_metric("sales.confirmed_untaxed.v1")
        payload = self.board._definition_payload()
        self.assertEqual(payload["items"][0]["business_metric_id"], item.business_metric_id)
        self.assertNotIn("domain", payload["items"][0])
        other = self.env["res.company"].create({"name": "Imported metric company", "currency_id": self.env.company.currency_id.id})
        template = self.env["eh.board.template"].create({"name": "Metric backup", "payload": payload})
        copied = template.with_company(other).create_from_template()
        self.assertEqual(copied.item_ids.business_metric_id, item.business_metric_id)
        self.assertEqual(copied.item_ids.business_company_id, other)
        self.assertIn(("company_id", "=", other.id), copied.item_ids._effective_domain({}))

    def test_unknown_saved_metric_never_leaves_partial_import(self):
        before = self.Dash.search_count([])
        template = self.env["eh.board.template"].create({"name": "Bad version", "payload": {"items": [
            {"type": "richtext", "content": "This item must roll back too"},
            {"business_metric_id": "sales.unknown.v99", "type": "kpi"},
        ]}})
        from odoo.exceptions import UserError
        with self.assertRaises(UserError):
            template.create_from_template()
        self.assertEqual(self.Dash.search_count([]), before)

    def test_warehouse_late_scope_moves_with_clock_and_current_backlog_ignores_period(self):
        if "stock.picking" not in self.env:
            self.skipTest("Inventory must be installed for native business fixtures.")
        item = self.board._create_business_metric("warehouse.late_transfers.v1")
        with patch.object(fields.Datetime, "now", return_value=fields.Datetime.to_datetime("2026-01-02 12:00:00")):
            domain = item._effective_domain({"date_range": {"start": "2000-01-01", "end": "2000-01-31"}})
        self.assertIn(("scheduled_date", "<", "2026-01-02 12:00:00"), domain)
        self.assertIn(("state", "not in", ["done", "cancel"]), domain)
        self.assertFalse(any(isinstance(leaf, (tuple, list)) and len(leaf) == 3 and leaf[0] == "create_date" for leaf in domain))

    def test_receivable_native_signed_residuals_and_partial_payment(self):
        if "account.move" not in self.env:
            self.skipTest("Accounting must be installed for native business fixtures.")
        Account = self.env["account.account"]
        company_vals = {"company_ids": [(6, 0, self.env.company.ids)]} if "company_ids" in Account._fields else {"company_id": self.env.company.id}
        receivable = Account.create({"name": "Board fixture receivable", "code": "EHBR01", "account_type": "asset_receivable", "reconcile": True, **company_vals})
        revenue = Account.create({"name": "Board fixture income", "code": "EHBI01", "account_type": "income", **company_vals})
        journal = self.env["account.journal"].create({"name": "Board fixture sales", "code": "EHBQ", "type": "sale", "company_id": self.env.company.id, "default_account_id": revenue.id})
        self.partner.with_company(self.env.company).property_account_receivable_id = receivable
        today = fields.Date.context_today(self.board)
        due = today - timedelta(days=2)
        moves = self.env["account.move"]
        invoice = None
        for move_type, amount, posted in (("out_invoice", 100, True), ("out_refund", 30, True), ("out_invoice", 999, False)):
            move = moves.create({
                "move_type": move_type, "partner_id": self.partner.id, "journal_id": journal.id,
                "company_id": self.env.company.id, "invoice_date": due, "invoice_date_due": due,
                "invoice_line_ids": [(0, 0, {"name": "Board fixture", "account_id": revenue.id,
                                            "quantity": 1, "price_unit": amount, "tax_ids": [(5, 0, 0)]})],
            })
            if posted:
                move.action_post()
            if move_type == "out_invoice" and posted:
                invoice = move
            moves |= move
        item = self.board._create_business_metric("receivables.open_balance.v1")
        scope = {"domain": [("id", "in", moves.ids)]}
        payload = item.get_payload({**scope, "date_range": {"start": "2000-01-01", "end": "2000-01-31"}})
        self.assertFalse(payload.get("error"), payload)
        self.assertAlmostEqual(payload["value"], 70)
        general = self.env["account.journal"].create({"name": "Board fixture adjustment", "code": "EHBG", "type": "general", "company_id": self.env.company.id})
        payment = self.env["account.move"].create({"journal_id": general.id, "date": today,
            "line_ids": [(0, 0, {"name": "Fixture payment", "account_id": revenue.id, "debit": 40, "credit": 0}),
                         (0, 0, {"name": "Fixture payment", "account_id": receivable.id, "partner_id": self.partner.id, "debit": 0, "credit": 40})]})
        payment.action_post()
        (invoice.line_ids + payment.line_ids).filtered(lambda line: line.account_id == receivable).reconcile()
        self.assertAlmostEqual(item.get_payload(scope)["value"], 30)
        overdue = self.board._create_business_metric("receivables.overdue_balance.v1")
        self.assertAlmostEqual(overdue.get_payload(scope)["value"], 30)
