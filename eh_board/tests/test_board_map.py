# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Tests for the choropleth map item.

The guarantees under test: grouping by a country field yields ISO-coded regions
(the real choropleth the incumbent only fakes), and any other dimension degrades
cleanly to the ranked-bar fallback flag instead of erroring.
"""
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "eh_board")
class TestBoardMap(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Datasource = cls.env["eh.board.datasource"]
        cls.Measure = cls.env["eh.board.measure"]
        cls.Item = cls.env["eh.board.item"]
        cls.Dashboard = cls.env["eh.board.dashboard"]

        au = cls.env.ref("base.au")
        us = cls.env.ref("base.us")
        cls.partners = cls.env["res.partner"].create([
            {"name": "P-AU-1", "country_id": au.id},
            {"name": "P-AU-2", "country_id": au.id},
            {"name": "P-US-1", "country_id": us.id},
            {"name": "P-NO", "company_type": "company"},
        ])
        partner_model = cls.env["ir.model"]._get("res.partner")
        cls.source = cls.Datasource.create({
            "name": "Partners", "provider_type": "orm",
            "model_id": partner_model.id,
            "domain": "[('id', 'in', %s)]" % cls.partners.ids})
        cls.measure = cls.Measure.create({
            "name": "Records", "datasource_id": cls.source.id, "aggregate": "count"})
        cls.dash = cls.Dashboard.create({"name": "Map board"})

    def _map_item(self, field_name):
        field = self.env["ir.model.fields"]._get("res.partner", field_name)
        return self.Item.create({
            "dashboard_id": self.dash.id, "item_type": "map", "title": "Map",
            "datasource_id": self.source.id,
            "measure_ids": [(6, 0, self.measure.ids)],
            "primary_dimension_id": field.id})

    def test_country_dim_yields_regions(self):
        item = self._map_item("country_id")
        payload = item.get_payload({})
        self.assertFalse(payload.get("error"), payload.get("error"))
        self.assertFalse(payload.get("degrade"))
        codes = {r["code"]: r["value"] for r in payload.get("regions", [])}
        self.assertEqual(codes.get("AU"), 2.0)
        self.assertEqual(codes.get("US"), 1.0)

    def test_non_country_dim_degrades(self):
        # is_company is stored (company_type is computed and would be rejected).
        item = self._map_item("is_company")
        payload = item.get_payload({})
        self.assertFalse(payload.get("error"), payload.get("error"))
        # Not a country field -> degrade flag set, no regions; the client draws
        # the ranked-bar fallback from labels/series.
        self.assertTrue(payload.get("degrade"))
        self.assertFalse(payload.get("regions"))
        self.assertTrue(payload.get("labels"))
