# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Regression tests for the hardening pass.

Each test pins a specific defect that was fixed, so a future change that
re-introduces it fails loudly here. Grouped by subsystem.
"""
from odoo.tests import TransactionCase, tagged
from odoo.exceptions import ValidationError

from ..lib import tabular, aggregation
from ..lib.formula import compile_formula, FormulaError
from ..datasources.sql import SqlDataSource


@tagged("post_install", "-at_install", "eh_board")
class TestBoardFixes(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Dashboard = cls.env["eh.board.dashboard"]
        cls.Datasource = cls.env["eh.board.datasource"]
        cls.Measure = cls.env["eh.board.measure"]
        cls.Item = cls.env["eh.board.item"]
        cls.partner_model = cls.env["ir.model"]._get("res.partner")
        cls.is_company_field = cls.env["ir.model.fields"]._get("res.partner", "is_company")
        cls.country_field = cls.env["ir.model.fields"]._get("res.partner", "country_id")
        cls.au = cls.env.ref("base.au", raise_if_not_found=False)
        cls.us = cls.env.ref("base.us", raise_if_not_found=False)
        Partner = cls.env["res.partner"]
        # partner_latitude is a stored Float on base res.partner; use it as the
        # amount so the average subtotal is checkable (100, 300, 200 -> avg 200).
        cls.partners = Partner.create([
            {"name": "AU-One", "company_type": "company",
             "country_id": cls.au.id if cls.au else False, "partner_latitude": 100.0},
            {"name": "AU-Two", "company_type": "company",
             "country_id": cls.au.id if cls.au else False, "partner_latitude": 300.0},
            {"name": "US-One", "company_type": "company",
             "country_id": cls.us.id if cls.us else False, "partner_latitude": 200.0},
        ])
        cls.source = cls.Datasource.create({
            "name": "Partners", "provider_type": "orm",
            "model_id": cls.partner_model.id,
            "domain": "[('id', 'in', %s)]" % cls.partners.ids,
        })

    # ------------------------------------------------------------------ formula
    def test_formula_unknown_variable_rejected_at_save(self):
        """A misspelled / out-of-range variable is caught at save, not silently
        evaluated to 0.0 at render."""
        with self.assertRaises(ValidationError):
            self.Measure.create({
                "name": "Bad", "datasource_id": self.source.id,
                "aggregate": "formula", "formula": "revenue / 2"})

    def test_formula_pow_of_large_money_not_zeroed(self):
        """revenue ** 0.5 (RMS / geometric mean) over a large value must not be
        silently zeroed; only a genuine blow-up exponent is capped."""
        fn = compile_formula("a ** 0.5")
        self.assertAlmostEqual(fn({"a": 4_000_000.0}), 2000.0, places=3)
        # A blow-up exponent is still capped to 0 (no CPU/RAM bomb).
        self.assertEqual(compile_formula("a ** b")({"a": 9, "b": 9 ** 9}), 0.0)

    def test_formula_non_finite_collapses_to_zero(self):
        """inf / nan would serialise as bare tokens and break the JSON-RPC
        response; they collapse to 0.0."""
        self.assertEqual(compile_formula("a / b")({"a": 1, "b": 0}), 0.0)
        self.assertEqual(compile_formula("a * b")({"a": 1e308, "b": 1e308}), 0.0)

    # -------------------------------------------------------------------- SQL
    def _sql_error(self, query):
        return SqlDataSource()._validate_sql(query)

    def test_sql_rejects_unicode_escape_identifier(self):
        self.assertTrue(self._sql_error('SELECT * FROM u&"\\0072es_users"'))

    def test_sql_rejects_catalog_views(self):
        for q in ("SELECT query FROM pg_stat_activity",
                  "SELECT rolname FROM pg_roles",
                  "SELECT name FROM pg_settings"):
            self.assertTrue(self._sql_error(q), q)

    def test_sql_rejects_rollback_surviving_functions(self):
        for q in ("SELECT nextval('some_seq')",
                  "SELECT setval('s', 1)",
                  "SELECT pg_advisory_lock(1)"):
            self.assertTrue(self._sql_error(q), q)

    def test_sql_comment_does_not_bypass_denylist(self):
        """A forbidden keyword or a hidden ';' is still caught with comments
        present (the scan runs on comment-stripped text)."""
        self.assertTrue(self._sql_error("SELECT * FROM t /* hi */ WHERE pg_sleep(9) > 0"))
        self.assertTrue(self._sql_error("SELECT 1 /* c */ ; DELETE FROM t"))

    def test_sql_safe_query_still_allowed(self):
        self.assertIsNone(self._sql_error("SELECT name, count(*) FROM x GROUP BY name"))

    def test_sql_duplicate_measure_columns_do_not_collapse(self):
        """Two aggregate columns that share a name (unaliased sum, sum) stay
        distinct instead of the first vanishing."""
        src = self.Datasource.sudo().create({
            "name": "sqltest", "provider_type": "sql",
            "sql_query": "SELECT 'x' AS k, 1 AS sum, 2 AS sum"})
        res = SqlDataSource().aggregate(src.sudo(), {"limit": 10})
        # No error, and two measure columns survived.
        self.assertFalse(res.get("error"), res.get("error"))
        self.assertEqual(len(res["measures"]), 2)
        self.assertEqual(len(set(res["measures"])), 2, "measure names are distinct")

    # ------------------------------------------------------------------ pivot
    def test_pivot_average_subtotal_is_exact_not_cell_sum(self):
        """A non-additive (average) measure's grand total is the TRUE average of
        the population, never the meaningless sum of per-cell averages."""
        avg = self.Measure.create({
            "name": "AvgLat", "datasource_id": self.source.id,
            "aggregate": "avg",
            "field_id": self.env["ir.model.fields"]._get("res.partner", "partner_latitude").id})
        item = self.Item.create({
            "dashboard_id": self.Dashboard.create({"name": "d"}).id,
            "item_type": "pivot", "title": "pv", "datasource_id": self.source.id,
            "measure_ids": [(6, 0, avg.ids)],
            "primary_dimension_id": self.country_field.id,
            "secondary_dimension_id": self.is_company_field.id})
        p = item.get_payload()
        self.assertIsNone(p.get("error"))
        mk = p["measure_keys"][0]
        # True average of 100, 300, 200 = 200 - NOT a sum of per-cell averages.
        self.assertAlmostEqual(p["grand_total"][mk], 200.0, places=3)

    # ------------------------------------------------------------------ filter
    def test_boolean_filter_offers_false(self):
        flt = self.env["eh.board.filter"].create({
            "dashboard_id": self.Dashboard.create({"name": "d"}).id,
            "name": "Is company", "filter_type": "field",
            "field_id": self.is_company_field.id})
        values = [o["value"] for o in flt.get_options()]
        self.assertIn(True, values)
        self.assertIn(False, values, "the False value must be filterable")

    # ----------------------------------------------------------------- tabular
    def test_date_column_format_is_consistent_for_us_dates(self):
        """A US MM/DD/YYYY column with a disambiguating day > 12 parses the whole
        column as month-first, so Feb 1 does not silently become Jan 2."""
        parsed = tabular.parse_csv(
            b"d,v\n02/01/2026,1\n02/28/2026,2\n03/15/2026,3\n")
        rows = parsed["rows"]
        # 02/01/2026 must be February (month 02), not 1 Feb read as day-first.
        self.assertTrue(rows[0]["d"].startswith("2026-02-01"))

    def test_leading_zero_code_stays_text(self):
        """Zip / SKU codes with a leading zero are text, not a number that drops
        the zero and collapses distinct codes."""
        parsed = tabular.parse_csv(b"zip,v\n00501,1\n02139,2\n")
        col = {c["name"]: c for c in parsed["columns"]}["zip"]
        self.assertEqual(col["dtype"], "text")
        self.assertEqual(parsed["rows"][0]["zip"], "00501")

    # -------------------------------------------------------------- aggregation
    def test_fill_time_gaps_preserves_null_date_group(self):
        rows = [
            {"keys": ["2025-01-01"], "labels": ["Jan 2025"], "values": {"m": 5.0}},
            {"keys": ["2025-03-01"], "labels": ["Mar 2025"], "values": {"m": 7.0}},
            {"keys": [None], "labels": ["Undefined"], "values": {"m": 9.0}},
        ]
        out = aggregation.fill_time_gaps(rows, "month")
        total = sum(r["values"]["m"] for r in out)
        self.assertEqual(total, 21.0, "the null-date group is not dropped")
        self.assertTrue(any(r["labels"][0] == "Undefined" for r in out))

    def test_date_sort_emits_granular_order_term(self):
        """Field-sorting a grouped DATE dimension emits 'field:granularity dir',
        matching the groupby - not a bare field that _read_group rejects on 17+."""
        date_field = self.env["ir.model.fields"]._get("res.partner", "create_date")
        item = self.Item.create({
            "dashboard_id": self.Dashboard.create({"name": "d"}).id,
            "item_type": "bar", "title": "b", "datasource_id": self.source.id,
            "primary_dimension_id": date_field.id,
            "date_granularity": "month",
            "sort_mode": "field", "sort_field_id": date_field.id, "sort_order": "desc"})
        clause = item._order_clause()
        self.assertEqual(clause, "create_date:month desc")

    # ------------------------------------------------------------- multi-company
    def test_child_models_have_global_company_rule(self):
        """Every child model that stores live figures carries a GLOBAL
        multi-company record rule, so KPI history/config cannot leak across
        companies to a user who cannot see the parent dashboard."""
        Rule = self.env["ir.rule"]
        for model in ("eh.board.item", "eh.board.snapshot", "eh.board.alert",
                      "eh.board.filter", "eh.board.layout.version", "eh.board.drill"):
            rules = Rule.search([("model_id.model", "=", model), ("global", "=", True)])
            self.assertTrue(
                any("company_id" in (r.domain_force or "") for r in rules),
                "%s needs a global company record rule" % model)
