# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Regression tests for the SECOND hardening pass (defects the first fixes
introduced or left). Each pins a specific regression so it cannot come back.
"""
import base64
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo.tests import TransactionCase, tagged
from odoo.exceptions import UserError, ValidationError
from odoo import fields

from ..lib import tabular, aggregation
from ..datasources.sql import SqlDataSource


@tagged("post_install", "-at_install", "eh_board")
class TestBoardFixes2(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Dashboard = cls.env["eh.board.dashboard"]
        cls.Datasource = cls.env["eh.board.datasource"]
        cls.Measure = cls.env["eh.board.measure"]
        cls.Item = cls.env["eh.board.item"]
        cls.partner_model = cls.env["ir.model"]._get("res.partner")
        cls.country_field = cls.env["ir.model.fields"]._get("res.partner", "country_id")
        cls.au = cls.env.ref("base.au", raise_if_not_found=False)
        cls.us = cls.env.ref("base.us", raise_if_not_found=False)
        cls.de = cls.env.ref("base.de", raise_if_not_found=False)
        Partner = cls.env["res.partner"]
        # A clear count distribution: US=5, AU=3, DE=1 (+ any pre-existing).
        recs = []
        for c, n in ((cls.us, 5), (cls.au, 3), (cls.de, 1)):
            for i in range(n):
                recs.append({"name": "P-%s-%d" % (c.code if c else "x", i),
                             "country_id": c.id if c else False})
        cls.partners = Partner.create(recs)
        cls.source = cls.Datasource.create({
            "name": "Partners", "provider_type": "orm",
            "model_id": cls.partner_model.id,
            "domain": "[('id', 'in', %s)]" % cls.partners.ids})
        cls.count = cls.Measure.create({
            "name": "Records", "datasource_id": cls.source.id, "aggregate": "count"})

    # ---- SQL sandbox: the comment-strip bypass is closed --------------------
    def _err(self, q):
        return SqlDataSource()._validate_sql(q)

    def test_sql_comments_rejected(self):
        """SQL comments are refused outright, so a `--` / `/* */` inside a string
        literal can no longer desync the scanned text from what executes."""
        self.assertTrue(self._err("SELECT '/*' AS a, pg_read_file('/x') AS b, '*/' AS c"))
        self.assertTrue(self._err("SELECT (SELECT 1 WHERE 'q'='--') AS a, "
                                  "(SELECT 1 FROM res_users) AS b"))
        self.assertTrue(self._err("SELECT 1 -- comment\nFROM t"))

    def test_sql_raw_scan_still_blocks_sensitive(self):
        self.assertTrue(self._err("SELECT login FROM res_users"))
        self.assertTrue(self._err("SELECT nextval('s')"))
        self.assertTrue(self._err('SELECT * FROM u&"\\0072es_users"'))
        self.assertIsNone(self._err("SELECT name, count(*) FROM x GROUP BY name"))

    def test_builder_creates_safe_sql_source(self):
        """Safe SQL's canvas RPC must resolve the registered provider."""
        dashboard = self.Dashboard.create({"name": "SQL source board"})
        query = "SELECT 'Accepted' AS label, 1.5 AS value"
        meta = dashboard.create_builder_source({
            "provider": "sql", "name": "Accepted SQL", "query": query,
        })
        source = self.Datasource.browse(meta["id"])
        self.assertEqual(source.dashboard_id, dashboard)
        self.assertEqual(source.provider_type, "sql")
        self.assertEqual(source.sql_query, query)

    def test_builder_edits_safe_sql_source_in_place(self):
        """Editing from Source Studio must preserve identity, expose current
        values only through the guarded edit RPC, and never add a duplicate."""
        dashboard = self.Dashboard.create({"name": "Editable SQL board"})
        original = dashboard.create_builder_source({
            "provider": "sql", "name": "Utilisation", "query": "SELECT 1 AS value",
        })
        before = self.Datasource.search_count([
            ("dashboard_id", "=", dashboard.id), ("provider_type", "=", "sql"),
        ])
        editable = dashboard.get_builder_source(original["id"])
        self.assertEqual(editable["name"], "Utilisation")
        self.assertEqual(editable["query"], "SELECT 1 AS value")
        self.assertTrue(editable["editable"])

        updated = dashboard.create_builder_source({
            "source_id": original["id"],
            "provider": "sql",
            "name": "Utilisation by plot",
            "query": "SELECT 2 AS value",
        })
        source = self.Datasource.browse(original["id"])
        self.assertEqual(updated["id"], original["id"])
        self.assertEqual(source.name, "Utilisation by plot")
        self.assertEqual(source.sql_query, "SELECT 2 AS value")
        self.assertEqual(self.Datasource.search_count([
            ("dashboard_id", "=", dashboard.id), ("provider_type", "=", "sql"),
        ]), before)

    def test_builder_file_source_can_be_renamed_without_reupload(self):
        dashboard = self.Dashboard.create({"name": "Editable file board"})
        original = dashboard.create_builder_source({
            "provider": "file",
            "name": "Targets",
            "filename": "targets.csv",
            "data": base64.b64encode(b"label,value\nA,10\n").decode(),
        })
        source = self.Datasource.browse(original["id"])
        old_data = source.file_data
        updated = dashboard.create_builder_source({
            "source_id": source.id, "provider": "file", "name": "FY targets",
        })
        self.assertEqual(updated["id"], source.id)
        self.assertEqual(source.name, "FY targets")
        self.assertEqual(source.file_data, old_data)
        self.assertEqual(source.row_count, 1)

    def test_ai_settings_view_does_not_replace_general_settings(self):
        """Standalone Dashboard AI form must never become global Settings."""
        ai_view = self.env.ref("eh_board.view_eh_board_ai_settings_form")
        base_view = self.env.ref("base.res_config_settings_view_form")
        action = self.env.ref("eh_board.action_eh_board_ai_settings")
        default_view_id = self.env["ir.ui.view"].default_view(
            "res.config.settings", "form")
        self.assertEqual(default_view_id, base_view.id)
        self.assertEqual(action.view_id, ai_view)
        self.assertGreater(ai_view.priority, base_view.priority)

        settings_view = self.env.ref("eh_board.view_eh_board_settings")
        self.assertEqual(settings_view.inherit_id, base_view)
        self.assertIn("Dashboard Builder", settings_view.arch_db)

    # ---- exact top-N is correct on this Odoo version -----------------------
    def test_value_sorted_top_n_is_the_true_top_n(self):
        """value_desc + a record limit returns the TRUE top groups, whether the
        DB-order push is used (Odoo 17+) or the safe read+sort path (Odoo 16)."""
        spec = {"model": "res.partner", "domain": [("id", "in", self.partners.ids)],
                "dimensions": [{"field": "country_id", "granularity": None}],
                "measures": [{"key": "m", "field": None, "verb": "count", "multiplier": 1.0}],
                "measure_keys": ["m"], "sort": "value_desc", "limit": 2,
                "read_cap": None, "group_others": False, "cumulative": False,
                "fill_gaps": False}
        from ..datasources.orm import OrmDataSource
        res = OrmDataSource().aggregate(self.source, spec)
        counts = [round(r["values"]["m"]) for r in res["rows"]]
        # top-2 by count must be US(5), AU(3) - never DE(1) or an arbitrary slice.
        self.assertEqual(counts, [5, 3])

    # ---- pivot field-sort margins do not blank -----------------------------
    def test_pivot_field_sort_margins_reconcile(self):
        """A pivot sorted by a specific field must still show exact margins; the
        dedicated margin reads must not inherit the field-sort order (which would
        raise on the reduced group-by and blank the totals)."""
        item = self.Item.create({
            "dashboard_id": self.Dashboard.create({"name": "d"}).id,
            "item_type": "pivot", "title": "pv", "datasource_id": self.source.id,
            "measure_ids": [(6, 0, self.count.ids)],
            "primary_dimension_id": self.country_field.id,
            "sort_mode": "field", "sort_field_id": self.country_field.id,
            "sort_order": "desc"})
        p = item.get_payload()
        self.assertIsNone(p.get("error"))
        mk = p["measure_keys"][0]
        # grand total = all 9 records, and row totals sum to it (not 0).
        self.assertEqual(round(p["grand_total"][mk]), 9)
        rowsum = sum(round(rt.get(mk, 0)) for rt in p["row_totals"].values())
        self.assertEqual(rowsum, 9)

    # ---- an unsaved dashboard cannot create an item with a null dashboard_id --
    def test_add_widget_on_unsaved_board_raises_clean(self):
        """Creating a widget against a non-persisted (NewId) dashboard raises a
        clear UserError instead of a raw not-null constraint violation."""
        newD = self.Dashboard.browse([None])
        vals = {"item_type": "tile", "title": "X",
                "model_id": self.partner_model.id,
                "measures": [{"verb": "count", "field": None}]}
        with self.assertRaises(UserError):
            newD._create_item_from_builder(dict(vals))

    def test_dashboard_id_is_authoritative(self):
        """A dashboard_id in the client vals can never override the real board."""
        D = self.Dashboard.create({"name": "d"})
        item = D._create_item_from_builder({
            "item_type": "tile", "title": "X", "dashboard_id": False,
            "model_id": self.partner_model.id,
            "measures": [{"verb": "count", "field": None}]})
        self.assertEqual(item.dashboard_id.id, D.id)

    def test_builder_model_domain_supports_technical_name_search(self):
        """Native ir.model autocomplete finds a model by technical name while
        staying inside builder's concrete-model whitelist."""
        D = self.Dashboard.create({"name": "d"})
        allowed_ids = [model["id"] for model in D.get_builder_meta()["models"]]
        # Positional call works across 16-18 (``args``) and 19 (``domain``).
        found = self.env["ir.model"].name_search(
            "res.partner", [("id", "in", allowed_ids)], "ilike", 20)
        self.assertIn(self.partner_model.id, [model_id for model_id, _name in found])

    # ---- tabular UTF-16 BOM is consumed, not left on the header -------------
    def test_utf16_bom_stripped_from_header(self):
        raw = "name,value\nAlice,1\nBob,2\n".encode("utf-16")  # includes BOM
        parsed = tabular.parse_csv(raw)
        names = [c["name"] for c in parsed["columns"]]
        # first column key is "name", not "﻿name"
        self.assertIn("name", names)
        self.assertFalse(any("﻿" in n for n in names))

    # ---- source studio / fixed-source regressions -------------------------
    def test_source_studio_file_builds_raw_record_list(self):
        dashboard = self.Dashboard.create({"name": "File board"})
        encoded = base64.b64encode(
            b"name,amount,won\nAlpha,10,true\nBeta,25,false\n").decode()
        meta = dashboard.create_builder_source({
            "provider": "file", "name": "Pipeline file",
            "filename": "pipeline.csv", "data": encoded,
        })
        source = self.Datasource.browse(meta["id"])
        self.assertEqual(source.dashboard_id, dashboard)
        self.assertEqual(source.row_count, 2)
        self.assertEqual({column.name for column in source.column_ids},
                         {"name", "amount", "won"})

        result = dashboard.add_item({
            "item_type": "list", "title": "File rows",
            "source_id": source.id, "list_mode": "records",
            "list_fields": ["amount", "name"], "measures": [],
            "record_limit": 50,
        })
        payload = result["payload"]
        self.assertIsNone(payload.get("error"))
        self.assertTrue(payload["record_list"])
        self.assertEqual([column["name"] for column in payload["columns"]],
                         ["amount", "name"])
        self.assertEqual(len(payload["rows"]), 2)
        self.assertEqual(payload["rows"][0]["cells"][0]["value"], 10)

    def test_fixed_sql_kpi_totals_all_rows(self):
        dashboard = self.Dashboard.create({"name": "SQL KPI"})
        source = self.Datasource.create({
            "name": "Fixed SQL", "provider_type": "sql",
            "dashboard_id": dashboard.id,
            "sql_query": "SELECT label, value FROM (VALUES ('A', 2), ('B', 3)) AS q(label, value)",
        })
        item = self.Item.create({
            "dashboard_id": dashboard.id, "datasource_id": source.id,
            "item_type": "kpi", "title": "Total",
        })
        self.assertEqual(item.get_payload()["value"], 5.0)

    def test_builder_rejects_foreign_source_and_ignores_raw_relations(self):
        first = self.Dashboard.create({"name": "First"})
        second = self.Dashboard.create({"name": "Second"})
        source = self.Datasource.create({
            "name": "Owned", "provider_type": "orm",
            "model_id": self.partner_model.id, "dashboard_id": first.id,
        })
        with self.assertRaises(UserError):
            second.add_item({
                "item_type": "tile", "source_id": source.id,
                "measures": [{"verb": "count"}],
            })
        item = second._create_item_from_builder({
            "item_type": "richtext", "content": "Safe",
            "datasource_id": source.id, "measure_ids": [(6, 0, self.count.ids)],
            "primary_dimension_id": self.country_field.id,
        })
        self.assertFalse(item.datasource_id)
        self.assertFalse(item.measure_ids)
        self.assertFalse(item.primary_dimension_id)

    # ---- settings/layout RPC contracts ------------------------------------
    def test_settings_rpc_whitelists_and_bounds_values(self):
        dashboard = self.Dashboard.create({"name": "Before"})
        original_owner = dashboard.owner_id
        saved = dashboard.save_settings({
            "name": "  After  ", "owner_id": False, "item_ids": [],
            "refresh_interval": 999999, "palette": "ocean",
        })
        self.assertEqual(dashboard.name, "After")
        self.assertEqual(dashboard.owner_id, original_owner)
        self.assertEqual(dashboard.refresh_interval, 86400)
        self.assertEqual(saved["palette"], "ocean")
        with self.assertRaises(UserError):
            dashboard.save_settings({"palette": "javascript:bad"})

    def test_digest_schedule_is_per_board_and_timezone_safe(self):
        dashboard = self.Dashboard.create({
            "name": "Digest", "digest_enabled": True,
            "digest_frequency": "daily", "digest_hour": 8,
        })
        dashboard.owner_id.tz = "UTC"
        self.assertFalse(dashboard._digest_due("2026-08-24 07:59:59"))
        self.assertTrue(dashboard._digest_due("2026-08-24 08:00:00"))
        dashboard.digest_last_sent_on = "2026-08-24 08:00:00"
        self.assertFalse(dashboard._digest_due("2026-08-24 23:59:59"))

        dashboard.write({
            "digest_frequency": "weekly", "digest_weekday": "2",
            "digest_last_sent_on": False,
        })
        self.assertFalse(dashboard._digest_due("2026-08-24 09:00:00"))
        self.assertTrue(dashboard._digest_due("2026-08-26 09:00:00"))

        dashboard.write({
            "digest_frequency": "monthly", "digest_month_day": 31,
            "digest_last_sent_on": False,
        })
        self.assertFalse(dashboard._digest_due("2026-02-27 09:00:00"))
        self.assertTrue(dashboard._digest_due("2026-02-28 09:00:00"))

    def test_layout_payload_is_bounded_and_owned(self):
        dashboard = self.Dashboard.create({"name": "Layout"})
        item = dashboard._create_item_from_builder({
            "item_type": "richtext", "content": "Card",
        })
        dashboard.save_layout({
            str(item.id): {"x": 99, "y": -8, "w": 99, "h": 9999,
                           "evil": "discard"},
            "99999999": {"x": 0, "y": 0, "w": 12, "h": 12},
            "not-an-id": "bad",
        })
        self.assertEqual(dashboard._active_layout().grid, {
            str(item.id): {"x": 11, "y": 0, "w": 1, "h": 200},
        })

    def test_visual_json_is_bounded_and_css_safe_at_rest(self):
        dashboard = self.Dashboard.create({"name": "Visual safety"})
        item = self.Item.create({
            "dashboard_id": dashboard.id, "item_type": "richtext",
            "icon": "fa-user bad-class", "record_limit": 999999,
            "chart_options": {
                "series_colors": ["#AABBCC", "red;position:fixed", "#123456789"],
                "unknown": "drop",
            },
            "conditional_rules": [
                {"measure": "0", "op": "gte", "v1": 1, "v2": 0,
                 "color": "#E8590C", "style": "fill"},
                {"measure": "", "op": "gte", "v1": 1, "v2": 0,
                 "color": "red;background:url(x)", "style": "text"},
            ],
        })
        self.assertFalse(item.icon)
        self.assertEqual(item.record_limit, 10000)
        self.assertEqual(item.chart_options, {"series_colors": ["#aabbcc"]})
        self.assertEqual(len(item.conditional_rules), 1)
        self.assertEqual(item.conditional_rules[0]["color"], "#e8590c")

    # ---- relative-date semantics -----------------------------------------
    def test_full_period_presets_differ_from_to_date(self):
        dashboard = self.Dashboard.create({"name": "Dates"})
        item = self.Item.create({
            "dashboard_id": dashboard.id, "item_type": "tile",
            "datasource_id": self.source.id,
            "measure_ids": [(6, 0, self.count.ids)],
        })
        today = fields.Date.context_today(item)
        month = item._preset_range("this_month")
        mtd = item._preset_range("mtd")
        expected_end = date(today.year, today.month, 1) \
            + relativedelta(months=1, days=-1)
        self.assertEqual(month[1], fields.Date.to_string(expected_end))
        self.assertEqual(mtd[1], fields.Date.to_string(today))
        year = item._preset_range("this_year")
        self.assertEqual(year[1], "%04d-12-31" % today.year)

    # ---- target trajectories / model-aware whole-board build -------------
    def test_dated_targets_are_canonical_and_never_backfill_future_goal(self):
        measure = self.Measure.create({
            "name": "Goal", "datasource_id": self.source.id,
            "aggregate": "count", "target_value": 7,
            "target_schedule": [
                {"date": "2026-07-01", "value": 20},
                {"date": "bad", "value": 999},
                {"date": "2026-01-01", "value": 10},
                {"date": "2026-07-01", "value": 25},
                {"date": "2026-08-01", "value": float("inf")},
            ],
        })
        self.assertEqual(measure.target_schedule, [
            {"date": "2026-01-01", "value": 10.0},
            {"date": "2026-07-01", "value": 25.0},
        ])
        self.assertEqual(measure.target_at("2025-12-01"), 7)
        self.assertEqual(measure.target_at("2026-03-01"), 10)
        self.assertEqual(measure.target_at("2026-09-01"), 25)
        self.assertEqual(measure.dated_targets_for_rows([
            {"keys": [date(2025, 12, 1)]},
            {"keys": ["2026-07-01T00:00:00"]},
        ]), [7, 25])

    def test_smart_build_creates_filters_layout_and_live_widgets(self):
        dashboard = self.Dashboard.create({"name": "Smart partner board"})
        result = dashboard.smart_build(self.partner_model.id)
        self.assertGreaterEqual(result["created"], 4)
        self.assertIn("tile", dashboard.item_ids.mapped("item_type"))
        self.assertIn("list", dashboard.item_ids.mapped("item_type"))
        self.assertTrue(dashboard.filter_ids)
        self.assertEqual(
            set(dashboard._active_layout().grid),
            {str(item_id) for item_id in dashboard.item_ids.ids})
        selected_numbers = set(dashboard.item_ids.measure_ids.mapped("field_name"))
        self.assertFalse(
            selected_numbers & {"partner_latitude", "partner_longitude"})
        self.assertIn(
            "country_id", dashboard.item_ids.primary_dimension_id.mapped("name"))
        for item in dashboard.item_ids:
            self.assertFalse(item.get_payload().get("error"), item.title)

    def test_dashboard_family_rejects_cycles_and_favorite_is_personal(self):
        parent = self.Dashboard.create({"name": "Parent"})
        child = self.Dashboard.create({
            "name": "Child", "parent_dashboard_id": parent.id})
        with self.assertRaises(ValidationError):
            parent.parent_dashboard_id = child
        user_group_field = (
            "group_ids" if "group_ids" in self.env["res.users"]._fields
            else "groups_id"
        )
        viewer_values = {
            "name": "Favorite viewer", "login": "eh_favorite_viewer",
            user_group_field: [(6, 0, [
                self.env.ref("eh_board.group_board_viewer").id])],
        }
        viewer = self.env["res.users"].create(viewer_values)
        parent.shared_user_ids = [(4, viewer.id)]
        favorite_parent = parent.with_user(viewer)
        self.assertTrue(favorite_parent.toggle_favorite()["favorite"])
        parent.invalidate_recordset(["favorite_user_ids"])
        self.assertIn(viewer, parent.favorite_user_ids)
        self.assertFalse(favorite_parent.toggle_favorite()["favorite"])

    def test_custom_window_action_is_model_scoped(self):
        dashboard = self.Dashboard.create({"name": "Actions"})
        action = self.env["ir.actions.act_window"].create({
            "name": "Partners", "res_model": "res.partner",
            "view_mode": "list,form",
        })
        item = dashboard._create_item_from_builder({
            "item_type": "tile", "title": "Partners",
            "model_id": self.partner_model.id,
            "measures": [{"verb": "count"}],
            "click_action": "action", "window_action_id": action.id,
        })
        opened = dashboard.get_item_window_action(item.id, [])
        self.assertEqual(opened["res_model"], "res.partner")
        wrong = self.env["ir.actions.act_window"].create({
            "name": "Users", "res_model": "res.users", "view_mode": "list"})
        with self.assertRaises(UserError):
            dashboard._create_item_from_builder({
                "item_type": "tile", "model_id": self.partner_model.id,
                "measures": [{"verb": "count"}],
                "click_action": "action", "window_action_id": wrong.id,
            })
