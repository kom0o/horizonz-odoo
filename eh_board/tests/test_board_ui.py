# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Browser smoke test: the board client action mounts and renders widgets.

Run by Odoo's own headless Chrome, so any OWL mount, template or SVG error
surfaces as a deterministic failure with a console dump. The test builds its
own board and removes every other one, so it never depends on demo data.
"""
from odoo.tests import HttpCase, tagged


@tagged("eh_board", "post_install", "-at_install")
class TestBoardUI(HttpCase):

    def _seed_board(self):
        Dashboard = self.env["eh.board.dashboard"]
        Dashboard.search([]).unlink()
        Field = self.env["ir.model.fields"]
        partner_model = self.env["ir.model"]._get("res.partner")
        is_company = Field._get("res.partner", "is_company")
        country = Field._get("res.partner", "country_id")
        country_refs = ["base.au", "base.us", "base.de", "base.nz", "base.za", "base.sa"]
        countries = [self.env.ref(ref, raise_if_not_found=False) for ref in country_refs]
        countries = [record for record in countries if record]
        # Dense, long country labels are intentional: browser tour verifies
        # adaptive 65-degree category-axis layout, not only chart mounting.
        self.env["res.partner"].create([
            {"name": "Demo %s" % index, "is_company": index % 2 == 0,
             "country_id": country_record.id, "color": index * 10}
            for index, country_record in enumerate(countries, 1)
        ])
        source = self.env["eh.board.datasource"].create({
            "name": "Contacts", "provider_type": "orm", "model_id": partner_model.id})
        count = self.env["eh.board.measure"].create({
            "name": "Contacts", "datasource_id": source.id, "aggregate": "count"})
        goal = self.env["eh.board.measure"].create({
            "name": "Goal", "datasource_id": source.id, "aggregate": "count",
            "target_value": 8})
        avg_color = self.env["eh.board.measure"].create({
            "name": "Average colour", "datasource_id": source.id,
            "field_id": Field._get("res.partner", "color").id,
            "aggregate": "avg", "table_calculation": "percent_row"})
        dash = Dashboard.create({"name": "UI Test Board", "state": "published"})
        # Advanced source used by builder tour to prove edit-in-place UI. It is
        # board-owned, so picker exposes Edit beside New.
        self.env["eh.board.datasource"].create({
            "name": "Tour SQL",
            "provider_type": "sql",
            "dashboard_id": dash.id,
            "sql_query": "SELECT 'Tour' AS label, 1.0 AS value",
        })
        common = {"dashboard_id": dash.id, "datasource_id": source.id,
                  "measure_ids": [(6, 0, count.ids)]}
        Item = self.env["eh.board.item"]
        # The first widgets stay EAGER (index < 8) and near the top so the chart
        # tours find them. Fillers push the scatter past the eager cutoff and an
        # explicit grid parks it far below the fold, so it is genuinely deferred
        # and unloaded when the presentation tour presses Play.
        kpi = Item.create(dict(common, item_type="kpi", title="Total"))
        bar = Item.create(dict(common, item_type="bar", title="By company",
                               primary_dimension_id=is_company.id))
        pivot = Item.create(dict(common, item_type="pivot", title="Pivot company x country",
                                 measure_ids=[(6, 0, (count + avg_color).ids)],
                                 primary_dimension_id=is_company.id,
                                 secondary_dimension_id=country.id))
        column = Item.create(dict(common, item_type="column", title="Drill company to country",
                                  primary_dimension_id=is_company.id, click_action="drill",
                                  drill_ids=[(0, 0, {"field_id": country.id, "sequence": 10})]))
        polar = Item.create(dict(common, item_type="polar", title="Polar by company",
                                 primary_dimension_id=is_company.id))
        heatmap = Item.create(dict(common, item_type="heatmap", title="Heat company x country",
                                   primary_dimension_id=is_company.id,
                                   secondary_dimension_id=country.id))
        bullet = Item.create(dict(dashboard_id=dash.id, datasource_id=source.id,
                                  measure_ids=[(6, 0, goal.ids)], item_type="bullet",
                                  title="To target"))
        record_list = Item.create(dict(
            dashboard_id=dash.id, datasource_id=source.id,
            item_type="list", title="Contact details", list_mode="records",
            list_field_ids=[(6, 0, [Field._get("res.partner", "name").id,
                                     Field._get("res.partner", "country_id").id])],
            record_limit=20))
        # Fillers past the eager cutoff; the slicer (control) and decomp (tree)
        # exercise the isEmpty branches, and the scatter is LAST (a lazy chart).
        line = Item.create(dict(common, item_type="line", title="Line by company",
                                primary_dimension_id=is_company.id))
        funnel = Item.create(dict(common, item_type="funnel", title="Funnel by company",
                                  primary_dimension_id=is_company.id))
        radar = Item.create(dict(common, item_type="radar", title="Radar by company",
                                 primary_dimension_id=is_company.id))
        slicer = Item.create(dict(dashboard_id=dash.id, datasource_id=source.id,
                                  item_type="slicer", title="Filter by company",
                                  primary_dimension_id=is_company.id))
        decomp = Item.create(dict(common, item_type="decomp", title="Breakdown",
                                  primary_dimension_id=is_company.id,
                                  drill_ids=[(0, 0, {"field_id": country.id, "sequence": 10})]))
        scatter = Item.create(dict(common, item_type="scatter", title="Scatter by company",
                                   primary_dimension_id=is_company.id))
        order = [kpi, bar, pivot, column, polar, heatmap, bullet, record_list,
                 line, funnel, radar, slicer, decomp, scatter]
        grid = {}
        for i, it in enumerate(order):
            # Stack vertically; the scatter lands at y=40, far below any test
            # viewport, so its IntersectionObserver never fires before Play.
            grid[str(it.id)] = {"x": 0, "y": i * 4, "w": 6, "h": 4}
        self.env["eh.board.layout.version"].create({
            "dashboard_id": dash.id, "name": "Default",
            "is_active": True, "is_default": True, "grid": grid})
        self.env["eh.board.filter"].create({
            "dashboard_id": dash.id, "name": "Country",
            "filter_type": "field", "field_id": country.id})
        self.env.cr.flush()
        return dash

    def test_builder_tour(self):
        """Open a widget's Configure and assert the luxury builder shows the
        live preview, the Sort/Limit/Value-format depth, and the visual DOMAIN
        widget - deterministically, via a controlled tour."""
        self._seed_board()
        self.start_tour(
            "/web#action=eh_board.action_eh_board_open",
            "eh_board_builder_tour", login="admin", timeout=90)

    def test_filter_drill_tour(self):
        """Global field filter renders on the bar; clicking a bar drills into
        the filtered records list."""
        self._seed_board()
        self.start_tour(
            "/web#action=eh_board.action_eh_board_open",
            "eh_board_filter_drill_tour", login="admin", timeout=90)

    def test_edit_tools_tour(self):
        """Duplicate a widget and open the in-canvas Add-filter dialog."""
        self._seed_board()
        self.start_tour(
            "/web#action=eh_board.action_eh_board_open",
            "eh_board_edit_tools_tour", login="admin", timeout=90)

    def test_charts_tour(self):
        """The new chart types (polar, heat map, bullet) render."""
        self._seed_board()
        self.start_tour(
            "/web#action=eh_board.action_eh_board_open",
            "eh_board_charts_tour", login="admin", timeout=90)

    def test_template_tour(self):
        """The template gallery opens and renders the vertical packs."""
        self._seed_board()
        self.start_tour(
            "/web#action=eh_board.action_eh_board_open",
            "eh_board_template_tour", login="admin", timeout=90)

    def test_drill_tour(self):
        """Click a bar on a drill-enabled widget: it regroups a level deeper
        and shows a breadcrumb; clicking the root crumb climbs back."""
        self._seed_board()
        self.start_tour(
            "/web#action=eh_board.action_eh_board_open",
            "eh_board_drill_tour", login="admin", timeout=90)

    def test_crossfilter_tour(self):
        """Cross-filter mode: clicking a bar drops a board-wide filter chip."""
        self._seed_board()
        self.start_tour(
            "/web#action=eh_board.action_eh_board_open",
            "eh_board_crossfilter_tour", login="admin", timeout=90)

    def test_pivot_tour(self):
        """The pivot matrix renders as a real table with a grand-total cell."""
        self._seed_board()
        self.start_tour(
            "/web#action=eh_board.action_eh_board_open",
            "eh_board_pivot_tour", login="admin", timeout=90)

    def test_present_tour(self):
        """Presentation mode fetches a lazy, below-the-fold widget: jumping to
        the scatter slide resolves its loading skeleton instead of staying blank."""
        self._seed_board()
        self.start_tour(
            "/web#action=eh_board.action_eh_board_open",
            "eh_board_present_tour", login="admin", timeout=90)

    def test_xlsx_export(self):
        """Server-side Excel export returns a real workbook (zip magic + a
        sheet per widget), driven by the same numbers the board renders."""
        dash = self._seed_board()
        self.authenticate("admin", "admin")
        res = self.url_open("/eh_board/export/xlsx?dashboard_id=%d" % dash.id)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.content[:2], b"PK", "xlsx must be a zip container")
        self.assertIn("spreadsheetml", res.headers.get("Content-Type", ""))
        self.assertGreater(len(res.content), 500)

    def test_board_mounts(self):
        self._seed_board()
        self.browser_js(
            "/web#action=eh_board.action_eh_board_open",
            # code: the app mounted, at least one widget rendered, and a chart
            # produced SVG bars - proves the whole render path end to end.
            "const app = document.querySelector('.eh_board_app');"
            "const widgets = document.querySelectorAll('.eh_board_widget');"
            "const bars = document.querySelectorAll('.eh_board_bar');"
            "const kpi = document.querySelector('.eh_board_kpi_value');"
            "console.log((app && widgets.length >= 2 && bars.length > 0 && kpi)"
            " ? 'test successful' : 'eh_board rendered empty');",
            "!!document.querySelector('.eh_board_widget')",
            login="admin",
            timeout=90,
        )

    def test_native_settings_section_mounts(self):
        """General Settings stays native and exposes Dashboard Builder."""
        self.browser_js(
            "/web#action=base_setup.action_general_configuration",
            "const settings = document.querySelector('.o_form_view');"
            "console.log((settings && settings.innerText.includes('Dashboard Builder'))"
            " ? 'test successful' : 'Dashboard Builder missing from Settings');",
            "!!document.querySelector('.o_form_view')"
            " && document.querySelector('.o_form_view').innerText.includes('Dashboard Builder')",
            login="admin",
            timeout=90,
        )
