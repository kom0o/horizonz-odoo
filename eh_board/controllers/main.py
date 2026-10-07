# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""HTTP endpoints for server-side exports.

The Excel export is real: a workbook with a sheet per widget (headers +
grouped rows, or a single value for a KPI), built from the same payloads the
board renders - so the numbers match to the cell. No screenshot rasterising.
"""
import io
import json
import csv

from werkzeug.exceptions import BadRequest

from odoo import http, _
from odoo.http import request, content_disposition


class EhBoardController(http.Controller):

    def _export_context(self, dashboard_id, options):
        try:
            did = int(dashboard_id)
            if len(options or "{}") > 100000:
                raise ValueError()
            opts = json.loads(options or "{}")
        except (ValueError, TypeError):
            raise BadRequest("Invalid dashboard export request.")
        dashboard = request.env["eh.board.dashboard"].browse(did).exists()
        if not dashboard:
            return dashboard, {}
        return dashboard, dashboard._analysis_options(opts)

    @http.route("/eh_board/export/pdf", type="http", auth="user")
    def export_pdf(self, dashboard_id=None, options="{}", **kw):
        dashboard, opts = self._export_context(dashboard_id, options)
        if not dashboard:
            return request.not_found()
        report = request.env.ref("eh_board.action_report_eh_board_dashboard").with_context(
            eh_board_options=opts)
        content, _kind = report._render_qweb_pdf(report.report_name, dashboard.ids)
        return request.make_response(content, headers=[
            ("Content-Type", "application/pdf"),
            ("Content-Disposition", content_disposition("%s.pdf" % dashboard.name)),
        ])

    @http.route("/eh_board/export/csv", type="http", auth="user")
    def export_csv(self, dashboard_id=None, options="{}", **kw):
        dashboard, opts = self._export_context(dashboard_id, options)
        if not dashboard:
            return request.not_found()
        data = dashboard.get_export_data(opts)
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)

        def write(values):
            writer.writerow([self._csv_value(value) for value in values])

        write([_("Dashboard"), data["name"]])
        write([_("Scope"), self._scope_text(data["scope"])])
        for payload in data["items"]:
            if payload.get("category") == "content":
                continue
            write([])
            write([payload.get("title") or payload.get("type")])
            if payload.get("error"):
                write([_("Error"), payload["error"]])
                continue
            if payload.get("warning"):
                write([_("Warning"), payload["warning"]])
            if (payload.get("source_status") or {}).get("last_success"):
                write([_("Last successful refresh"), payload["source_status"]["last_success"], "UTC"])
            if (payload.get("currency") or {}).get("code"):
                write([_("Currency"), payload["currency"]["code"]])
            if "value" in payload:
                write([_("Value"), payload["value"]])
                continue
            table = dashboard._payload_table(payload)
            write([col.get("label") or _("Value") for col in table.get("columns", [])])
            for row in table.get("rows", []):
                write(row)
        return request.make_response(stream.getvalue().encode("utf-8-sig"), headers=[
            ("Content-Type", "text/csv; charset=utf-8"),
            ("Content-Disposition", content_disposition("%s.csv" % dashboard.name)),
        ])

    @staticmethod
    def _csv_value(value):
        if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r", "\n"):
            return "'" + value
        return "" if value is None else value

    @staticmethod
    def _scope_text(scope):
        return scope.get("label") or ""

    @http.route("/eh_board/export/xlsx", type="http", auth="user")
    def export_xlsx(self, dashboard_id=None, item_id=None, options="{}", **kw):
        try:
            import xlsxwriter
        except ImportError:
            return request.not_found()
        dashboard, opts = self._export_context(dashboard_id, options)
        if not dashboard:
            return request.not_found()
        data = dashboard.get_export_data(opts)

        stream = io.BytesIO()
        book = xlsxwriter.Workbook(stream, {
            "in_memory": True, "strings_to_formulas": False, "strings_to_urls": False,
        })
        f_title = book.add_format({"bold": True, "font_size": 13, "font_color": "#14181a"})
        f_head = book.add_format({"bold": True, "bg_color": "#eef1f2", "border": 1})
        f_num = book.add_format({"num_format": "#,##0.###", "border": 1})
        f_pct = book.add_format({"num_format": "0.0%", "border": 1})
        f_txt = book.add_format({"border": 1})

        meta_by_id = {m["id"]: m for m in data.get("item_meta", [])}
        used_names = set()
        for payload in data.get("items", []):
            meta = meta_by_id.get(payload.get("id"), {})
            title = (meta.get("title") or payload.get("type") or "Widget")
            name = self._safe_sheet(title, used_names)
            sheet = book.add_worksheet(name)
            sheet.set_column(0, 0, 32)
            sheet.write(0, 0, title, f_title)
            sheet.write_string(1, 0, self._scope_text(data["scope"]))
            if payload.get("warning"):
                sheet.write_string(1, 1, payload["warning"])
            status = payload.get("source_status") or {}
            if status.get("last_success"):
                sheet.write_string(1, 2, _("Last successful refresh: %s UTC", status["last_success"]))
            if (payload.get("currency") or {}).get("code"):
                sheet.write_string(1, 3, payload["currency"]["code"])
            if payload.get("error"):
                sheet.write_string(2, 0, payload["error"], f_txt)
                continue
            if payload.get("category") == "kpi":
                sheet.write(2, 0, "Value", f_head)
                sheet.write(2, 1, payload.get("value", 0), f_num)
            elif payload.get("category") == "content":
                continue
            else:
                table = dashboard._payload_table(payload)
                for c, column in enumerate(table.get("columns", [])):
                    sheet.set_column(c, c, 32 if c == 0 else 16)
                    sheet.write(2, c, str(column.get("label") or "Value"), f_head)
                for r, row in enumerate(table.get("rows", [])):
                    for c, value in enumerate(row):
                        column = table["columns"][c]
                        if column.get("percentage"):
                            sheet.write_number(3 + r, c, float(value or 0), f_pct)
                        elif column.get("numeric") and not isinstance(value, bool):
                            sheet.write_number(3 + r, c, float(value or 0), f_num)
                        else:
                            sheet.write(3 + r, c,
                                        "" if value is None else str(value), f_txt)

        if not book.worksheets():
            book.add_worksheet("Dashboard").write(0, 0, data.get("name", "Dashboard"))
        book.close()
        content = stream.getvalue()
        filename = "%s.xlsx" % (data.get("name") or "dashboard")
        return request.make_response(content, headers=[
            ("Content-Type",
             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            ("Content-Disposition", content_disposition(filename)),
            ("Content-Length", len(content)),
        ])

    def _safe_sheet(self, name, used):
        clean = "".join(c for c in name if c not in "[]:*?/\\")[:28] or "Sheet"
        # xlsxwriter dedups sheet names case-INSENSITIVELY and raises
        # DuplicateWorksheetName (a 500) on a collision. Track the lower-cased
        # name so two widgets differing only in case get distinct sheets.
        base, i = clean, 1
        while clean.lower() in used:
            i += 1
            clean = "%s %d" % (base[:25], i)
        used.add(clean.lower())
        return clean
