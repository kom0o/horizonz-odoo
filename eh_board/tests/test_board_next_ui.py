# -*- coding: utf-8 -*-
# Copyright (C) 2026 ERP Heritage.
"""Real OWL mounts and authenticated exports for the new dashboard flows.

The catalogue fixture uses Contacts so the browser path runs on a base-only
installation. It still goes through the native availability checks, rollback
preview, metric creation and renderer. Production business semantics have
separate Sales/Accounting/Inventory tests. No external provider is contacted.
"""
import csv
import io
import json
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode
from xml.etree import ElementTree
from zipfile import ZipFile

from odoo.tests import HttpCase, tagged

from ..lib.business_metrics import METRICS, PACKS


@tagged("eh_board", "eh_board_next_ui", "post_install", "-at_install")
class TestBoardNextUI(HttpCase):
    def _seed_board(self, export=False):
        Dashboard = self.env["eh.board.dashboard"]
        Dashboard.search([]).unlink()
        board = Dashboard.create({"name": "Next browser fixture", "state": "published",
                                  "refresh_mode": "off"})
        country = self.env["ir.model.fields"]._get("res.partner", "country_id")
        company = self.env["ir.model.fields"]._get("res.partner", "is_company")
        partners = self.env["res.partner"].create([
            {"name": "Next browser A", "color": 10, "is_company": True,
             "country_id": self.env.ref("base.au").id, "company_id": self.env.company.id},
            {"name": "Next browser B", "color": 20, "is_company": False,
             "country_id": self.env.ref("base.au").id, "company_id": self.env.company.id},
            {"name": "Next browser C", "color": 90, "is_company": True,
             "country_id": self.env.ref("base.us").id, "company_id": self.env.company.id},
        ])
        source = self.env["eh.board.datasource"].create({
            "name": "Next browser contacts", "dashboard_id": board.id,
            "provider_type": "orm", "model_id": self.env["ir.model"]._get("res.partner").id,
            "domain": repr([("id", "in", partners.ids)]),
        })
        measure = self.env["eh.board.measure"].create({
            "name": "Amount" if export else "Contacts", "datasource_id": source.id,
            "aggregate": "sum" if export else "count",
            "field_id": self.env["ir.model.fields"]._get("res.partner", "color").id if export else False,
        })
        kpi = self.env["eh.board.item"].create({
            "title": "Scoped amount", "dashboard_id": board.id, "datasource_id": source.id,
            "item_type": "kpi", "measure_ids": [(6, 0, measure.ids)],
        })
        drill = self.env["eh.board.item"]
        if export:
            drill = kpi.copy({"title": "Drilled amount", "item_type": "bar",
                              "primary_dimension_id": country.id,
                              "drill_ids": [(0, 0, {"field_id": company.id})]})
            for index in range(9):
                kpi.copy({"title": "Deferred amount %s" % index})
        self.env.cr.flush()
        return board, partners, drill

    def _browser_check(self, scenario):
        script = (Path(__file__).resolve().parents[1] / "static/tests/next_tour.js").read_text()
        self.browser_js(
            "/web#action=eh_board.action_eh_board_open",
            script + "\nwindow.ehBoardNextTour(%s).catch((error) => console.error(error));" % json.dumps(scenario),
            "!!document.querySelector('.eh_board_app .eh_board_widget')",
            login="admin", timeout=100,
        )

    def test_business_pack_preview_and_create_mount(self):
        board, partners, _drill = self._seed_board()
        definition = {
            "title": "Browser contacts", "model": "res.partner", "module": "base",
            "aggregate": "count", "field": None, "date_field": None,
            "domain": [("id", "in", partners.ids)], "dimensions": ["country_id"],
            "definition": "Count only the three browser fixture contacts in the current company.",
        }
        pack = {
            "name": "Browser fixture pack", "category": "general", "module": "base", "preset": "all",
            "description": "A controlled contact count and country breakdown for the browser test.",
            "widgets": [("test.browser_contacts.v1", "kpi", None),
                        ("test.browser_contacts.v1", "hbar", "country_id")],
        }
        with patch.dict(METRICS, {"test.browser_contacts.v1": definition}), \
                patch.dict(PACKS, {"test.browser.v1": pack}):
            self._browser_check("gallery")
            created = self.env["eh.board.dashboard"].search([("name", "=", pack["name"])])
            self.assertEqual(len(created), 1, "Preview must not leave an extra dashboard")
            self.assertEqual(created.state, "draft")
            self.assertFalse(created.shared_user_ids)
            self.assertFalse(created.group_ids)
            self.assertEqual(created.company_ids, self.env.company)
            self.assertEqual(len(created.item_ids), 2)
            self.assertEqual(created.item_ids[:1].get_payload({})["value"], 3)
            self.assertEqual(board.state, "published")
            self.assertEqual(len(board.item_ids), 1)

    def test_ai_off_and_private_remote_setup_mount_without_network(self):
        board, _partners, _drill = self._seed_board()
        self.env["ir.config_parameter"].sudo().set_param("eh_board.ai_provider", "off")
        sources_before = self.env["eh.board.datasource"].search_count([])
        with patch.object(type(self.env["eh.board.ai"]), "_call_llm") as provider, \
                patch.object(type(self.env["eh.board.datasource"]), "_fetch_remote") as remote:
            self._browser_check("setup")
            provider.assert_not_called()
            remote.assert_not_called()
        self.assertEqual(self.env["eh.board.datasource"].search_count([]), sources_before)
        self.assertEqual(len(board.item_ids), 1)

    def test_ai_enabled_proposal_refine_and_apply_mount(self):
        """Exercise real RPC validation/preview/apply with a stubbed provider."""
        board, partners, _drill = self._seed_board()
        metric_id = "test.browser_contacts.v1"
        definition = {
            "title": "Browser contacts", "model": "res.partner", "module": "base",
            "aggregate": "count", "field": None, "date_field": None,
            "domain": [("id", "in", partners.ids)], "dimensions": ["country_id"],
            "definition": "Count only the three browser fixture contacts in the current company.",
        }
        kpi = {"id": "contacts", "metric_id": metric_id, "title": "Initial AI contacts",
               "item_type": "kpi", "dimension": "", "date_preset": "none", "granularity": "month"}
        first = {"version": 1, "items": [kpi], "assumptions": ["Fixture contacts only."],
                 "unavailable": ["No sales target was requested or supplied."]}
        refined = {"version": 1, "items": [
            dict(kpi, title="Refined AI contacts"),
            dict(kpi, id="countries", title="AI contacts by country", item_type="hbar", dimension="country_id"),
        ], "assumptions": ["Fixture contacts only."], "unavailable": []}
        admin = self.env.ref("base.user_admin")
        config = self.env["ir.config_parameter"].sudo()
        config.set_param("eh_board.ai_authoring_daily_requests", "20")
        config.set_param("eh_board.authoring_usage.%s" % admin.id, "{}")
        with patch.dict(METRICS, {metric_id: definition}), \
                patch.object(type(self.env["eh.board.ai"]), "ai_available", return_value=True), \
                patch.object(type(self.env["eh.board.ai"]), "_call_llm",
                             side_effect=[json.dumps(first), json.dumps(refined), json.dumps(refined)]) as provider:
            self._browser_check("authoring")
            self.assertEqual(provider.call_count, 3, "Only generation and explicit refinement may call the provider")
            initial_request = json.loads(provider.call_args_list[0].args[1])
            refinement_request = json.loads(provider.call_args_list[1].args[1])
            self.assertFalse(initial_request["existing_proposal"])
            self.assertEqual(refinement_request["existing_proposal"]["items"][0]["title"], "Initial AI contacts")
            self.assertEqual(refinement_request["request"], "Keep the contact count and add a country breakdown.")
            restored_request = json.loads(provider.call_args_list[2].args[1])
            self.assertEqual(restored_request["existing_proposal"]["items"][0]["title"], "Reviewed AI contacts")
            self.assertTrue(provider.call_args_list[0].kwargs["json_mode"])
            items = self.env["eh.board.item"].search([("dashboard_id", "=", board.id)])
            self.assertEqual(len(items), 2, "Preview/refinement must not persist items, and only the selected item is applied")
            created = items.filtered(lambda item: item.business_metric_id == metric_id)
            self.assertEqual(len(created), 1)
            self.assertEqual(created.title, "Reviewed AI contacts")
            self.assertEqual(created.item_type, "kpi")
            self.assertEqual(created.get_payload({})["value"], 3)
            self.assertFalse(created.measure_ids.target_value)
            self.assertTrue(items.filtered(lambda item: item.title == "Scoped amount"), "Existing widget must remain")
            self.assertEqual(board.state, "published")

    def _export_options(self, drill):
        return {"company_ids": self.env.company.ids,
                "filters": [{"field": "is_company", "model": "res.partner", "values": [True]}],
                "drill_paths": {str(drill.id): [
                    {"field": "country_id", "value": self.env.ref("base.au").id, "label": "Australia"}]}}

    def _get_export(self, kind, board, options):
        return self.url_open("/eh_board/export/%s?%s" % (
            kind, urlencode({"dashboard_id": board.id, "options": json.dumps(options)})))

    @staticmethod
    def _xlsx_rows(content):
        """Read cells without an optional spreadsheet-library dependency."""
        ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        with ZipFile(io.BytesIO(content)) as archive:
            strings = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
            shared = ["".join(node.itertext()) for node in strings.findall("s:si", ns)]
            workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
            result = {}
            for index, sheet in enumerate(workbook.findall("s:sheets/s:sheet", ns), 1):
                root = ElementTree.fromstring(archive.read("xl/worksheets/sheet%s.xml" % index))
                cells = {}
                for cell in root.findall(".//s:c", ns):
                    value = cell.find("s:v", ns)
                    value = value.text if value is not None else ""
                    cells[cell.attrib["r"]] = shared[int(value)] if cell.attrib.get("t") == "s" else value
                result[sheet.attrib["name"]] = cells
            return result

    def test_csv_and_xlsx_preserve_filters_drills_and_all_deferred_items(self):
        board, _partners, drill = self._seed_board(export=True)
        options = self._export_options(drill)
        self.assertTrue(board.get_data(lazy=True)["lazy_ids"])
        self.authenticate("admin", "admin")
        response = self._get_export("csv", board, options)
        self.assertEqual(response.status_code, 200)
        rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))
        for item in board.item_ids.filtered(lambda item: item != drill):
            offset = rows.index([item.title])
            self.assertEqual(rows[offset + 1][0], "Value")
            self.assertEqual(float(rows[offset + 1][1]), 100)
        offset = rows.index([drill.title])
        self.assertEqual(float(rows[offset + 2][-1]), 10)
        self.assertIn("Drilled view", rows[1][1])
        response = self._get_export("xlsx", board, options)
        self.assertEqual(response.status_code, 200)
        self.assertIn("spreadsheetml", response.headers.get("Content-Type", ""))
        sheets = self._xlsx_rows(response.content)
        self.assertEqual(len(sheets), 11)
        for item in board.item_ids.filtered(lambda item: item != drill):
            self.assertEqual(float(sheets[item.title]["B3"]), 100)
        self.assertEqual(float(sheets[drill.title]["B4"]), 10)
        self.assertNotIn("B5", sheets[drill.title], "Drilling must retain the active company-type filter")
        self.assertIn("Drilled view", sheets[drill.title]["A2"])

    def test_pdf_http_uses_same_scope_and_real_qweb_for_deferred_widgets(self):
        board, _partners, drill = self._seed_board(export=True)
        options = self._export_options(drill)
        self.authenticate("admin", "admin")
        captured = []

        def render(report, report_ref, res_ids=None, data=None):
            # Exercise the actual QWeb/report data boundary. Only the external
            # wkhtmltopdf binary is substituted, not the template or aggregates.
            docs = report.env["eh.board.dashboard"].browse(res_ids)
            captured.append({"uid": report.env.uid, "options": report.env.context.get("eh_board_options"),
                             "blocks": docs._report_data()})
            html, _kind = report._render_qweb_html(report_ref, res_ids, data=data)
            return b"%PDF-1.4\n" + html, "pdf"

        with patch.object(type(self.env["ir.actions.report"]), "_render_qweb_pdf", render):
            response = self._get_export("pdf", board, options)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("Content-Type"), "application/pdf")
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]["uid"], self.env.ref("base.user_admin").id)
        self.assertEqual(captured[0]["options"]["drill_paths"], options["drill_paths"])
        blocks = {block["title"]: block for block in captured[0]["blocks"]}
        self.assertEqual(len(blocks), 11)
        self.assertEqual(blocks["Deferred amount 8"]["value"], "100")
        self.assertEqual(blocks[drill.title]["rows"][0][-1], "10")
        self.assertEqual(len(blocks[drill.title]["rows"]), 1)
        self.assertIn(b"Deferred amount 8", response.content)
        self.assertIn(b"Drilled view", response.content)
