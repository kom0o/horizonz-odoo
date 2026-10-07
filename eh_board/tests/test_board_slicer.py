# -*- encoding: utf-8 -*-
"""Compact slicer options survive builder edits and portable dashboard backups."""
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "eh_board")
class TestBoardSlicer(TransactionCase):

    def test_layout_round_trip(self):
        dashboard = self.env["eh.board.dashboard"].create({"name": "Compact slicers"})
        item = dashboard._create_item_from_builder({
            "item_type": "slicer", "title": "Company selector",
            "model_id": self.env["ir.model"]._get("res.partner").id,
            "dimension": "is_company", "chart_options": {"slicer_display": "list"},
        })
        self.assertEqual(item.chart_options["slicer_display"], "list")
        self.assertEqual(dashboard.get_item_config(item.id)["chart_options"]["slicer_display"], "list")
        exported = dashboard.export_definition()
        imported = self.env["eh.board.dashboard"].import_definition(exported)
        restored = self.env["eh.board.dashboard"].browse(imported["dashboard_id"])
        self.assertEqual(restored.item_ids.chart_options["slicer_display"], "list")

    def test_invalid_layouts_fall_back_without_losing_colors(self):
        dashboard = self.env["eh.board.dashboard"].create({"name": "Slicer validation"})
        item = self.env["eh.board.item"].create({
            "dashboard_id": dashboard.id, "item_type": "richtext", "content": "Test",
        })
        for mode in ("auto", "list", "chips", "invalid", {}, [], None, 4):
            item.chart_options = {"slicer_display": mode, "series_colors": ["#AABBCC"], "unknown": 1}
            expected = mode if mode in ("auto", "list", "chips") else "auto"
            self.assertEqual(item.chart_options, {
                "slicer_display": expected, "series_colors": ["#aabbcc"],
            })
