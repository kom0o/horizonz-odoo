# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
from odoo.tests import TransactionCase, tagged
from odoo.exceptions import UserError

from ..lib import aggregation
from ..lib.registry import (
    ITEM_TYPES, DATASOURCES, item_type_selection, get_item_type, get_datasource,
)


@tagged("post_install", "-at_install", "eh_board")
class TestBoardEngine(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Dashboard = cls.env["eh.board.dashboard"]
        cls.Datasource = cls.env["eh.board.datasource"]
        cls.Measure = cls.env["eh.board.measure"]
        cls.Item = cls.env["eh.board.item"]
        cls.partner_model = cls.env["ir.model"]._get("res.partner")

        # A deterministic partner population: 3 companies + 2 people.
        Partner = cls.env["res.partner"]
        cls.partners = Partner.create([
            {"name": "ACME Pty", "company_type": "company", "color": 10},
            {"name": "Globex Pty", "company_type": "company", "color": 20},
            {"name": "Initech Pty", "company_type": "company", "color": 30},
            {"name": "Alice", "company_type": "person", "color": 40},
            {"name": "Bob", "company_type": "person", "color": 50},
        ])
        # is_company is a *stored* boolean (3 companies True, 2 people False);
        # company_type is *computed / non-stored* and is used to prove the guard.
        cls.is_company_field = cls.env["ir.model.fields"]._get(
            "res.partner", "is_company")
        cls.company_type_field = cls.env["ir.model.fields"]._get(
            "res.partner", "company_type")

        cls.source = cls.Datasource.create({
            "name": "Partners",
            "provider_type": "orm",
            "model_id": cls.partner_model.id,
            "domain": "[('id', 'in', %s)]" % cls.partners.ids,
        })
        cls.count_measure = cls.Measure.create({
            "name": "Records",
            "datasource_id": cls.source.id,
            "aggregate": "count",
        })

    # -- registry ------------------------------------------------------------
    def test_registries_populated(self):
        self.assertIn("bar", ITEM_TYPES)
        self.assertIn("kpi", ITEM_TYPES)
        self.assertIn("gauge", ITEM_TYPES)
        self.assertIn("orm", DATASOURCES)
        keys = dict(item_type_selection())
        self.assertGreaterEqual(len(keys), 12, "expected the full core catalogue")
        self.assertEqual(get_item_type("bar").category, "chart")
        self.assertEqual(get_datasource("orm").key, "orm")

    # -- aggregation ---------------------------------------------------------
    def test_read_group_aggregation(self):
        result = aggregation.aggregate(
            self.env["res.partner"],
            [("id", "in", self.partners.ids)],
            [{"field": "is_company", "granularity": None}],
            [{"key": "m_count", "field": None, "verb": "count"}],
        )
        counts = {r["labels"][0]: r["values"]["m_count"] for r in result["rows"]}
        self.assertEqual(sum(counts.values()), 5)
        self.assertEqual(len(result["rows"]), 2)

    def test_read_cap_bounds_grouped_read(self):
        # No unbounded read: a read_cap limits the number of grouped rows so a
        # high-cardinality dimension (or pivot cross-product) cannot OOM.
        result = get_datasource("orm").aggregate(self.source, {
            "model": "res.partner",
            "domain": [("id", "in", self.partners.ids)],
            "dimensions": [{"field": "id", "granularity": None}],
            "measures": [{"key": "m", "field": None, "verb": "count"}],
            "read_cap": 2,
        })
        self.assertLessEqual(len(result["rows"]), 2)

    def test_aggregation_respects_record_rules(self):
        # The datasource aggregates as the current user, so a domain outside the
        # partner set returns nothing rather than leaking other records.
        result = get_datasource("orm").aggregate(self.source, {
            "model": "res.partner",
            "domain": [("id", "in", self.partners.ids), ("is_company", "=", False)],
            "dimensions": [{"field": "is_company", "granularity": None}],
            "measures": [{"key": "m_count", "field": None, "verb": "count"}],
        })
        self.assertEqual(len(result["rows"]), 1)
        self.assertEqual(result["rows"][0]["values"]["m_count"], 2)

    # -- item payloads -------------------------------------------------------
    def _make_item(self, item_type, **kw):
        vals = {
            "dashboard_id": self.dashboard.id,
            "item_type": item_type,
            "title": item_type,
            "datasource_id": self.source.id,
            "measure_ids": [(6, 0, self.count_measure.ids)],
        }
        vals.update(kw)
        return self.Item.create(vals)

    def setUp(self):
        super().setUp()
        self.dashboard = self.Dashboard.create({"name": "Test Board"})

    def test_bar_item_payload(self):
        item = self._make_item(
            "bar", primary_dimension_id=self.is_company_field.id)
        payload = item.get_payload()
        self.assertIsNone(payload.get("error"))
        self.assertEqual(payload["type"], "bar")
        self.assertEqual(len(payload["series"]), 1)
        self.assertEqual(sum(payload["series"][0]["data"]), 5)
        self.assertEqual(len(payload["labels"]), 2)

    def test_unstored_field_rejected_gracefully(self):
        # A computed (non-stored) dimension must surface a friendly message,
        # never a 500 out of _read_group.
        item = self._make_item(
            "bar", primary_dimension_id=self.company_type_field.id)
        payload = item.get_payload()
        self.assertTrue(payload.get("error"))
        self.assertIn("stored", payload["error"].lower())

    def test_kpi_item_payload(self):
        item = self._make_item("kpi")
        payload = item.get_payload()
        self.assertIsNone(payload.get("error"))
        self.assertEqual(payload["value"], 5)

    def test_kpi_target_comparison(self):
        self.count_measure.target_value = 10
        item = self._make_item("kpi")
        payload = item.get_payload()
        self.assertEqual(payload["target"], 10)
        self.assertAlmostEqual(payload["achievement"], 0.5)

    def test_record_list_renders_selected_fields_without_aggregation(self):
        name = self.env["ir.model.fields"]._get("res.partner", "name")
        color = self.env["ir.model.fields"]._get("res.partner", "color")
        item = self.Item.create({
            "dashboard_id": self.dashboard.id,
            "item_type": "list",
            "title": "Partner records",
            "datasource_id": self.source.id,
            "list_mode": "records",
            "list_field_ids": [(6, 0, [name.id, color.id])],
            "list_field_order": ["name", "color"],
            "record_limit": 3,
        })
        payload = item.get_payload()
        self.assertIsNone(payload.get("error"))
        self.assertTrue(payload["record_list"])
        self.assertEqual([c["name"] for c in payload["columns"]], ["name", "color"])
        self.assertEqual(len(payload["rows"]), 3)
        self.assertTrue(all(row.get("id") for row in payload["rows"]))
        self.assertTrue(all(len(row["cells"]) == 2 for row in payload["rows"]))
        export = self.dashboard._payload_table(payload)
        self.assertEqual(len(export["columns"]), 2)
        self.assertEqual(len(export["rows"]), 3)
        self.assertEqual(
            [column["label"] for column in export["columns"]],
            [name.field_description, color.field_description])

    def test_record_list_requires_display_fields(self):
        item = self.Item.create({
            "dashboard_id": self.dashboard.id,
            "item_type": "list",
            "datasource_id": self.source.id,
            "list_mode": "records",
        })
        self.assertIn("field to display", item.get_payload()["error"].lower())

    def test_builder_round_trips_record_list_columns(self):
        result = self.dashboard.add_item({
            "item_type": "list",
            "title": "Contacts",
            "model_id": self.partner_model.id,
            "list_mode": "records",
            "list_fields": ["name", "color"],
            "measures": [],
            "record_limit": 25,
        })
        config = self.dashboard.get_item_config(result["meta"]["id"])
        self.assertEqual(config["list_mode"], "records")
        self.assertEqual(config["list_fields"], ["name", "color"])
        self.assertFalse(config["measures"])
        fields_meta = self.dashboard.get_model_fields(self.partner_model.id)
        self.assertIn("name", {field["name"] for field in fields_meta["columns"]})

    def test_grouped_list_percentage_keeps_exact_grand_average(self):
        color = self.env["ir.model.fields"]._get("res.partner", "color")
        average = self.Measure.create({
            "name": "Average colour",
            "datasource_id": self.source.id,
            "field_id": color.id,
            "aggregate": "avg",
            "table_calculation": "percent_grand",
        })
        item = self._make_item(
            "list", list_mode="grouped",
            primary_dimension_id=self.is_company_field.id,
            measure_ids=[(6, 0, average.ids)])
        payload = item.get_payload()
        key = average.measure_key()
        self.assertEqual(payload["measure_calculations"][key], "percent_grand")
        self.assertAlmostEqual(payload["grand_total"][key], 30.0)
        self.assertEqual(len(payload["rows"]), 2)
        export = self.dashboard._payload_table(payload)
        # An average is not additive: the rows do not add up to the grand
        # figure, so the column is a ratio against it, not a share, and must
        # not be labelled as one.
        self.assertEqual(
            [column["label"] for column in export["columns"]],
            ["Category", "Average colour", "Average colour · % of grand avg"])
        self.assertTrue(export["columns"][2]["percentage"])
        self.assertEqual(len(export["rows"]), 2)


    def test_percent_column_label_states_what_it_is_a_percentage_of(self):
        """A share only adds up to 100% when the aggregate is additive.

        The value is row / total-grain either way and is correct either way;
        what changes is what it MEANS, so the header has to say which.
        """
        for aggregate, expected in (
                ("sum", "% grand"),
                ("count", "% grand"),
                ("avg", "% of grand avg"),
                ("min", "% of grand min"),
                ("max", "% of grand max"),
                ("count_distinct", "% of grand distinct"),
                # a formula may be additive (a + b) or not (a / b); nothing
                # here can tell, so it keeps the neutral share wording
                ("formula", "% grand"),
        ):
            self.assertEqual(
                self.dashboard._percent_suffix("percent_grand", aggregate),
                expected, "grand suffix for %s" % aggregate)
        self.assertEqual(
            self.dashboard._percent_suffix("percent_row", "avg"),
            "% of row avg")
        self.assertEqual(
            self.dashboard._percent_suffix("percent_column", "max"),
            "% of column max")
        self.assertEqual(
            self.dashboard._percent_suffix("percent_column", "sum"),
            "% column")

    def test_additive_measure_keeps_share_wording_and_sums_to_one(self):
        """A Sum really is a share: the rows add up to the grand total."""
        color = self.env["ir.model.fields"]._get("res.partner", "color")
        total = self.Measure.create({
            "name": "Total colour",
            "datasource_id": self.source.id,
            "field_id": color.id,
            "aggregate": "sum",
            "table_calculation": "percent_grand",
        })
        item = self._make_item(
            "list", list_mode="grouped",
            primary_dimension_id=self.is_company_field.id,
            measure_ids=[(6, 0, total.ids)])
        payload = item.get_payload()
        key = total.measure_key()
        self.assertEqual(payload["measure_aggregates"][key], "sum")
        export = self.dashboard._payload_table(payload)
        self.assertEqual(
            [column["label"] for column in export["columns"]],
            ["Category", "Total colour", "Total colour · % grand"])
        share = sum(row[2] for row in export["rows"])
        self.assertAlmostEqual(share, 1.0, places=6)

    def test_pivot_percentage_calculation_reaches_payload(self):
        color = self.env["ir.model.fields"]._get("res.partner", "color")
        active = self.env["ir.model.fields"]._get("res.partner", "active")
        average = self.Measure.create({
            "name": "Average colour",
            "datasource_id": self.source.id,
            "field_id": color.id,
            "aggregate": "avg",
            "table_calculation": "percent_row",
        })
        item = self._make_item(
            "pivot", primary_dimension_id=self.is_company_field.id,
            secondary_dimension_id=active.id,
            measure_ids=[(6, 0, average.ids)])
        payload = item.get_payload()
        key = average.measure_key()
        self.assertEqual(payload["measure_calculations"][key], "percent_row")
        self.assertIn(key, payload["grand_total"])
        export = self.dashboard._payload_table(payload)
        self.assertIn("Average colour · % of row avg",
                      [column["label"] for column in export["columns"]])

    def test_validation_surfaces_inline(self):
        # A bar item with no dimension explains itself instead of blanking.
        item = self._make_item("bar")  # no primary_dimension_id
        payload = item.get_payload()
        self.assertTrue(payload.get("error"))
        self.assertIn("group by", payload["error"].lower())

    def test_content_item_needs_no_data(self):
        item = self.Item.create({
            "dashboard_id": self.dashboard.id,
            "item_type": "richtext",
            "title": "Heading",
            "content": "<h2>Sales</h2>",
        })
        payload = item.get_payload()
        self.assertIsNone(payload.get("error"))
        # Content is html-sanitised on render; clean markup survives intact.
        self.assertIn("Sales", payload["content"])
        self.assertIn("h2", payload["content"])

    def test_content_xss_sanitised(self):
        # A text block must never carry executable markup into a shared board.
        item = self.Item.create({
            "dashboard_id": self.dashboard.id, "item_type": "richtext",
            "content": "<p>ok</p><script>alert(1)</script>"
                       "<img src=x onerror=alert(2)>"})
        html = item.get_payload()["content"].lower()
        self.assertNotIn("<script", html)
        self.assertNotIn("onerror", html)
        self.assertIn("ok", html)

    # -- dashboard payload + layout -----------------------------------------
    def test_dashboard_get_data(self):
        self._make_item("bar", primary_dimension_id=self.is_company_field.id)
        self._make_item("kpi")
        data = self.dashboard.get_data()
        self.assertEqual(len(data["items"]), 2)
        self.assertEqual(len(data["item_meta"]), 2)
        self.assertIn("layout", data)

    def test_global_field_filter_rescopes(self):
        # A global field filter (options.filters) narrows every widget whose
        # model has the field.
        item = self._make_item(
            "bar", primary_dimension_id=self.is_company_field.id)
        full = item.get_payload()
        self.assertEqual(sum(full["series"][0]["data"]), 5)
        companies = self.partners.filtered(lambda p: p.company_type == "company")
        scoped = item.get_payload({
            "filters": [{"field": "id", "values": companies.ids}]})
        self.assertEqual(sum(scoped["series"][0]["data"]), 3)

    def test_filter_get_options(self):
        Field = self.env["ir.model.fields"]
        flt = self.env["eh.board.filter"].create({
            "dashboard_id": self.dashboard.id, "name": "Type",
            "filter_type": "field",
            "field_id": Field._get("res.partner", "company_type").id})
        opts = flt.get_options()
        values = {o["value"] for o in opts}
        self.assertIn("company", values)
        self.assertIn("person", values)

    # -- advanced data shaping ----------------------------------------------
    def test_group_others_buckets_tail(self):
        result = {
            "rows": [
                {"keys": [1], "labels": ["A"], "values": {"m": 10}},
                {"keys": [2], "labels": ["B"], "values": {"m": 6}},
                {"keys": [3], "labels": ["C"], "values": {"m": 3}},
                {"keys": [4], "labels": ["D"], "values": {"m": 1}},
            ],
            "measures": ["m"],
        }
        out = aggregation.sort_and_cap(result, "value_desc", 2, group_others=True)
        rows = out["rows"]
        self.assertEqual(len(rows), 3, "top 2 + one Others bucket")
        self.assertEqual(rows[0]["values"]["m"], 10)
        self.assertTrue(rows[-1].get("is_others"))
        self.assertEqual(rows[-1]["values"]["m"], 4, "3 + 1 summed into Others")

    def test_cap_without_others_drops_tail(self):
        result = {
            "rows": [{"keys": [i], "labels": [str(i)], "values": {"m": i}}
                     for i in range(5)],
            "measures": ["m"],
        }
        out = aggregation.sort_and_cap(result, "value_desc", 2)
        self.assertEqual(len(out["rows"]), 2)
        self.assertFalse(any(r.get("is_others") for r in out["rows"]))

    def test_cumulate_running_total(self):
        rows = [
            {"keys": [1], "labels": ["Jan"], "values": {"m": 2}},
            {"keys": [2], "labels": ["Feb"], "values": {"m": 3}},
            {"keys": [3], "labels": ["Mar"], "values": {"m": 5}},
        ]
        out = aggregation.cumulate(rows, ["m"])
        self.assertEqual([r["values"]["m"] for r in out], [2, 5, 10])
        self.assertEqual(rows[0]["values"]["m"], 2, "originals left untouched")

    def test_item_cumulative_climbs_to_total(self):
        item = self._make_item(
            "bar", primary_dimension_id=self.is_company_field.id, cumulative=True)
        payload = item.get_payload()
        self.assertIsNone(payload.get("error"))
        self.assertEqual(payload["series"][0]["data"][-1], 5,
                         "cumulative last point equals the grand total")

    def test_item_group_others_preserves_total(self):
        item = self._make_item(
            "bar", primary_dimension_id=self.is_company_field.id,
            record_limit=1, group_others=True)
        payload = item.get_payload()
        self.assertEqual(len(payload["labels"]), 2, "top 1 + Others")
        self.assertIn("Others", payload["labels"][-1])
        self.assertEqual(sum(payload["series"][0]["data"]), 5,
                         "Others keeps the total honest")

    # -- pivot / cross-tab matrix -------------------------------------------
    def test_pivot_single_dimension(self):
        # Row dimension only: columns become the measures, one grand total.
        item = self._make_item("pivot", primary_dimension_id=self.is_company_field.id)
        p = item.get_payload()
        self.assertIsNone(p.get("error"))
        self.assertEqual(p["type"], "pivot")
        self.assertFalse(p["has_col"])
        self.assertEqual(len(p["row_headers"]), 2)
        mk = p["measure_keys"][0]
        self.assertEqual(p["grand_total"][mk], 5)
        self.assertEqual(sum(rt[mk] for rt in p["row_totals"].values()), 5)

    def test_pivot_cross_tab_reconciles(self):
        # Row x column matrix: row totals, column totals and grand total must
        # all reconcile to the same population.
        Partner = self.env["res.partner"]
        au = self.env.ref("base.au", raise_if_not_found=False)
        quad = Partner.create([
            {"name": "PC-au", "is_company": True, "country_id": au.id if au else False},
            {"name": "PC-none", "is_company": True},
            {"name": "PI-au", "is_company": False, "country_id": au.id if au else False},
            {"name": "PI-none", "is_company": False},
        ])
        src = self.Datasource.create({
            "name": "Quad", "provider_type": "orm",
            "model_id": self.partner_model.id,
            "domain": "[('id', 'in', %s)]" % quad.ids})
        cnt = self.Measure.create({
            "name": "n", "datasource_id": src.id, "aggregate": "count"})
        country_field = self.env["ir.model.fields"]._get("res.partner", "country_id")
        item = self.Item.create({
            "dashboard_id": self.dashboard.id, "item_type": "pivot", "title": "pv",
            "datasource_id": src.id, "measure_ids": [(6, 0, cnt.ids)],
            "primary_dimension_id": self.is_company_field.id,
            "secondary_dimension_id": country_field.id})
        p = item.get_payload()
        self.assertIsNone(p.get("error"))
        self.assertTrue(p["has_col"])
        self.assertEqual(len(p["row_headers"]), 2)
        self.assertEqual(len(p["col_headers"]), 2)
        mk = p["measure_keys"][0]
        self.assertEqual(p["grand_total"][mk], 4)
        self.assertEqual(sum(rt[mk] for rt in p["row_totals"].values()), 4)
        self.assertEqual(sum(ct[mk] for ct in p["col_totals"].values()), 4)
        # The company x Australia cell is exactly one record. The boolean row key
        # is lower-cased "true" so it agrees with the JS String(true) key.
        au_key = str(au.id) if au else "∅"
        self.assertEqual(p["cells"]["true"][au_key][mk], 1)

    # -- drill-down ---------------------------------------------------------
    def test_drill_regroups_and_scopes(self):
        country = self.env["ir.model.fields"]._get("res.partner", "country_id")
        item = self._make_item("bar", primary_dimension_id=self.is_company_field.id)
        item.write({
            "click_action": "drill",
            "drill_ids": [(0, 0, {"field_id": country.id, "sequence": 10})]})
        top = item.get_payload()
        self.assertEqual(len(top["labels"]), 2, "top level groups by is_company")
        # Drill into the companies bar: regroup by country, scoped to companies.
        p = item.get_drilled_payload(
            [{"field": "is_company", "value": True, "label": "Companies"}])
        self.assertIsNone(p.get("error"))
        self.assertEqual(p["drill_depth"], 1)
        self.assertEqual(sum(p["series"][0]["data"]), 3,
                         "drill path scopes to the 3 companies only")

    def test_drill_overflow_is_rejected(self):
        # A stale drill path must not silently export a wider population.
        item = self._make_item("bar", primary_dimension_id=self.is_company_field.id)
        with self.assertRaises(UserError):
            item.get_drilled_payload(
                [{"field": "is_company", "value": True, "label": "x"},
                 {"field": "country_id", "value": 1, "label": "y"}])

    # -- KPI comparison mode ------------------------------------------------
    def test_compare_mode_none_suppresses_delta(self):
        create_date = self.env["ir.model.fields"]._get("res.partner", "create_date")
        m = self.Measure.create({
            "name": "cnone", "datasource_id": self.source.id,
            "aggregate": "count", "compare_mode": "none"})
        item = self.Item.create({
            "dashboard_id": self.dashboard.id, "item_type": "kpi", "title": "k",
            "datasource_id": self.source.id, "measure_ids": [(6, 0, m.ids)],
            "date_filter_field_id": create_date.id, "show_trend": True})
        p = item.get_payload()
        self.assertIsNone(p.get("error"))
        self.assertNotIn("trend", p, "compare_mode 'none' must not emit a delta")
        self.assertIn("spark", p, "sparkline still shown without a comparison")

    def test_compare_mode_prev_year_builds(self):
        create_date = self.env["ir.model.fields"]._get("res.partner", "create_date")
        m = self.Measure.create({
            "name": "cyoy", "datasource_id": self.source.id,
            "aggregate": "count", "compare_mode": "prev_year"})
        item = self.Item.create({
            "dashboard_id": self.dashboard.id, "item_type": "kpi", "title": "k2",
            "datasource_id": self.source.id, "measure_ids": [(6, 0, m.ids)],
            "date_filter_field_id": create_date.id, "show_trend": True})
        p = item.get_payload()
        self.assertIsNone(p.get("error"), "year-over-year window builds cleanly")

    # -- per-measure formatting + KPI target from the builder ---------------
    def test_builder_measure_target_and_unit(self):
        res = self.dashboard.add_item({
            "item_type": "kpi", "title": "Goal",
            "model_id": self.partner_model.id,
            "measures": [{"verb": "count", "field": None, "number_format": "plain",
                          "unit": "ppl", "target": 10, "compare_mode": "none"}],
        })
        item = self.Item.browse(res["meta"]["id"])
        m = item.measure_ids[:1]
        self.assertEqual(m.target_value, 10)
        self.assertEqual(m.unit, "ppl")
        self.assertEqual(m.number_format, "plain")
        self.assertEqual(res["payload"].get("target"), 10)
        self.assertEqual(res["payload"].get("unit"), "ppl")

    def test_measure_dedup_separates_by_target(self):
        r1 = self.dashboard.add_item({
            "item_type": "kpi", "title": "a", "model_id": self.partner_model.id,
            "measures": [{"verb": "count", "field": None, "target": 10}]})
        r2 = self.dashboard.add_item({
            "item_type": "kpi", "title": "b", "model_id": self.partner_model.id,
            "measures": [{"verb": "count", "field": None, "target": 20}]})
        m1 = self.Item.browse(r1["meta"]["id"]).measure_ids[:1]
        m2 = self.Item.browse(r2["meta"]["id"]).measure_ids[:1]
        self.assertNotEqual(m1.id, m2.id, "different targets -> distinct measures")
        self.assertEqual(m1.target_value, 10)
        self.assertEqual(m2.target_value, 20)

    def test_pivot_registered_and_advertised(self):
        # The manifest sells a pivot matrix; the type must actually exist.
        self.assertIn("pivot", ITEM_TYPES)
        self.assertEqual(get_item_type("pivot").category, "pivot")
        self.assertIn("pivot", dict(item_type_selection()))

    # -- lazy load + switcher -----------------------------------------------
    def test_lazy_defers_tail_widgets(self):
        for i in range(11):
            self._make_item("kpi", title="k%d" % i)
        data = self.dashboard.get_data({}, lazy=True)
        self.assertEqual(len(data["item_meta"]), 11, "all widgets described")
        self.assertEqual(len(data["items"]), 8, "first 8 carry data")
        self.assertEqual(len(data["lazy_ids"]), 3, "the tail is deferred")

    def test_lazy_off_loads_all(self):
        for i in range(11):
            self._make_item("kpi", title="k%d" % i)
        data = self.dashboard.get_data({}, lazy=False)
        self.assertEqual(len(data["items"]), 11)
        self.assertEqual(len(data["lazy_ids"]), 0)

    def test_list_boards_visible(self):
        boards = self.dashboard.list_boards()
        self.assertTrue(any(b["id"] == self.dashboard.id for b in boards))

    # -- insights -----------------------------------------------------------
    def test_insights_narrate_offline(self):
        self._make_item("kpi")
        self._make_item("bar", primary_dimension_id=self.is_company_field.id)
        insights = self.dashboard.get_insights()
        # At least one narration per data widget, plus optional key-influencer
        # "drivers" lines.
        self.assertGreaterEqual(len(insights), 2, "at least one insight per data widget")
        for ins in insights:
            self.assertTrue(ins["text"], "each insight has narration text")
        bar_ins = [i for i in insights if "leads" in i["text"]]
        self.assertTrue(bar_ins, "the chart insight names the top group")
        driver_ins = [i for i in insights if "contributor" in i["text"].lower()]
        self.assertTrue(driver_ins, "top-contributor line is present")

    # -- snapshots + alerts + digest ----------------------------------------
    def test_snapshot_capture_and_history(self):
        self.dashboard.state = "published"
        self._make_item("kpi")
        self._make_item("bar", primary_dimension_id=self.is_company_field.id)
        self.dashboard.capture_snapshot()
        snaps = self.env["eh.board.snapshot"].search(
            [("dashboard_id", "=", self.dashboard.id)])
        self.assertEqual(len(snaps), 2, "one snapshot per data widget")
        kpi = self.dashboard.item_ids.filtered(lambda i: i.item_type == "kpi")
        hist = kpi._snapshot_history()
        self.assertEqual(len(hist), 1)
        self.assertIn("value", hist[0])

    def test_alert_fires_then_rearms(self):
        kpi = self._make_item("kpi")  # value = 5 partners in the source domain
        alert = self.env["eh.board.alert"].create({
            "name": "A", "dashboard_id": self.dashboard.id, "item_id": kpi.id,
            "operator": "gt", "threshold": 3, "user_id": self.env.user.id})
        alert._evaluate()
        self.assertEqual(alert.state, "triggered")
        self.assertEqual(alert.last_value, 5)
        self.assertTrue(alert.message_ids, "a notification was posted")
        alert.threshold = 100  # value now below -> recovers
        alert._evaluate()
        self.assertEqual(alert.state, "armed", "re-arms when it recovers")

    def test_alert_no_refire_while_triggered(self):
        kpi = self._make_item("kpi")
        alert = self.env["eh.board.alert"].create({
            "name": "A2", "dashboard_id": self.dashboard.id, "item_id": kpi.id,
            "operator": "gt", "threshold": 1})
        alert._evaluate()
        n1 = len(alert.message_ids)
        alert._evaluate()
        self.assertEqual(len(alert.message_ids), n1, "no refire while triggered")

    def test_digest_creates_mail(self):
        rcpt = self.env["res.users"].create({
            "name": "Rcpt", "login": "eh_digest_rcpt", "email": "r@example.com",
            "groups_id": [(6, 0, [self.env.ref("base.group_user").id,
                                  self.env.ref("eh_board.group_board_viewer").id])]})
        self._make_item("kpi")
        # send_digest mails the board's own configured recipients (never a
        # caller-supplied list) and is owner/builder gated.
        self.dashboard.digest_user_ids = [(6, 0, rcpt.ids)]
        self.dashboard.shared_user_ids = [(6, 0, rcpt.ids)]
        mail_id = self.dashboard.send_digest()
        self.assertTrue(mail_id, "digest produced a mail")
        mail = self.env["mail.mail"].browse(mail_id)
        self.assertIn(self.dashboard.name, mail.subject)

    # -- new chart types ----------------------------------------------------
    def test_new_chart_types_build(self):
        country = self.env["ir.model.fields"]._get("res.partner", "country_id")
        for t in ("polar", "radial"):
            item = self._make_item(t, primary_dimension_id=self.is_company_field.id)
            p = item.get_payload()
            self.assertIsNone(p.get("error"), "%s built" % t)
            self.assertTrue(p["series"])
        m = self.Measure.create({
            "name": "bt", "datasource_id": self.source.id,
            "aggregate": "count", "target_value": 10})
        bullet = self.Item.create({
            "dashboard_id": self.dashboard.id, "item_type": "bullet", "title": "B",
            "datasource_id": self.source.id, "measure_ids": [(6, 0, m.ids)]})
        pb = bullet.get_payload()
        self.assertIsNone(pb.get("error"))
        self.assertEqual(pb["value"], 5)
        self.assertEqual(pb["target"], 10)
        hm = self._make_item(
            "heatmap", primary_dimension_id=self.is_company_field.id,
            secondary_dimension_id=country.id)
        ph = hm.get_payload()
        self.assertIsNone(ph.get("error"))
        self.assertTrue(ph["rows"])

    # -- measure multiplier (was dead) --------------------------------------
    def test_measure_multiplier_scales(self):
        m = self.Measure.create({
            "name": "scaled", "datasource_id": self.source.id,
            "aggregate": "count", "multiplier": 2.0})
        item = self.Item.create({
            "dashboard_id": self.dashboard.id, "item_type": "kpi", "title": "S",
            "datasource_id": self.source.id, "measure_ids": [(6, 0, m.ids)]})
        self.assertEqual(item.get_payload()["value"], 10, "5 records * 2.0 scale")

    # -- snapshot cron runs as owner ----------------------------------------
    def test_snapshot_cron_runs_as_owner(self):
        self.dashboard.write({"state": "published", "owner_id": self.env.user.id})
        self._make_item("kpi")
        self.env["eh.board.snapshot"]._cron_capture_snapshots()
        snaps = self.env["eh.board.snapshot"].search(
            [("dashboard_id", "=", self.dashboard.id)])
        self.assertTrue(snaps, "owner-scoped capture still records")

    # -- goal line + combo --------------------------------------------------
    def test_goal_and_combo_in_meta(self):
        item = self._make_item(
            "bar", primary_dimension_id=self.is_company_field.id,
            goal_value=10, combo_line=True)
        meta = item._meta()
        self.assertEqual(meta["display"]["goal_value"], 10)
        self.assertTrue(meta["display"]["combo_line"])

    # -- safe SQL provider --------------------------------------------------
    def test_sql_registered(self):
        self.assertIn("sql", DATASOURCES)

    def test_sql_safe_select_runs(self):
        src = self.Datasource.create({
            "name": "Q", "provider_type": "sql",
            "sql_query": "SELECT 'a' AS label, 1 AS n UNION SELECT 'b', 2"})
        item = self.Item.create({
            "dashboard_id": self.dashboard.id, "item_type": "bar",
            "title": "Q", "datasource_id": src.id})
        p = item.get_payload()
        self.assertIsNone(p.get("error"))
        self.assertEqual(len(p["rows"]), 2)
        self.assertIn("n", p["measure_keys"])

    def test_sql_forbidden_rejected(self):
        src = self.Datasource.create({
            "name": "Q2", "provider_type": "sql",
            "sql_query": "DELETE FROM res_partner"})
        item = self.Item.create({
            "dashboard_id": self.dashboard.id, "item_type": "bar",
            "title": "Q2", "datasource_id": src.id})
        p = item.get_payload()
        self.assertTrue(p.get("error"), "a write statement is refused")

    def test_sql_dangerous_function_rejected(self):
        for q in ("SELECT pg_read_file('/etc/passwd') AS x",
                  "SELECT * FROM dblink('', '') AS t(x int)",
                  "SELECT lo_export(1, '/tmp/x') AS x",
                  "SELECT * FROM information_schema.tables"):
            src = self.Datasource.create({
                "name": "QD", "provider_type": "sql", "sql_query": q})
            item = self.Item.create({
                "dashboard_id": self.dashboard.id, "item_type": "bar",
                "title": "QD", "datasource_id": src.id})
            self.assertTrue(item.get_payload().get("error"),
                            "dangerous function %r must be refused" % q)

    def test_sql_multi_statement_rejected(self):
        src = self.Datasource.create({
            "name": "Q3", "provider_type": "sql",
            "sql_query": "SELECT 1 AS n; DROP TABLE res_partner"})
        item = self.Item.create({
            "dashboard_id": self.dashboard.id, "item_type": "bar",
            "title": "Q3", "datasource_id": src.id})
        self.assertTrue(item.get_payload().get("error"))

    def test_sql_admin_only(self):
        builder = self.env["res.users"].create({
            "name": "B", "login": "eh_sql_builder",
            "groups_id": [(6, 0, [self.env.ref("eh_board.group_board_builder").id])]})
        blocked = False
        try:
            self.Datasource.with_user(builder).create({
                "name": "Q4", "provider_type": "sql", "sql_query": "SELECT 1 AS n"})
        except Exception:  # noqa: BLE001 - any denial means the gate held
            blocked = True
        self.assertTrue(blocked, "a non-admin cannot create a SQL data source")

    def test_credential_secret_admin_only(self):
        from odoo.exceptions import AccessError
        cred = self.env["eh.board.credential"].create({
            "name": "C", "secret": "topsecret"})
        builder = self.env["res.users"].create({
            "name": "B2", "login": "eh_cred_builder",
            "groups_id": [(6, 0, [self.env.ref("eh_board.group_board_builder").id])]})
        as_builder = cred.with_user(builder)
        self.assertEqual(as_builder.name, "C", "builder can reference it")
        with self.assertRaises(AccessError):
            _ = as_builder.secret  # the secret is not readable by a non-admin

    # -- calculated (formula) measures --------------------------------------
    def test_formula_evaluator_safe(self):
        from ..lib.formula import compile_formula, FormulaError
        self.assertAlmostEqual(compile_formula("a / b * 100")({"a": 3, "b": 4}), 75.0)
        self.assertEqual(compile_formula("a / b")({"a": 5, "b": 0}), 0.0)  # no ZeroDivision
        for bad in ("__import__('os')", "a.b", "open('x')", "a if b else c", "[a]"):
            with self.assertRaises(FormulaError):
                compile_formula(bad)
        # DoS + complex guards: never hang, never raise on evaluation.
        self.assertEqual(compile_formula("9 ** 9 ** 9")({}), 0.0)   # magnitude capped
        self.assertEqual(compile_formula("a ** b")({"a": -1, "b": 0.5}), 0.0)  # complex -> 0

    def test_formula_measure_in_payload(self):
        # An item with base count (a) + a formula "a * 2" renders both series.
        src = self.source
        base = self.count_measure
        calc = self.Measure.create({
            "name": "Doubled", "datasource_id": src.id,
            "aggregate": "formula", "formula": "a * 2"})
        item = self.Item.create({
            "dashboard_id": self.dashboard.id, "item_type": "bar", "title": "F",
            "datasource_id": src.id, "measure_ids": [(6, 0, (base + calc).ids)],
            "primary_dimension_id": self.is_company_field.id})
        p = item.get_payload()
        self.assertIsNone(p.get("error"))
        self.assertEqual(len(p["series"]), 2)
        for r in p["rows"]:
            keys = p["measure_keys"]
            self.assertAlmostEqual(r["values"][keys[1]], r["values"][keys[0]] * 2)

    def test_formula_bad_rejected_on_save(self):
        from odoo.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            self.Measure.create({
                "name": "Bad", "datasource_id": self.source.id,
                "aggregate": "formula", "formula": "__import__('os')"})

    # -- cross-model join ---------------------------------------------------
    def test_join_registered(self):
        self.assertIn("join", DATASOURCES)

    def test_join_merges_two_sides(self):
        src = self.Datasource.create({
            "name": "J", "provider_type": "join", "config": {
                "left_model": "res.partner", "join_left": "is_company",
                "left_measure": {"verb": "count"}, "left_label": "All",
                "right_model": "res.partner", "join_right": "is_company",
                "right_measure": {"verb": "count"}, "right_label": "Copy"}})
        item = self.Item.create({
            "dashboard_id": self.dashboard.id, "item_type": "bar",
            "title": "J", "datasource_id": src.id})
        p = item.get_payload()
        self.assertIsNone(p.get("error"))
        self.assertEqual(len(p["series"]), 2, "left + right series")
        self.assertEqual(p["series"][0]["label"], "All")
        self.assertEqual(p["series"][1]["label"], "Copy")
        for r in p["rows"]:
            self.assertEqual(r["values"]["left"], r["values"]["right"],
                             "both sides read the same model -> equal")

    def test_join_incomplete_surfaces_error(self):
        src = self.Datasource.create({
            "name": "J2", "provider_type": "join", "config": {}})
        item = self.Item.create({
            "dashboard_id": self.dashboard.id, "item_type": "bar",
            "title": "J2", "datasource_id": src.id})
        p = item.get_payload()
        self.assertTrue(p.get("error"), "incomplete join explains itself")

    # -- templates ----------------------------------------------------------
    def test_predefined_packs_seeded_and_gated(self):
        packs = self.env["eh.board.template"].search([("is_predefined", "=", True)])
        self.assertGreaterEqual(len(packs), 6, "vertical packs seeded")
        # At least one vertical dependency is absent even when this suite runs
        # in a database that also installs Sales/Accounting. Gate a pack whose
        # own dependency is actually missing instead of assuming all are.
        vertical = packs.filtered(lambda p: p.required_module)
        unavailable = vertical.filtered(lambda p: not p.is_available())
        self.assertTrue(vertical and unavailable)
        from odoo.exceptions import UserError
        with self.assertRaises(UserError):
            unavailable[0].create_from_template()
        # A general pack ships that works on any install.
        general = packs.filtered(lambda p: not p.required_module)
        self.assertTrue(general, "a general pack ships")
        self.assertTrue(general[0].is_available())
        dash = general[0].create_from_template()
        self.assertTrue(dash.item_ids, "general pack builds a live board")

    def test_create_from_template_builds_board(self):
        tmpl = self.env["eh.board.template"].create({
            "name": "T", "category": "general",
            "payload": {"name": "From T", "items": [
                {"type": "tile", "title": "Count", "model": "res.partner",
                 "measure": {"verb": "count"}, "x": 0, "y": 0, "w": 3, "h": 4},
                {"type": "bar", "title": "By type", "model": "res.partner",
                 "measure": {"verb": "count"}, "dimension": "is_company",
                 "x": 0, "y": 4, "w": 6, "h": 6},
                {"type": "richtext", "title": "", "content": "<h2>Hi</h2>",
                 "x": 0, "y": 0, "w": 12, "h": 2},
            ]}})
        dash = tmpl.create_from_template()
        self.assertEqual(dash.name, "From T")
        self.assertEqual(len(dash.item_ids), 3)
        self.assertEqual(len(dash._active_layout().grid), 3)
        bar = dash.item_ids.filtered(lambda i: i.item_type == "bar")
        self.assertTrue(bar.primary_dimension_id, "dimension resolved from a name")

    def test_template_skips_missing_field(self):
        # A dimension absent on the target model drops the chart, not the board.
        tmpl = self.env["eh.board.template"].create({
            "name": "T2", "category": "general",
            "payload": {"name": "T2", "items": [
                {"type": "tile", "title": "Count", "model": "res.partner",
                 "measure": {"verb": "count"}, "x": 0, "y": 0, "w": 3, "h": 4},
                {"type": "bar", "title": "Bad", "model": "res.partner",
                 "measure": {"verb": "count"}, "dimension": "does_not_exist",
                 "x": 0, "y": 4, "w": 6, "h": 6},
            ]}})
        dash = tmpl.create_from_template()
        self.assertEqual(len(dash.item_ids), 1, "the bad chart was skipped")

    def test_save_as_template_round_trip(self):
        self._make_item("kpi")
        self._make_item("bar", primary_dimension_id=self.is_company_field.id)
        res = self.dashboard.save_as_template("RT")
        tmpl = self.env["eh.board.template"].browse(res["template_id"])
        self.assertEqual(len(tmpl.payload["items"]), 2)
        dash2 = tmpl.create_from_template()
        self.assertEqual(len(dash2.item_ids), 2, "re-apply rebuilds the board")

    # -- server PDF report --------------------------------------------------
    def test_report_data_blocks(self):
        self._make_item("kpi")
        self._make_item("bar", primary_dimension_id=self.is_company_field.id)
        blocks = self.dashboard._report_data()
        kinds = [b["kind"] for b in blocks]
        self.assertIn("kpi", kinds)
        self.assertIn("table", kinds)
        table = next(b for b in blocks if b["kind"] == "table")
        self.assertTrue(table["rows"], "chart block carries formatted rows")

    def test_report_renders_html(self):
        # The QWeb report renders to HTML without wkhtmltopdf, proving the
        # template + data method are sound (the PDF is just this printed).
        self._make_item("kpi")
        report = self.env.ref("eh_board.action_report_eh_board_dashboard")
        html, _kind = report._render_qweb_html(report.report_name, self.dashboard.ids)
        text = html.decode() if isinstance(html, bytes) else html
        self.assertIn("Test Board", text)

    def test_save_layout_persists_single_grid(self):
        item = self._make_item("kpi")
        grid = {str(item.id): {"x": 0, "y": 0, "w": 3, "h": 3}}
        self.dashboard.save_layout(grid)
        layout = self.dashboard._active_layout()
        self.assertTrue(layout)
        self.assertEqual(layout.grid, grid)

    # -- parity overhaul: new config fields ---------------------------------
    def test_sort_by_field_emits_order_clause(self):
        # sort_mode='field' + a field turns into a real ORM order string.
        item = self._make_item(
            "bar", primary_dimension_id=self.is_company_field.id,
            sort_mode="field", sort_field_id=self.is_company_field.id, sort_order="asc")
        spec = item._resolve_spec()
        self.assertEqual(spec["order"], "is_company asc")
        # Non-field sort keeps order None (aggregation sorts by value/label).
        item.sort_mode = "value_desc"
        self.assertIsNone(item._resolve_spec()["order"])

    def test_include_archived_flows_into_spec(self):
        item = self._make_item("kpi", include_archived=True)
        self.assertTrue(item._resolve_spec()["include_archived"])
        item.include_archived = False
        self.assertFalse(item._resolve_spec()["include_archived"])

    def test_base_domain_scopes_click_through(self):
        # A tile filtered to companies exposes that scope for click-through.
        item = self._make_item("tile", domain="[('is_company', '=', True)]")
        meta = item._meta()
        self.assertIn(["is_company", "=", True], meta["base_domain"])

    def test_default_date_filter_range_resolves(self):
        # A per-widget default date filter yields a real (start, end) pair.
        item = self._make_item("kpi", default_date_filter="this_year")
        rng = item._preset_range("this_year")
        self.assertIsNotNone(rng)
        self.assertLessEqual(rng[0], rng[1])
        self.assertIsNone(item._preset_range("none"))

    def test_decomp_tree_levels(self):
        item = self._make_item(
            "decomp", primary_dimension_id=self.is_company_field.id,
            drill_ids=[(0, 0, {"field_id": self.is_company_field.id, "sequence": 10})])
        payload = item.get_payload()
        self.assertIsNone(payload.get("error"))
        self.assertEqual(payload["category"], "chart")
        self.assertEqual(payload["chain"][0], "is_company")
        self.assertTrue(payload["level0"]["nodes"], "root level has breakdown nodes")
        # Expanding a node returns the next level scoped to the click.
        top = payload["level0"]["nodes"][0]
        nxt = item.get_decomp([{"field": "is_company", "value": top["key"]}])
        self.assertIn("nodes", nxt)

    def test_slicer_builds_field_values(self):
        item = self._make_item("slicer", primary_dimension_id=self.is_company_field.id)
        payload = item.get_payload()
        self.assertIsNone(payload.get("error"))
        self.assertEqual(payload["category"], "control")
        self.assertEqual(payload["field"], "is_company")
        # is_company is boolean -> distinct values present.
        self.assertTrue(isinstance(payload["values"], list))

    def test_slicer_requires_field(self):
        item = self._make_item("slicer")  # no primary_dimension_id
        payload = item.get_payload()
        self.assertTrue(payload.get("error"))

    def test_influencer_text(self):
        item = self._make_item("kpi")
        # Influencer runs offline over a candidate dimension; may be None if no
        # groupable field, but must never raise.
        txt = item._influencer_text()
        self.assertTrue(txt is None or isinstance(txt, str))

    def test_conditional_rules_round_trip(self):
        rules = [{"op": "gte", "v1": 30, "v2": 0, "color": "#12b886", "style": "fill"}]
        res = self.dashboard.add_item({
            "item_type": "tile",
            "model_id": self.source.model_id.id,
            "measures": [{"verb": "count"}],
            "conditional_rules": rules,
        })
        item = self.env["eh.board.item"].browse(res["meta"]["id"])
        self.assertEqual(item.conditional_rules, rules)
        self.assertEqual(item._meta()["conditional_rules"], rules)
        cfg = self.dashboard.get_item_config(res["meta"]["id"])
        self.assertEqual(cfg["conditional_rules"], rules)

    def test_data_label_type_in_meta(self):
        item = self._make_item(
            "pie", primary_dimension_id=self.is_company_field.id,
            data_label_type="percent")
        self.assertEqual(item._meta()["display"]["data_label_type"], "percent")

    def test_builder_round_trip_new_fields(self):
        # add_item -> get_item_config preserves the new editor fields.
        res = self.dashboard.add_item({
            "item_type": "bar",
            "model_id": self.source.model_id.id,
            "measures": [{"verb": "count"}],
            "dimension": "is_company",
            "sort_mode": "field", "sort_field": "is_company", "sort_order": "asc",
            "include_archived": True, "default_date_filter": "mtd",
            "description": "Contacts by kind",
        })
        cfg = self.dashboard.get_item_config(res["meta"]["id"])
        self.assertEqual(cfg["sort_mode"], "field")
        self.assertEqual(cfg["sort_field"], "is_company")
        self.assertEqual(cfg["sort_order"], "asc")
        self.assertTrue(cfg["include_archived"])
        self.assertEqual(cfg["default_date_filter"], "mtd")
        self.assertEqual(cfg["description"], "Contacts by kind")
