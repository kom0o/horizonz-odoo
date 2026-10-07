"""Admin-managed remote feeds, rendered only from the last valid snapshot."""
import base64
import re
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from ..lib import remote

ADMIN = "eh_board.group_board_admin"
REMOTE_TYPES = ("sheets", "rest")
CONFIG_FIELDS = (
    "remote_url", "remote_path", "remote_auth", "remote_header_name",
    "remote_token_expires", "remote_pagination", "remote_page_param",
    "remote_size_param", "remote_page_size", "remote_max_pages",
    "remote_refresh_minutes", "remote_enabled", "remote_audience_ack",
    "sheets_id", "sheets_range", "credential_id",
)


def diagnostic(code, context=None):
    messages = {
        "unsafe_url": _("Use a public HTTPS destination on port 443 without credentials in its URL. Private, local and reserved addresses are blocked."),
        "redirect": _("The source redirected the request. Enter its final HTTPS address; redirects are not followed."),
        "authentication": _("Authentication failed. Check the stored credential and grant read access to the source."),
        "expired": _("The bearer token has expired. Replace it and set its expiry, or use a Google service account for unattended refresh."),
        "temporary": _("The source is busy or unavailable. Refresh will retry with backoff."),
        "http_error": _("The source rejected the request. Check its endpoint and configuration."),
        "connection": _("The HTTPS connection failed. Check the destination, certificate and network access."),
        "timeout": _("The refresh exceeded its time limit. Reduce the requested range or page count."),
        "size": _("The response exceeds a connector limit: 8 MB, 10,000 rows or 60 columns. Narrow the source query."),
        "json": _("The response is not valid UTF-8 JSON."),
        "path": _("The JSON pointer does not identify the expected data. Use an explicit path such as /data/items."),
        "schema": _("The source schema changed or contains unsupported values. The last valid snapshot is retained; restore the column names and types or create a new source for the new schema."),
        "page_limit": _("The page limit was reached before the end of the feed. Narrow the query or increase the bounded page limit; partial totals were not saved."),
        "sheet_range": _("Choose a finite range including headers, such as Sheet1!A1:F1001, within 10,000 data rows and 60 columns."),
        "google_auth_missing": _("Install the google-auth Python package on the Odoo server to use service-account refresh, or select an expiring OAuth bearer token."),
        "not_ready": _("No valid remote snapshot exists yet. A Dashboard Administrator must refresh this source."),
        "unexpected": _("Refresh failed. The last valid snapshot is retained. Check the connection configuration before retrying."),
    }
    return messages.get(code, messages["unexpected"])


class EhBoardRemoteDataSource(models.Model):
    _inherit = "eh.board.datasource"

    remote_url = fields.Char(string="HTTPS endpoint", groups=ADMIN)
    remote_path = fields.Char(string="Rows JSON pointer", groups=ADMIN,
                              help="Blank for a root array, or /data/items. Arrays of flat objects only.")
    remote_auth = fields.Selection([
        ("none", "No authentication"), ("bearer", "OAuth bearer token"),
        ("service_account", "Google service account JSON"),
        ("basic", "Username and password"), ("header", "API key header")],
        default="none", string="Authentication", groups=ADMIN)
    remote_header_name = fields.Char(default="X-API-Key", string="API key header", groups=ADMIN)
    remote_token_expires = fields.Datetime(string="Bearer token expiry (UTC)", groups=ADMIN)
    remote_pagination = fields.Selection([("none", "Single response"), ("page", "Numbered pages")],
                                         default="none", string="Pagination", groups=ADMIN)
    remote_page_param = fields.Char(default="page", string="Page parameter", groups=ADMIN)
    remote_size_param = fields.Char(default="limit", string="Page size parameter", groups=ADMIN)
    remote_page_size = fields.Integer(default=500, string="Rows per page", groups=ADMIN)
    remote_max_pages = fields.Integer(default=5, string="Maximum pages", groups=ADMIN)
    remote_refresh_minutes = fields.Integer(default=60, string="Refresh every (minutes)", groups=ADMIN)
    remote_enabled = fields.Boolean(default=True, string="Scheduled refresh", groups=ADMIN)
    remote_audience_ack = fields.Boolean(string="Share this snapshot with this dashboard's audience", groups=ADMIN,
        help="Remote rows share one snapshot. Odoo model record rules do not filter these rows. Only connect data suitable for everyone who can view this dashboard.")
    sheets_id = fields.Char(string="Google spreadsheet ID", groups=ADMIN)
    sheets_range = fields.Char(default="Sheet1!A1:F1001", string="Sheet range with headers", groups=ADMIN)
    remote_last_attempt = fields.Datetime(string="Last refresh attempt", readonly=True)
    remote_last_success = fields.Datetime(string="Last successful refresh", readonly=True)
    remote_next_refresh = fields.Datetime(string="Next refresh", readonly=True)
    remote_error_code = fields.Char(string="Refresh diagnostic code", readonly=True)
    remote_last_error = fields.Text(string="Last refresh error", compute="_compute_remote_state")
    remote_failures = fields.Integer(string="Consecutive failures", readonly=True, groups=ADMIN)
    remote_schema = fields.Json(default=list, readonly=True, groups=ADMIN)
    remote_state = fields.Selection([("pending", "Awaiting first refresh"), ("fresh", "Current"),
                                    ("stale", "Using last valid snapshot"), ("error", "Refresh failed")],
                                   compute="_compute_remote_state", string="Refresh status")

    @api.depends("remote_last_success", "remote_error_code", "remote_next_refresh")
    def _compute_remote_state(self):
        now = fields.Datetime.now()
        for source in self:
            source.remote_last_error = diagnostic(source.remote_error_code, self.env.context) if source.remote_error_code else False
            if not source.remote_last_success:
                source.remote_state = "error" if source.remote_error_code else "pending"
            elif source.remote_error_code or (source.remote_next_refresh and source.remote_next_refresh < now):
                source.remote_state = "stale"
            else:
                source.remote_state = "fresh"

    def _require_remote_admin(self):
        if not (self.env.su or self.env.user.has_group(ADMIN)):
            raise AccessError(_("Only a Dashboard Administrator can configure or refresh remote sources."))

    def _remote_check_access(self, operation="read"):
        if hasattr(self, "check_access"):
            self.check_access(operation)
        else:
            self.check_access_rights(operation)
            self.check_access_rule(operation)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("provider_type") in REMOTE_TYPES or any(k.startswith(("remote_", "sheets_")) for k in vals):
                self._require_remote_admin()
        return super().create(vals_list)

    def write(self, vals):
        if (any(r.provider_type in REMOTE_TYPES for r in self)
                or vals.get("provider_type") in REMOTE_TYPES
                or any(k.startswith(("remote_", "sheets_")) for k in vals)):
            self._require_remote_admin()
        return super().write(vals)

    def unlink(self):
        if any(source.provider_type in REMOTE_TYPES for source in self):
            self._require_remote_admin()
        return super().unlink()

    def copy_data(self, default=None):
        if any(source.provider_type in REMOTE_TYPES for source in self):
            raise UserError(_("Remote connections are not copied. Create an administrator-approved connection on the destination dashboard."))
        return super().copy_data(default)

    @api.constrains("provider_type", "dashboard_id", *CONFIG_FIELDS)
    def _check_remote_configuration(self):
        for source in self.filtered(lambda s: s.provider_type in REMOTE_TYPES):
            if not source.dashboard_id or not source.remote_audience_ack:
                raise ValidationError(_("Remote sources must belong to a dashboard and explicitly share their snapshot with its audience."))
            if not 5 <= source.remote_refresh_minutes <= 10080:
                raise ValidationError(_("Refresh intervals must be between 5 minutes and 7 days."))
            if not 1 <= source.remote_page_size <= 1000 or not 1 <= source.remote_max_pages <= remote.MAX_PAGES:
                raise ValidationError(_("Choose 1–1,000 rows per page and 1–10 pages."))
            if source.provider_type == "sheets":
                if source.remote_auth not in ("bearer", "service_account"):
                    raise ValidationError(_("Private Google Sheets require a service account or OAuth bearer token."))
                if not source.sheets_id or not source.sheets_range:
                    raise ValidationError(_("Enter a spreadsheet ID and finite sheet range."))
            else:
                try:
                    remote.destination(source.remote_url, resolve=False)
                except remote.RemoteError as exc:
                    raise ValidationError(diagnostic(exc.code, self.env.context)) from None
                if source.remote_auth == "service_account":
                    raise ValidationError(_("Google service-account authentication is available only for Google Sheets."))
            if source.remote_auth != "none" and not source.credential_id:
                raise ValidationError(_("Choose a stored credential or enter a new secret."))
            if source.remote_auth == "bearer" and not source.remote_token_expires:
                raise ValidationError(_("Set the OAuth bearer token's expiry time."))
            if source.remote_auth == "header" and not re.fullmatch(r"X-[A-Za-z0-9-]{1,60}", source.remote_header_name or "", re.I):
                raise ValidationError(_("Use an X- header for API keys, such as X-API-Key."))
            if source.remote_path and (not source.remote_path.startswith("/") or len(source.remote_path) > 512):
                raise ValidationError(_("Use a JSON pointer such as /data/items, or leave it blank for a root array."))

    def _remote_headers(self):
        self.ensure_one()
        mode = self.remote_auth
        if mode == "none":
            return {}
        credential = self.credential_id
        secret = credential.secret or ""
        if not secret or len(secret) > 20000:
            raise remote.RemoteError("authentication")
        if mode == "service_account":
            return {"Authorization": "Bearer " + remote.service_account_token(secret)}
        if "\n" in secret or "\r" in secret:
            raise remote.RemoteError("authentication")
        if mode == "bearer":
            if not self.remote_token_expires or self.remote_token_expires <= fields.Datetime.now():
                raise remote.RemoteError("expired")
            return {"Authorization": "Bearer " + secret}
        if mode == "basic":
            username = credential.username or ""
            if ":" in username or "\n" in username or "\r" in username:
                raise remote.RemoteError("authentication")
            encoded = base64.b64encode((username + ":" + secret).encode()).decode("ascii")
            return {"Authorization": "Basic " + encoded}
        return {self.remote_header_name: secret}

    def _fetch_remote(self):
        self.ensure_one()
        headers = self._remote_headers()
        if self.provider_type == "sheets":
            return remote.fetch_sheets(self.sheets_id, self.sheets_range, headers)
        return remote.fetch_rest({
            "url": self.remote_url, "path": self.remote_path,
            "pagination": self.remote_pagination, "page_param": self.remote_page_param,
            "size_param": self.remote_size_param, "page_size": self.remote_page_size,
            "max_pages": self.remote_max_pages,
        }, headers)

    def _refresh_remote_snapshot(self):
        """Atomic replacement. Any refresh/schema failure leaves prior rows and IDs intact."""
        self.ensure_one()
        self._require_remote_admin()
        self._remote_check_access("write")
        self.env.cr.execute("SELECT id FROM eh_board_datasource WHERE id = %s FOR UPDATE SKIP LOCKED", [self.id])
        if not self.env.cr.fetchone():
            return False
        now = fields.Datetime.now()
        try:
            with self.env.cr.savepoint():
                parsed = self._fetch_remote()
                previous = {c["name"]: c for c in (self.remote_schema or [])}
                current = {c["name"]: c for c in parsed["columns"]}
                if not parsed["rows"] and previous:
                    if current and set(previous) - set(current):
                        raise remote.RemoteError("schema")
                    parsed["columns"] = self.remote_schema
                    current = previous
                if not current or set(previous) - set(current):
                    raise remote.RemoteError("schema")
                if any(current[name]["dtype"] != old["dtype"] for name, old in previous.items()):
                    raise remote.RemoteError("schema")
                existing = {c.name: c for c in self.column_ids}
                for index, column in enumerate(parsed["columns"]):
                    vals = {"sequence": index * 10, "label": column["label"], "dtype": column["dtype"]}
                    if column["name"] in existing:
                        existing[column["name"]].write(vals)
                    else:
                        self.env["eh.board.source.column"].create({"datasource_id": self.id, "name": column["name"], **vals})
                self._store_rows_cache(parsed["rows"])
                self.write({"row_count": parsed["row_count"], "truncated": False,
                            "remote_schema": parsed["columns"], "remote_last_success": now,
                            "remote_last_attempt": now, "remote_error_code": False,
                            "remote_failures": 0,
                            "remote_next_refresh": now + timedelta(minutes=self.remote_refresh_minutes)})
            return True
        except remote.RemoteError as exc:
            code = exc.code
        except Exception:
            code = "unexpected"
        failures = min(self.remote_failures + 1, 20)
        self.write({"remote_last_attempt": now, "remote_error_code": code,
                    "remote_failures": failures,
                    "remote_next_refresh": now + timedelta(minutes=min(1440, 5 * (2 ** min(failures - 1, 9))))})
        return False

    def action_refresh_remote(self):
        self._require_remote_admin()
        for source in self:
            if source.provider_type in REMOTE_TYPES:
                source._refresh_remote_snapshot()
        return True

    @api.model
    def _cron_refresh_remote(self):
        self._require_remote_admin()
        now = fields.Datetime.now()
        sources = self.search([("provider_type", "in", REMOTE_TYPES), ("remote_enabled", "=", True),
                               "|", ("remote_next_refresh", "=", False), ("remote_next_refresh", "<=", now)],
                              limit=3, order="remote_next_refresh, id")
        for source in sources:
            source._refresh_remote_snapshot()
        return len(sources)

    def _tabular_rows(self):
        self.ensure_one()
        if self.provider_type in REMOTE_TYPES:
            return self._load_rows_cache() or []
        return super()._tabular_rows()

    def tabular_rows(self):
        if any(s.provider_type in REMOTE_TYPES for s in self):
            self._require_remote_admin()
            self._remote_check_access()
        return super().tabular_rows()

    def _tabular_rows_for_item(self, item_id):
        self.ensure_one()
        if self.provider_type in REMOTE_TYPES:
            item = self.env["eh.board.item"].browse(int(item_id or 0)).exists()
            if not item or item.datasource_id != self or item.dashboard_id != self.dashboard_id:
                raise AccessError(_("Remote snapshots are available only through their owning dashboard."))
        return super()._tabular_rows_for_item(item_id)

    def _remote_status(self):
        self.ensure_one()
        # No endpoint, sheet ID, credential identity or upstream error body.
        return {"state": self.remote_state, "last_success": fields.Datetime.to_string(self.remote_last_success) if self.remote_last_success else False,
                "last_attempt": fields.Datetime.to_string(self.remote_last_attempt) if self.remote_last_attempt else False,
                "next_refresh": fields.Datetime.to_string(self.remote_next_refresh) if self.remote_next_refresh else False,
                "error": self.remote_last_error or False, "rows": self.row_count,
                "scope": _("Shared remote snapshot for this dashboard's audience. Odoo model record rules do not filter these rows.")}

    @api.model
    def remote_config(self, dashboard_id, source_id=False):
        self._require_remote_admin()
        board = self.env["eh.board.dashboard"].browse(int(dashboard_id)).exists()
        board.ensure_one()
        board._require_edit()
        if not source_id:
            return {}
        source = board._owned_source(source_id)
        placeholder = source.provider_type == "file" and (source.config or {}).get("requires_remote") in REMOTE_TYPES
        if source.dashboard_id != board or (source.provider_type not in REMOTE_TYPES and not placeholder):
            raise AccessError(_("This remote source does not belong to this dashboard."))
        result = {field: source[field] or False for field in CONFIG_FIELDS if field != "credential_id"}
        result["remote_token_expires"] = fields.Datetime.to_string(source.remote_token_expires) if source.remote_token_expires else ""
        provider = source.config["requires_remote"] if placeholder else source.provider_type
        if placeholder:
            result["remote_auth"] = "service_account" if provider == "sheets" else "none"
        result.update({"id": source.id, "name": source.name, "provider": provider,
                       "credential_id": source.credential_id.id or False,
                       "has_secret": bool(source.credential_id), "status": source._remote_status(),
                       "source": board._source_meta(source)})
        return result

    @api.model
    def remote_save_config(self, dashboard_id, values, source_id=False):
        self._require_remote_admin()
        board = self.env["eh.board.dashboard"].browse(int(dashboard_id)).exists()
        board.ensure_one()
        board._require_edit()
        if not isinstance(values, dict):
            raise UserError(_("Invalid remote source settings."))
        source = board._owned_source(source_id) if source_id else self.browse()
        provider = values.get("provider")
        placeholder = source and source.provider_type == "file" and (source.config or {}).get("requires_remote") == provider
        if provider not in REMOTE_TYPES or (source and (source.dashboard_id != board or (source.provider_type != provider and not placeholder))):
            raise AccessError(_("Choose a remote source owned by this dashboard."))
        vals = {key: values[key] for key in CONFIG_FIELDS if key in values}
        vals.update({"name": str(values.get("name") or _("Remote source"))[:120], "provider_type": provider,
                     "dashboard_id": board.id, "remote_next_refresh": fields.Datetime.now()})
        if placeholder:
            vals.update({"config": {}, "file_data": False, "file_name": False,
                         "remote_schema": [{"name": c.name, "label": c.label, "dtype": c.dtype} for c in source.column_ids]})
        secret = values.get("secret")
        if secret:
            if not isinstance(secret, str) or len(secret) > 20000:
                raise UserError(_("The credential is too large."))
            # Always create a new credential on replacement. Never mutate a vault entry shared by other connections.
            credential = self.env["eh.board.credential"].create({"name": vals["name"], "kind": "token",
                          "username": str(values.get("username") or "")[:255], "secret": secret})
            vals["credential_id"] = credential.id
        source.write(vals) if source else None
        if not source:
            source = self.create(vals)
        return {"id": source.id, "name": source.name, "provider": source.provider_type, "status": source._remote_status()}


class EhBoardRemoteSourceColumn(models.Model):
    _inherit = "eh.board.source.column"

    def _require_remote_column_admin(self, source):
        if source and source.provider_type in REMOTE_TYPES:
            source._require_remote_admin()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._require_remote_column_admin(self.env["eh.board.datasource"].browse(vals.get("datasource_id")))
        return super().create(vals_list)

    def write(self, vals):
        for source in self.mapped("datasource_id"):
            self._require_remote_column_admin(source)
        if vals.get("datasource_id"):
            self._require_remote_column_admin(self.env["eh.board.datasource"].browse(vals["datasource_id"]))
        return super().write(vals)

    def unlink(self):
        for source in self.mapped("datasource_id"):
            self._require_remote_column_admin(source)
        return super().unlink()
