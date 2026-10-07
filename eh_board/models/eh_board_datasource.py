# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
import ast
import base64
import gzip
import json

from odoo import api, fields, models, SUPERUSER_ID
from odoo.exceptions import UserError, ValidationError

from ..lib.registry import datasource_selection, get_datasource
from ..lib import tabular


class EhBoardDataSource(models.Model):
    _name = "eh.board.datasource"
    _description = "Dashboard Data Source"
    _order = "name"
    _MAX_FILE_BYTES = 20 * 1024 * 1024

    name = fields.Char(required=True, default="Data Source")
    dashboard_id = fields.Many2one(
        "eh.board.dashboard", string="Dashboard", ondelete="cascade", index=True,
        help="Owning dashboard for sources created by the visual builder.")
    item_ids = fields.One2many("eh.board.item", "datasource_id", string="Widgets")
    provider_type = fields.Selection(
        selection=lambda self: datasource_selection(),
        required=True, default="orm",
        help="Where the numbers come from. The free engine ships the Odoo-model "
             "provider; joins, safe SQL and external feeds register alongside it.",
    )
    model_id = fields.Many2one(
        "ir.model", string="Model", ondelete="cascade",
        help="The Odoo model to aggregate (for the Odoo-model provider).",
    )
    model_name = fields.Char(
        related="model_id.model", store=True, readonly=True, string="Model Technical Name")
    domain = fields.Char(
        default="[]",
        help="A static filter applied before any runtime dashboard filter. "
             "A plain domain literal - never an evaluated expression.",
    )
    read_only = fields.Boolean(default=True, readonly=True)
    config = fields.Json(default=lambda self: {})
    # ---- safe SQL (provider_type == 'sql') ----
    sql_query = fields.Text(
        string="SQL query",
        groups="eh_board.group_board_admin",
        help="A single read-only SELECT. First column is the category label; "
             "the remaining numeric columns become measures. Dashboard "
             "Administrator only: other users never receive query text.")
    credential_id = fields.Many2one(
        "eh.board.credential", string="Credential",
        help="A vaulted credential for an external source (never inlined).")
    measure_ids = fields.One2many(
        "eh.board.measure", "datasource_id", string="Measures")
    active = fields.Boolean(default=True)

    # ---- cross-model join (provider_type == 'join') ----
    _AGG = [("count", "Count"), ("sum", "Sum"), ("avg", "Average"),
            ("min", "Minimum"), ("max", "Maximum")]
    join_left_model_id = fields.Many2one("ir.model", string="Left model", ondelete="cascade")
    join_left_key = fields.Char(string="Left group field", help="Field to group the left model by; its value is the join key.")
    join_left_agg = fields.Selection(_AGG, string="Left measure", default="count")
    join_left_value = fields.Char(string="Left value field", help="Numeric field to aggregate (blank for a record count).")
    join_left_label = fields.Char(string="Left label", default="Left")
    join_right_model_id = fields.Many2one("ir.model", string="Right model", ondelete="cascade")
    join_right_key = fields.Char(string="Right group field")
    join_right_agg = fields.Selection(_AGG, string="Right measure", default="count")
    join_right_value = fields.Char(string="Right value field")
    join_right_label = fields.Char(string="Right label", default="Right")

    # ---- file (provider_type == 'file') ----
    # Stored as an attachment (not a raw DB column) so a large upload never
    # bloats the row; the parsed rows live in a separate cache attachment.
    # Builder/Admin only: the raw uploaded blob must not be readable by every
    # Viewer across the database. Viewers render file-based widgets from the
    # sudo-cached parsed rows (tabular_rows), never the blob itself.
    file_data = fields.Binary(
        string="Data file", attachment=True,
        groups="eh_board.group_board_builder")
    file_name = fields.Char(string="File name")
    file_kind = fields.Selection(
        [("csv", "CSV / text"), ("xlsx", "Excel (.xlsx)")],
        string="File type", compute="_compute_file_kind", store=True, readonly=False)
    column_ids = fields.One2many(
        "eh.board.source.column", "datasource_id", string="Columns")
    row_count = fields.Integer(string="Rows", readonly=True)
    truncated = fields.Boolean(string="Truncated", readonly=True)

    @api.depends("file_name")
    def _compute_file_kind(self):
        for rec in self:
            name = (rec.file_name or "").lower()
            if name.endswith((".xlsx", ".xlsm")):
                rec.file_kind = "xlsx"
            elif name.endswith((".csv", ".tsv", ".txt")):
                rec.file_kind = "csv"
            elif not rec.file_kind:
                rec.file_kind = "csv"

    # -- file parsing + row cache ------------------------------------------
    _CACHE_XMLKEY = "eh_board.tabular_cache"

    def _cache_attachment(self):
        self.ensure_one()
        return self.env["ir.attachment"].sudo().search([
            ("res_model", "=", self._name), ("res_id", "=", self.id),
            ("res_field", "=", "eh_board_tabular_cache")], limit=1)

    def _store_rows_cache(self, rows):
        """Persist parsed rows as one gzipped-JSON attachment (not a table)."""
        self.ensure_one()
        blob = base64.b64encode(gzip.compress(
            json.dumps(rows).encode("utf-8")))
        att = self._cache_attachment()
        vals = {"datas": blob, "name": "eh_board_rows_%s.json.gz" % self.id}
        if att:
            att.write(vals)
        else:
            self.env["ir.attachment"].sudo().create({
                "res_model": self._name, "res_id": self.id,
                "res_field": "eh_board_tabular_cache", "type": "binary",
                **vals})

    def _load_rows_cache(self):
        self.ensure_one()
        att = self._cache_attachment()
        if not att or not att.datas:
            return None
        try:
            return json.loads(gzip.decompress(base64.b64decode(att.datas)))
        except (ValueError, OSError):
            return None

    def action_parse_file(self):
        """(Re)parse the uploaded file: rebuild the column registry and cache
        the coerced rows. Never creates an Odoo model or a physical table."""
        for rec in self:
            if rec.provider_type != "file":
                continue
            if not rec.file_data:
                raise UserError("Upload a CSV or Excel file first.")
            raw = base64.b64decode(rec.file_data)
            if len(raw) > self._MAX_FILE_BYTES:
                raise UserError("Dashboard files are limited to 20 MB.")
            try:
                parsed = tabular.parse(raw, rec.file_kind or "csv")
            except tabular.TabularError as err:
                raise UserError(str(err))
            # Rebuild THIS source's columns only (no global scratch, no race).
            # Preserve identity by NAME so a re-upload of the same shape keeps
            # every widget pointing at its column; only truly-removed columns are
            # dropped (which set-nulls the references, degrading gracefully).
            existing = {c.name: c for c in rec.column_ids}
            seen = set()
            Col = self.env["eh.board.source.column"]
            for i, c in enumerate(parsed["columns"]):
                seen.add(c["name"])
                vals = {"sequence": i * 10, "label": c["label"], "dtype": c["dtype"]}
                if c["name"] in existing:
                    existing[c["name"]].write(vals)
                else:
                    Col.create({"datasource_id": rec.id, "name": c["name"], **vals})
            stale = rec.column_ids.filtered(lambda x: x.name not in seen)
            if stale:
                stale.unlink()
            rec._store_rows_cache(parsed["rows"])
            rec.row_count = parsed["row_count"]
            rec.truncated = parsed["truncated"]
        return True

    def _tabular_rows(self):
        """Cached parsed rows, self-healing by re-parsing the stored file.

        Both the cache read and the cold-cache re-parse run sudo (the file blob is
        Builder/Admin-gated), so this method MUST authorise the caller itself:
        without a record rule on this model, a plain Viewer could otherwise RPC
        tabular_rows() on an ARBITRARY datasource id and exfiltrate any uploaded
        file. A non-builder is allowed only when a widget they can actually open
        (record-rule-filtered items) references THIS source - the legitimate
        render path - and is refused otherwise."""
        self.ensure_one()
        rows = self._load_rows_cache()
        if rows is not None:
            return rows
        src = self.sudo()
        if src.file_data:
            src.action_parse_file()
            return src._load_rows_cache() or []
        return []

    def tabular_rows(self):
        """Builder-only raw preview. Viewer rendering uses private provider seam."""
        self.ensure_one()
        if not (self.env.su
                or self.env.user.has_group("eh_board.group_board_builder")):
            return []
        return self._tabular_rows()

    def _tabular_rows_for_item(self, item_id):
        """Private render seam: prove caller can read exact referencing widget."""
        self.ensure_one()
        item = self.env["eh.board.item"].browse(int(item_id or 0)).exists()
        if not item or item.datasource_id != self:
            return []
        if hasattr(item, "check_access"):
            item.check_access("read")
        else:
            item.check_access_rights("read")
            item.check_access_rule("read")
        return self._tabular_rows()

    def _join_config(self):
        """Join settings as a plain dict. A raw ``config`` (set programmatically
        or by a template) wins; otherwise the structured form fields are packed."""
        self.ensure_one()
        if self.config and self.config.get("left_model"):
            return self.config
        return {
            "left_model": self.join_left_model_id.model or None,
            "join_left": self.join_left_key or None,
            "left_measure": {"verb": self.join_left_agg or "count",
                             "field": self.join_left_value or None},
            "left_label": self.join_left_label or "Left",
            "right_model": self.join_right_model_id.model or None,
            "join_right": self.join_right_key or None,
            "right_measure": {"verb": self.join_right_agg or "count",
                              "field": self.join_right_value or None},
            "right_label": self.join_right_label or "Right",
        }

    @api.constrains("domain")
    def _check_domain(self):
        for rec in self:
            rec._parse_domain(rec.domain)

    @api.constrains("provider_type", "sql_query")
    def _check_sql_admin(self):
        # The SQL provider runs arbitrary read-only SQL; restrict its creation
        # to Dashboard Administrators (the vault-gated tier).
        # Check the acting user's id, not the superuser MODE - constraints run
        # sudo, so a mode check would skip enforcement for everyone.
        if self.env.uid == SUPERUSER_ID:
            return
        for rec in self:
            if rec.provider_type == "sql" \
                    and not self.env.user.has_group("eh_board.group_board_admin"):
                raise ValidationError(
                    "Only a Dashboard Administrator can create a SQL data source.")

    def _parse_domain(self, raw):
        """Parse a static domain literal safely (no code evaluation)."""
        raw = (raw or "").strip()
        if not raw:
            return []
        try:
            parsed = ast.literal_eval(raw)
        except (ValueError, SyntaxError) as err:
            raise ValidationError("Invalid data-source filter: %s" % err)
        if not isinstance(parsed, (list, tuple)):
            raise ValidationError("A data-source filter must be a domain list.")
        return list(parsed)

    def get_domain(self):
        self.ensure_one()
        return self._parse_domain(self.domain)

    def provider(self):
        self.ensure_one()
        return get_datasource(self.provider_type)

    def _is_tabular_source(self):
        """Registry capability, shared by file and bounded remote providers."""
        self.ensure_one()
        return bool(getattr(self.provider(), "tabular", False))

    def validate_source(self):
        self.ensure_one()
        provider = self.provider()
        return provider.validate(self) if provider else ["Unknown provider."]
