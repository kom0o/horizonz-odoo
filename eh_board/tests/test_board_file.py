# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Tests for the file (CSV / Excel) data source.

The guarantees under test: parsing infers column types and caps size; an item
aggregates file columns through the unchanged spec contract; a renamed/removed
column degrades to a clear message instead of crashing; and NO ir.model or
physical table is ever created (the anti-incumbent design).
"""
import base64
import math

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.eh_board.lib import tabular

CSV = (
    b"Country,Team,Sales,Signed\n"
    b"Australia,West,1200,2026-01-05\n"
    b"Australia,East,800,2026-02-11\n"
    b"United States,West,2000,2026-01-20\n"
    b"United States,East,1500,2026-03-02\n"
    b"Australia,West,300,2026-01-30\n"
)


@tagged("post_install", "-at_install", "eh_board")
class TestBoardFile(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Datasource = cls.env["eh.board.datasource"]
        cls.Measure = cls.env["eh.board.measure"]
        cls.Item = cls.env["eh.board.item"]
        cls.Dashboard = cls.env["eh.board.dashboard"]

    def _make_source(self, data=CSV, name="sales.csv"):
        src = self.Datasource.create({
            "name": "Sales file", "provider_type": "file",
            "file_name": name, "file_data": base64.b64encode(data)})
        src.action_parse_file()
        return src

    # -- pure parser ---------------------------------------------------------
    def test_parse_infers_types(self):
        parsed = tabular.parse_csv(CSV)
        dtypes = {c["name"]: c["dtype"] for c in parsed["columns"]}
        self.assertEqual(dtypes["country"], "text")
        self.assertEqual(dtypes["sales"], "number")
        self.assertEqual(dtypes["signed"], "date")
        self.assertEqual(parsed["row_count"], 5)

    def test_parse_bad_file_raises(self):
        with self.assertRaises(tabular.TabularError):
            tabular.parse_csv(b"")

    def test_non_finite_never_aggregates_to_nan(self):
        # inf / nan / overflow cells must be rejected at parse so an aggregate can
        # never become NaN/Infinity (which would break the whole board's JSON).
        data = b"Team,Amount\nWest,100\nEast,inf\nNorth,NaN\nSouth,1e400\n"
        parsed = tabular.parse_csv(data)
        res = tabular.aggregate_records(
            parsed["rows"],
            [{"field": "team", "dtype": "text"}],
            [{"key": "m", "field": "amount", "verb": "sum"}])
        for r in res["rows"]:
            v = r["values"]["m"]
            self.assertTrue(math.isfinite(v), "aggregate stayed finite for %s" % r["labels"])

    def test_binary_flag_column_is_number(self):
        # A 0/1 flag column must infer as number (so it sums), not boolean.
        parsed = tabular.parse_csv(b"Rep,Paid\nA,1\nB,0\nC,1\n")
        dtypes = {c["name"]: c["dtype"] for c in parsed["columns"]}
        self.assertEqual(dtypes["paid"], "number")
        res = tabular.aggregate_records(
            parsed["rows"], [], [{"key": "m", "field": "paid", "verb": "sum"}])
        self.assertEqual(res["rows"][0]["values"]["m"], 2.0)

    # -- column registry, not ir.model --------------------------------------
    def test_parse_builds_columns_no_model(self):
        before = self.env["ir.model"].search_count([])
        src = self._make_source()
        self.assertEqual(len(src.column_ids), 4)
        self.assertEqual(src.row_count, 5)
        # The anti-incumbent guarantee: no dynamic model was created.
        self.assertEqual(self.env["ir.model"].search_count([]), before)

    def test_reupload_rebuilds_columns(self):
        src = self._make_source()
        first_ids = set(src.column_ids.ids)
        src.write({"file_data": base64.b64encode(
            b"Region,Amount\nAPAC,10\nEMEA,20\n")})
        src.action_parse_file()
        self.assertEqual(src.column_ids.mapped("name"), ["region", "amount"])
        # Old columns were removed (rebuilt), not accumulated.
        self.assertFalse(first_ids & set(src.column_ids.ids))

    def test_parse_requires_file(self):
        src = self.Datasource.create({
            "name": "Empty", "provider_type": "file"})
        with self.assertRaises(UserError):
            src.action_parse_file()

    # -- aggregation through the spec contract ------------------------------
    def _item_on(self, src, group_col, measure_col=None, verb="sum"):
        col = src.column_ids.filtered(lambda c: c.name == group_col)
        mvals = {"name": "M", "datasource_id": src.id, "aggregate": verb}
        if measure_col:
            mcol = src.column_ids.filtered(lambda c: c.name == measure_col)
            mvals["column_id"] = mcol.id
        measure = self.Measure.create(mvals)
        dash = self.Dashboard.create({"name": "F"})
        return self.Item.create({
            "dashboard_id": dash.id, "item_type": "bar", "title": "By " + group_col,
            "datasource_id": src.id, "measure_ids": [(6, 0, measure.ids)],
            "primary_column_id": col.id})

    def test_item_aggregates_file_column(self):
        src = self._make_source()
        item = self._item_on(src, "country", "sales", "sum")
        payload = item.get_payload({})
        self.assertFalse(payload.get("error"), payload.get("error"))
        # Map label -> first-series value.
        vals = dict(zip(payload["labels"], payload["series"][0]["data"]))
        self.assertEqual(vals["Australia"], 2300.0)
        self.assertEqual(vals["United States"], 3500.0)

    def test_item_count_verb(self):
        src = self._make_source()
        item = self._item_on(src, "team", None, "count")
        payload = item.get_payload({})
        vals = dict(zip(payload["labels"], payload["series"][0]["data"]))
        self.assertEqual(vals["West"], 3.0)
        self.assertEqual(vals["East"], 2.0)

    def test_reupload_preserves_column_identity(self):
        # A re-upload of the same-shape file keeps the widget working: the
        # column rows are matched by name, so the item's references survive.
        src = self._make_source()
        item = self._item_on(src, "country", "sales", "sum")
        country_col = item.primary_column_id
        src.write({"file_data": base64.b64encode(
            b"Country,Team,Sales,Signed\nAustralia,West,999,2026-01-01\n")})
        src.action_parse_file()
        self.assertTrue(item.primary_column_id, "group-by column should survive")
        self.assertEqual(item.primary_column_id, country_col)
        payload = item.get_payload({})
        self.assertFalse(payload.get("error"), payload.get("error"))

    def test_dropped_group_column_degrades(self):
        src = self._make_source()
        item = self._item_on(src, "country", "sales", "sum")
        # Re-upload WITHOUT the group-by column: its row is removed, the item's
        # reference is set null, and it degrades to a clear message (no crash).
        src.write({"file_data": base64.b64encode(
            b"Team,Sales\nWest,10\nEast,20\n")})
        src.action_parse_file()
        self.assertFalse(item.primary_column_id)
        payload = item.get_payload({})
        self.assertIn("column", (payload.get("error") or "").lower())

    def test_validate_messages(self):
        src = self.Datasource.create({
            "name": "NoFile", "provider_type": "file"})
        dash = self.Dashboard.create({"name": "V"})
        item = self.Item.create({
            "dashboard_id": dash.id, "item_type": "bar",
            "datasource_id": src.id})
        # An unconfigured file item explains itself inline (no upload, no columns).
        payload = item.get_payload({})
        self.assertIn("Upload", payload.get("error") or "")
