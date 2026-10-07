# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
import ast
import base64
import binascii
import calendar
import json
import logging
import math

import pytz

from odoo import _, api, fields, models, SUPERUSER_ID
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools.safe_eval import safe_eval

from ..lib.aggregation import grouped_read
from ..lib.registry import get_datasource

if not hasattr(fields, "Domain"):  # Odoo 16-18
    from odoo.osv import expression as _legacy_expression

_logger = logging.getLogger(__name__)


def _normal_domain(domain):
    """Validate and canonicalise a domain without Odoo 19 deprecations."""
    if hasattr(fields, "Domain"):
        return list(fields.Domain(domain or []))
    return _legacy_expression.normalize_domain(domain or [])


def _and_domains(domains):
    if hasattr(fields, "Domain"):
        return list(fields.Domain.AND(domains))
    return _legacy_expression.AND(domains)


class EhBoardDashboard(models.Model):
    _name = "eh.board.dashboard"
    _description = "Dashboard"
    _order = "sequence, name"

    name = fields.Char(required=True, default="New Dashboard")
    sequence = fields.Integer(default=10)
    state = fields.Selection(
        [("draft", "Draft"), ("published", "Published")],
        default="draft", required=True)
    owner_id = fields.Many2one(
        "res.users", string="Owner", default=lambda self: self.env.user)
    company_ids = fields.Many2many(
        "res.company", string="Companies",
        default=lambda self: self.env.company)
    group_ids = fields.Many2many(
        "res.groups", string="Restricted to groups",
        help="Leave empty to let every internal user with dashboard access see it.")
    shared_user_ids = fields.Many2many(
        "res.users", "eh_board_dashboard_shared_user_rel", "dashboard_id", "user_id",
        string="Shared with",
        help="Specific users who may open this dashboard even while it is a draft.")
    description = fields.Text()
    thumbnail = fields.Binary(attachment=True)
    is_template = fields.Boolean()
    parent_dashboard_id = fields.Many2one(
        "eh.board.dashboard", string="Parent dashboard", ondelete="set null",
        index=True, help="Optional dashboard family used for in-canvas tabs.")
    child_dashboard_ids = fields.One2many(
        "eh.board.dashboard", "parent_dashboard_id", string="Child dashboards")
    favorite_user_ids = fields.Many2many(
        "res.users", "eh_board_dashboard_favorite_user_rel",
        "dashboard_id", "user_id", string="Favorited by", copy=False)

    refresh_mode = fields.Selection(
        [("off", "Manual"), ("interval", "Auto (interval)"), ("live", "Live")],
        default="off", required=True)
    refresh_interval = fields.Integer(
        default=60, help="Seconds between refreshes when auto-refresh is on.")
    is_kiosk = fields.Boolean(string="Kiosk-ready")
    palette = fields.Selection(
        [("default", "Heritage"), ("ocean", "Ocean"), ("sunset", "Sunset"),
         ("forest", "Forest"), ("mono", "Monochrome")],
        default="default", help="Chart colour palette for this dashboard.")
    default_date_preset = fields.Selection(
        [("all", "None"), ("today", "Today"), ("yesterday", "Yesterday"),
         ("tomorrow", "Tomorrow"), ("this_week", "This week"),
         ("last_week", "Last week"), ("next_week", "Next week"),
         ("this_month", "This month"), ("last_month", "Last month"),
         ("next_month", "Next month"), ("this_quarter", "This quarter"),
         ("last_quarter", "Last quarter"), ("next_quarter", "Next quarter"),
         ("this_year", "This year"), ("last_year", "Last year"),
         ("next_year", "Next year"), ("wtd", "Week to date"),
         ("mtd", "Month to date"), ("qtd", "Quarter to date"),
         ("ytd", "Year to date"), ("last_7", "Last 7 days"),
         ("last_30", "Last 30 days"), ("last_90", "Last 90 days"),
         ("last_365", "Last 365 days")],
        default="all",
        help="The date range this dashboard opens with (the board date filter's start value).")
    digest_enabled = fields.Boolean(
        string="Email digest", help="Email this dashboard as a PDF on a schedule.")
    digest_user_ids = fields.Many2many(
        "res.users", "eh_board_dashboard_digest_user_rel", "dashboard_id", "user_id",
        string="Digest recipients")
    digest_frequency = fields.Selection(
        [("daily", "Daily"), ("weekly", "Weekly"), ("monthly", "Monthly")],
        default="weekly", required=True, string="Digest frequency")
    digest_weekday = fields.Selection(
        [("0", "Monday"), ("1", "Tuesday"), ("2", "Wednesday"),
         ("3", "Thursday"), ("4", "Friday"), ("5", "Saturday"),
         ("6", "Sunday")],
        default="0", required=True, string="Digest weekday")
    digest_month_day = fields.Integer(
        default=1, string="Digest day of month",
        help="Days beyond a short month's end are sent on that month's final day.")
    digest_hour = fields.Integer(
        default=8, string="Digest hour",
        help="Hour of day (0-23) in the dashboard owner's timezone.")
    digest_last_sent_on = fields.Datetime(copy=False, readonly=True)
    digest_view = fields.Json(default=dict, copy=False,
        help="Saved report filters. Relative dates are resolved when each digest is generated.")

    item_ids = fields.One2many("eh.board.item", "dashboard_id", string="Items")
    item_count = fields.Integer(compute="_compute_item_count")
    layout_version_ids = fields.One2many(
        "eh.board.layout.version", "dashboard_id", string="Layouts")
    active_layout_id = fields.Many2one(
        "eh.board.layout.version", string="Active layout",
        # Do NOT carry the pointer to the ORIGINAL board's layout on copy(); the
        # duplicate resolves its own active layout from its copied layout list.
        copy=False)
    filter_ids = fields.One2many(
        "eh.board.filter", "dashboard_id", string="Filters")
    alert_ids = fields.One2many(
        "eh.board.alert", "dashboard_id", string="Alerts")

    @api.constrains("parent_dashboard_id")
    def _check_parent_dashboard(self):
        has_cycle = self._has_cycle("parent_dashboard_id") \
            if hasattr(self, "_has_cycle") \
            else not self._check_recursion("parent_dashboard_id")
        if has_cycle:
            raise ValidationError(_("Dashboard hierarchy cannot contain a cycle."))

    @api.depends("item_ids")
    def _compute_item_count(self):
        for rec in self:
            rec.item_count = len(rec.item_ids)

    # ------------------------------------------------------------------ data
    def _active_layout(self):
        self.ensure_one()
        if self.active_layout_id:
            return self.active_layout_id
        company = self.env.company
        match = self.layout_version_ids.filtered(
            lambda l: l.is_active and (not l.company_id or l.company_id == company))
        return match[:1] or self.layout_version_ids[:1]

    _LAZY_EAGER = 8   # widgets rendered with data up front; the rest lazy-load

    def _analysis_options(self, options=None):
        """One bounded, caller-scoped context for charts, insights and exports.

        Identity and timezone come from the authenticated environment, never
        from browser input. Drill paths may reference this board's items only.
        """
        self.ensure_one()
        if hasattr(self, "check_access"):
            self.check_access("read")
        else:
            self.check_access_rights("read")
            self.check_access_rule("read")
        options = {} if options is None else options
        if not isinstance(options, dict):
            raise UserError(_("Dashboard filters must be an object."))
        try:
            if len(json.dumps(options, allow_nan=False)) > 100000:
                raise ValueError()
        except (TypeError, ValueError):
            raise UserError(_("Dashboard filters are invalid or too large."))
        out = {}
        companies = options.get("company_ids")
        if companies is None:
            companies = self.env.companies.ids
        if (not isinstance(companies, list) or not companies
                or any(type(cid) is not int for cid in companies)
                or not set(companies).issubset(self.env.companies.ids)):
            raise AccessError(_("Choose companies available in your current session."))
        out["company_ids"] = list(dict.fromkeys(companies))
        domain = options.get("domain") or []
        if not isinstance(domain, list) or len(domain) > 200:
            raise UserError(_("Dashboard filter is invalid."))
        try:
            out["domain"] = _normal_domain(domain) if domain else []
        except (ValueError, TypeError, AssertionError):
            raise UserError(_("Dashboard filter is invalid."))
        date_range = options.get("date_range") or {}
        if date_range:
            try:
                start = fields.Date.to_date(date_range.get("start"))
                end = fields.Date.to_date(date_range.get("end"))
                if not start or not end or start > end:
                    raise ValueError()
            except (AttributeError, TypeError, ValueError):
                raise UserError(_("Choose a valid date range."))
            out["date_range"] = {"start": start.isoformat(), "end": end.isoformat()}
        filters = options.get("filters") or []
        if not isinstance(filters, list) or len(filters) > 50:
            raise UserError(_("Dashboard filters are invalid or too large."))
        out["filters"] = []
        for flt in filters:
            if (not isinstance(flt, dict) or not isinstance(flt.get("field"), str)
                    or any(flt.get(key) not in (None, False, "") and not isinstance(flt.get(key), str)
                           for key in ("model", "relation"))
                    or (flt.get("source_id") is not None and type(flt.get("source_id")) is not int)
                    or not isinstance(flt.get("values"), list)
                    or len(flt["values"]) > 1000
                    or any(isinstance(value, (dict, list)) for value in flt["values"])):
                raise UserError(_("Dashboard filter is invalid."))
            out["filters"].append({key: flt.get(key) for key in
                                   ("field", "model", "relation", "values")
                                   if key in flt})
            if flt.get("source_id") is not None:
                out["filters"][-1]["source_id"] = flt["source_id"]
        paths = options.get("drill_paths") or {}
        if not isinstance(paths, dict) or len(paths) > 200:
            raise UserError(_("Dashboard drill path is invalid."))
        owned = {str(item.id): item for item in self.item_ids}
        out["drill_paths"] = {}
        for key, path in paths.items():
            if str(key) not in owned:
                raise UserError(_("Dashboard drill path references another widget."))
            owned[str(key)]._drill_options(path, out)
            out["drill_paths"][str(key)] = path
        return out

    def _analysis_payload(self, item, options):
        path = (options.get("drill_paths") or {}).get(str(item.id))
        return item.get_drilled_payload(path, options) if path else item.get_payload(options)

    def _analysis_scope(self, options=None):
        options = self._analysis_options(
            self.env.context.get("eh_board_options") if options is None else options)
        date_range = options.get("date_range") or {}
        scope = {
            "generated_at": fields.Datetime.to_string(fields.Datetime.now()),
            "timezone": self.env.context.get("tz") or self.env.user.tz or "UTC",
            "companies": self.env["res.company"].browse(options["company_ids"]).mapped("name"),
            "start": date_range.get("start"), "end": date_range.get("end"),
            "filters": options.get("filters") or [],
            "domain": options.get("domain") or [],
            "drilled_items": list((options.get("drill_paths") or {}).keys()),
        }
        labels = []
        for flt in scope["filters"]:
            label = flt["field"]
            model = flt.get("model")
            if model and model in self.env and label in self.env[model]._fields:
                label = self.env[model]._fields[label].string or label
            labels.append("%s: %s" % (label, ", ".join(str(v) for v in flt["values"])))
        scope["label"] = " · ".join(part for part in [
            ", ".join(scope["companies"]),
            "%s — %s" % (scope["start"], scope["end"]) if scope["start"] else _("Widget date defaults"),
            scope["timezone"],
            "; ".join(labels) if labels else _("No field filters"),
            _("Additional filter") if scope["domain"] else "",
            _("Drilled view") if scope["drilled_items"] else _("Full board"),
            scope["generated_at"] + " UTC",
        ] if part)
        return scope

    def get_export_data(self, options=None):
        """Complete snapshot of the selected view, including deferred widgets."""
        return self.get_data(options, lazy=False)

    def get_data(self, options=None, lazy=False):
        """Full payload for the OWL board: config, items, layout, filters.

        With ``lazy`` on, only the first widgets carry data; the rest are listed
        in ``lazy_ids`` and fetched by the client as they scroll into view, so a
        20-30 widget board paints the visible ones first."""
        self.ensure_one()
        options = self._analysis_options(options)
        layout = self._active_layout()
        items, lazy_ids = [], []
        for i, item in enumerate(self.item_ids):
            if lazy and i >= self._LAZY_EAGER:
                lazy_ids.append(item.id)
            else:
                items.append(self._analysis_payload(item, options))
        family_root = self.parent_dashboard_id or self
        navigation = family_root | family_root.child_dashboard_ids
        return {
            "id": self.id,
            "name": self.name,
            "state": self.state,
            "refresh_mode": self.refresh_mode,
            "refresh_interval": self.refresh_interval,
            "is_kiosk": self.is_kiosk,
            "palette": self.palette or "default",
            "default_date_preset": self.default_date_preset or "all",
            "can_edit": self._can_edit(),
            "can_remote": bool(self.env.su or self.env.user.has_group("eh_board.group_board_admin")),
            "is_favorite": self.env.user in self.favorite_user_ids,
            "navigation": [{"id": board.id, "name": board.name}
                           for board in navigation.sorted(
                               key=lambda board: (board.sequence, board.name or ""))],
            "layout": layout.grid if layout else {},
            "density": layout.density if layout else "comfortable",
            "filters": [f.spec() for f in self.filter_ids],
            "items": items,
            "lazy_ids": lazy_ids,
            "item_meta": [item._meta() for item in self.item_ids],
            "scope": self._analysis_scope(options),
        }

    def list_boards(self):
        """Boards the current user may open (record-rule filtered) for the
        in-app dashboard switcher."""
        user = self.env.user
        boards = self.search([], order="sequence, name")
        boards = boards.sorted(
            key=lambda board: (user not in board.favorite_user_ids,
                               bool(board.parent_dashboard_id),
                               board.sequence, board.name or ""))
        return [{
            "id": board.id,
            "name": board.name,
            "parent_id": board.parent_dashboard_id.id or False,
            "favorite": user in board.favorite_user_ids,
        } for board in boards]

    def toggle_favorite(self):
        """Toggle current user's personal shortcut without granting board write."""
        self.ensure_one()
        user = self.env.user
        favorite = user not in self.favorite_user_ids
        # Viewers intentionally lack dashboard write ACL. This narrow method may
        # mutate only their own relation row, never dashboard configuration.
        self.sudo().write({
            "favorite_user_ids": [(4 if favorite else 3, user.id)],
        })
        if hasattr(self, "invalidate_recordset"):
            self.invalidate_recordset(["favorite_user_ids"])
        else:  # Odoo 16 compatibility
            self.invalidate_cache(["favorite_user_ids"], self.ids)
        return {"favorite": favorite}

    @api.model
    def can_build(self):
        return bool(self.env.su
                    or self.env.user.has_group("eh_board.group_board_builder"))

    @api.model
    def count_domain_matches(self, model_name, domain, include_archived=False):
        """Safe live match-count for the builder's compact domain editor.

        The domain literal is parsed with ``ast.literal_eval`` (never evaluated as
        code) and counted AS THE CURRENT USER, so record rules apply and a value
        containing an apostrophe no longer breaks a client-side quote-swap parse.
        Returns None when the domain is unparseable or the model is unknown."""
        if not self.can_build():
            raise AccessError(_("Only a dashboard builder can inspect a builder domain."))
        if not model_name or model_name not in self.env:
            return None
        try:
            parsed = ast.literal_eval(domain or "[]")
        except (ValueError, SyntaxError):
            return None
        if not isinstance(parsed, (list, tuple)):
            return None
        Model = self.env[model_name]
        if include_archived:
            Model = Model.with_context(active_test=False)
        try:
            return Model.search_count(list(parsed))
        except Exception:  # noqa: BLE001 - a bad ad-hoc domain must not 500
            return None

    # -- dashboard settings --------------------------------------------------
    def _can_edit(self):
        """True only when ACLs also permit dashboard writes."""
        self.ensure_one()
        return self.env.su or self.env.user.has_group("eh_board.group_board_builder")

    def _require_edit(self):
        """Central mutation guard for every public in-canvas RPC.

        Child-model ACLs are useful defence in depth, but they are not an
        ownership check: an RPC could otherwise pass an item/filter id from a
        different dashboard.  Every mutating route enters through this guard
        and then resolves child records through this dashboard's One2many.
        """
        self.ensure_one()
        if not self._can_edit():
            raise AccessError(_("You may not change this dashboard."))

    def _owned_item(self, item_id):
        """Return one item belonging to this board or reject the foreign id."""
        self.ensure_one()
        try:
            item_id = int(item_id or 0)
        except (TypeError, ValueError):
            item_id = 0
        item = self.item_ids.filtered(lambda record: record.id == item_id)[:1]
        if not item:
            raise UserError(_("That widget does not belong to this dashboard."))
        return item

    def _owned_filter(self, filter_id):
        """Return one filter belonging to this board or reject the foreign id."""
        self.ensure_one()
        try:
            filter_id = int(filter_id or 0)
        except (TypeError, ValueError):
            filter_id = 0
        board_filter = self.filter_ids.filtered(
            lambda record: record.id == filter_id)[:1]
        if not board_filter:
            raise UserError(_("That filter does not belong to this dashboard."))
        return board_filter

    def _owned_source(self, source_id):
        """Resolve a source attached to, or already used by, this dashboard."""
        self.ensure_one()
        try:
            source_id = int(source_id or 0)
        except (TypeError, ValueError):
            source_id = 0
        source = self.env["eh.board.datasource"].browse(source_id).exists()
        used_here = source and source.item_ids.filtered(
            lambda item: item.dashboard_id == self)
        if not source or (source.dashboard_id != self and not used_here):
            raise UserError(_("That data source does not belong to this dashboard."))
        return source

    def _owned_alert(self, alert_id):
        self.ensure_one()
        try:
            alert_id = int(alert_id or 0)
        except (TypeError, ValueError):
            alert_id = 0
        alert = self.alert_ids.filtered(lambda record: record.id == alert_id)[:1]
        if not alert:
            raise UserError(_("That alert does not belong to this dashboard."))
        return alert

    def _source_meta(self, source):
        """Secret-free descriptor consumed by unified visual source picker."""
        remote_kind = source.provider_type if source.provider_type in ("rest", "sheets") \
            else (source.config or {}).get("requires_remote")
        is_remote = remote_kind in ("rest", "sheets")
        result = {
            "id": source.id,
            "name": source.name,
            "provider": source.provider_type,
            "model_id": source.model_id.id if source.model_id else False,
            "model_name": source.model_name or "",
            "editable": bool(source.dashboard_id == self and (
                (source.provider_type != "sql" and not is_remote) or self.env.su
                or self.env.user.has_group("eh_board.group_board_admin")
            )),
            "rows": source.row_count if source._is_tabular_source() else None,
            "tabular": source._is_tabular_source(),
            "requires_remote": remote_kind if source.provider_type == "file" and is_remote else False,
            "truncated": bool(source.truncated),
            "columns": [{
                "name": column.name,
                "label": column.label,
                "dtype": column.dtype,
            } for column in source.column_ids],
        }
        if is_remote:
            result["status"] = source._remote_status()
        return result

    def get_settings(self):
        """Current dashboard settings + the option lists the settings panel
        needs (users to share with / to email)."""
        self.ensure_one()
        # User directory is needed only by editors.  Do not turn this read-only
        # settings endpoint into an internal-user enumeration seam for viewers.
        users = self.env["res.users"]
        if self._can_edit():
            users = users.search(
                [("share", "=", False), ("active", "=", True)], order="name")
        layout = self._active_layout()
        boards = self.search([("id", "!=", self.id)], order="sequence, name") \
            if self._can_edit() else self.env["eh.board.dashboard"]
        return {
            "id": self.id,
            "name": self.name or "",
            "description": self.description or "",
            "published": self.state == "published",
            "palette": self.palette or "default",
            "density": layout.density if layout else "comfortable",
            "default_date_preset": self.default_date_preset or "all",
            "refresh_mode": self.refresh_mode or "off",
            "refresh_interval": self.refresh_interval or 60,
            "digest_enabled": self.digest_enabled,
            "digest_frequency": self.digest_frequency or "weekly",
            "digest_weekday": self.digest_weekday or "0",
            "digest_month_day": self.digest_month_day or 1,
            "digest_hour": self.digest_hour if self.digest_hour is not False else 8,
            "parent_dashboard_id": self.parent_dashboard_id.id or False,
            "boards": [{"id": board.id, "name": board.name} for board in boards],
            "shared_user_ids": self.shared_user_ids.ids,
            "digest_user_ids": self.digest_user_ids.ids,
            "users": [{"id": u.id, "name": u.name} for u in users],
            "can_edit": self._can_edit(),
        }

    def save_settings(self, vals):
        """Apply settings from the in-app panel. Owner/builder only; layout
        density lives on the active layout, everything else on the board."""
        self.ensure_one()
        if not self._can_edit():
            from odoo.exceptions import AccessError
            raise AccessError(_("You may not change this dashboard's settings."))
        vals = dict(vals or {})
        density = vals.get("density")
        write_vals = {}

        if "name" in vals:
            name = str(vals.get("name") or "").strip()[:120]
            if not name:
                raise UserError(_("Dashboard name cannot be empty."))
            write_vals["name"] = name
        if "description" in vals:
            write_vals["description"] = str(vals.get("description") or "")[:20000]
        if "published" in vals:
            write_vals["state"] = "published" if vals.get("published") else "draft"

        for key in ("palette", "default_date_preset", "refresh_mode",
                    "digest_frequency", "digest_weekday"):
            if key not in vals:
                continue
            value = vals.get(key)
            selection = self._fields[key].selection
            allowed = {choice[0] for choice in selection}
            # ``live`` was a legacy name for polling, not push updates.  New UI
            # is truthful and writes interval; accept old records on read only.
            if key == "refresh_mode" and value == "live":
                value = "interval"
            if value not in allowed:
                raise UserError(_("Unsupported dashboard setting: %s") % key)
            write_vals[key] = value

        if "refresh_interval" in vals:
            try:
                interval = int(vals.get("refresh_interval") or 60)
            except (TypeError, ValueError):
                raise UserError(_("Refresh interval must be a number of seconds."))
            write_vals["refresh_interval"] = max(5, min(interval, 86400))
        if "digest_enabled" in vals:
            write_vals["digest_enabled"] = bool(vals.get("digest_enabled"))
        if "digest_month_day" in vals:
            try:
                month_day = int(vals.get("digest_month_day") or 1)
            except (TypeError, ValueError):
                raise UserError(_("Digest day must be a number from 1 to 31."))
            write_vals["digest_month_day"] = max(1, min(month_day, 31))
        if "digest_hour" in vals:
            try:
                digest_hour = int(vals.get("digest_hour"))
            except (TypeError, ValueError):
                raise UserError(_("Digest hour must be a number from 0 to 23."))
            write_vals["digest_hour"] = max(0, min(digest_hour, 23))
        if "parent_dashboard_id" in vals:
            try:
                parent_id = int(vals.get("parent_dashboard_id") or 0)
            except (TypeError, ValueError):
                raise UserError(_("Choose a valid parent dashboard."))
            parent = self.search([
                ("id", "=", parent_id), ("id", "!=", self.id),
            ], limit=1) if parent_id else self.env["eh.board.dashboard"]
            if parent_id and not parent:
                raise UserError(_("Choose a visible parent dashboard."))
            write_vals["parent_dashboard_id"] = parent.id or False

        def _internal_user_ids(raw):
            if not isinstance(raw, (list, tuple)):
                raise UserError(_("Recipients must be a list of users."))
            ids = []
            for value in raw[:500]:
                try:
                    user_id = int(value)
                except (TypeError, ValueError):
                    continue
                if user_id > 0 and user_id not in ids:
                    ids.append(user_id)
            users = self.env["res.users"].search([
                ("id", "in", ids), ("share", "=", False), ("active", "=", True),
            ])
            valid = set(users.ids)
            return [user_id for user_id in ids if user_id in valid]

        for key in ("shared_user_ids", "digest_user_ids"):
            if key in vals:
                write_vals[key] = [(6, 0, _internal_user_ids(vals.get(key) or []))]
        self.write(write_vals)
        if density in ("comfortable", "compact"):
            layout = self._active_layout()
            if layout:
                layout.density = density
        return self.get_settings()

    def get_item_data(self, item_ids, options=None):
        """Refresh a subset of items (used by lazy load and live refresh)."""
        self.ensure_one()
        options = self._analysis_options(options)
        items = self.item_ids.filtered(lambda i: i.id in set(item_ids))
        return [self._analysis_payload(item, options) for item in items]

    def get_item_window_action(self, item_id, domain=None, label=None):
        """Return configured Odoo action with clicked widget scope layered on.

        Action/model/group checks run as current user. Client may propose a
        clicked domain, but it must be valid, bounded, and remains subject to
        destination model ACLs and record rules.
        """
        self.ensure_one()
        item = self._owned_item(item_id)
        action = item.window_action_id.exists()
        if item.click_action != "action" or not action:
            raise UserError(_("This widget has no Odoo action configured."))
        if not item.datasource_id or action.res_model != item.datasource_id.model_name:
            raise UserError(_("Configured action no longer matches this widget's model."))

        action_group_field = "group_ids" if "group_ids" in action._fields else "groups_id"
        action_groups = action[action_group_field] if action_group_field in action._fields \
            else self.env["res.groups"]
        user = self.env.user
        user_group_field = next((name for name in (
            "all_group_ids", "group_ids", "groups_id") if name in user._fields), None)
        user_groups = user[user_group_field] if user_group_field else self.env["res.groups"]
        if action_groups and not (action_groups & user_groups):
            raise AccessError(_("You may not open this Odoo action."))
        Model = self.env[action.res_model]
        if hasattr(Model, "has_access"):
            readable = Model.has_access("read")
        else:
            readable = Model.check_access_rights("read", raise_exception=False)
        if not readable:
            raise AccessError(_("You may not read this action's model."))

        clicked = domain if isinstance(domain, list) else []
        if len(repr(clicked)) > 20000:
            raise UserError(_("Clicked filter is too large."))
        try:
            clicked = _normal_domain(clicked)
        except (AssertionError, TypeError, ValueError):
            raise UserError(_("Clicked filter is invalid."))
        try:
            configured = safe_eval(
                action.domain or "[]", action._get_eval_context(action))
            configured = _normal_domain(configured or [])
        except Exception:  # noqa: BLE001 - bad legacy action domain must not 500
            configured = []

        result = action.sudo()._get_action_dict()
        result["domain"] = _and_domains([configured, clicked])
        if label:
            result["name"] = "%s · %s" % (
                item.title or action.name or _("Records"), str(label)[:120])
        result["target"] = "current"
        return result

    # -- server PDF report ---------------------------------------------------
    def _fmt_num(self, value, fmt="compact"):
        """Mirror the client number format for the server-rendered PDF."""
        v = value or 0.0
        if fmt == "plain":
            return "{:,.2f}".format(v).rstrip("0").rstrip(".")
        if fmt == "thousands":
            return "{:,.1f}K".format(v / 1000.0)
        if fmt == "millions":
            return "{:,.2f}M".format(v / 1000000.0)
        a = abs(v)
        if a >= 1e9:
            return "{:.1f}B".format(v / 1e9)
        if a >= 1e6:
            return "{:.1f}M".format(v / 1e6)
        if a >= 1e3:
            return "{:.1f}K".format(v / 1e3)
        return "{:,.0f}".format(v)

    # Mirrors static/src/measure_label.js: the percentage column is a SHARE only
    # for an additive aggregate. For an average / min / max / distinct count the
    # total-grain figure is itself an average (or a min, or a max), so the ratio
    # runs past 100% and must not be labelled as a share of the total.
    _PERCENT_ADDITIVE = ("sum", "count")
    _PERCENT_GRAIN = {
        "avg": "avg", "min": "min", "max": "max", "count_distinct": "distinct",
    }
    _PERCENT_SCOPE = {
        "percent_row": "row", "percent_column": "column", "percent_grand": "grand",
    }

    def _percent_suffix(self, calculation, aggregate=None):
        """Name the percentage companion column for a measure.

        `formula` keeps the share wording on purpose: a calculated measure may
        be additive (a + b over two sums) or not (a / b), and nothing here can
        tell which.
        """
        scope = self._PERCENT_SCOPE.get(calculation, "grand")
        grain = self._PERCENT_GRAIN.get(aggregate)
        if not grain or aggregate in self._PERCENT_ADDITIVE:
            return "%% %s" % scope
        return "%% of %s %s" % (scope, grain)

    def _payload_table(self, payload):
        """Flatten a list/chart/pivot payload for PDF and Excel exports.

        Percentage companions use same exact pivot margins as browser widget;
        raw record lists retain selected field headers and cell text.
        """
        if payload.get("record_list"):
            columns = [{
                "label": col.get("label") or col.get("name") or "Field",
                "numeric": col.get("type") in ("integer", "float", "monetary"),
            } for col in payload.get("columns", [])]
            rows = []
            for row in payload.get("rows", []):
                rows.append([
                    cell.get("value", 0) if cell.get("type") in
                    ("integer", "float", "monetary") else cell.get("text", "")
                    for cell in row.get("cells", [])
                ])
            return {"columns": columns, "rows": rows}

        keys = payload.get("measure_keys", [])
        labels = {s.get("key"): s.get("label") for s in payload.get("series", [])}
        labels.update(payload.get("measure_labels") or {})
        calculations = (payload.get("measure_calculations") or {}) \
            if payload.get("category") in ("table", "pivot") else {}
        aggregates = payload.get("measure_aggregates") or {}
        descriptors = []
        for key in keys:
            label = labels.get(key) or key
            descriptors.append({"key": key, "label": label, "numeric": True})
            calculation = calculations.get(key)
            if calculation and calculation != "none":
                suffix = self._percent_suffix(calculation, aggregates.get(key))
                descriptors.append({
                    "key": key, "label": "%s · %s" % (label, suffix),
                    "numeric": True, "percentage": True,
                    "calculation": calculation,
                })

        pivot = payload.get("category") == "pivot"
        has_col = bool(pivot and payload.get("has_col"))
        if pivot:
            columns = [{"label": payload.get("row_dim_label") or "Rows"}]
            if has_col:
                columns.append({"label": payload.get("col_dim_label") or "Columns"})
        else:
            columns = [{"label": "Category"}]
        columns.extend(descriptors)

        def _skey(value):
            if value is None:
                return "∅"
            if value is False:
                return "false"
            if value is True:
                return "true"
            return str(value)

        def _ratio(value, denominator):
            return (float(value or 0) / float(denominator or 0)) if denominator else 0.0

        rows = []
        for row in payload.get("rows", []):
            row_labels = row.get("labels") or []
            if pivot:
                cells = [row_labels[0] if row_labels else ""]
                if has_col:
                    cells.append(row_labels[1] if len(row_labels) > 1 else "")
            else:
                cells = [" / ".join(str(label) for label in row_labels
                                    if label not in (None, ""))]
            row_values = row.get("values") or {}
            row_keys = row.get("keys") or []
            for descriptor in descriptors:
                value = row_values.get(descriptor["key"], 0) or 0
                calculation = descriptor.get("calculation")
                if not calculation:
                    cells.append(value)
                    continue
                denominator = (payload.get("grand_total") or {}).get(descriptor["key"], 0)
                if pivot and calculation == "percent_row":
                    denominator = ((payload.get("row_totals") or {}).get(
                        _skey(row_keys[0] if row_keys else None), {}) or {}).get(
                            descriptor["key"], 0)
                elif pivot and calculation == "percent_column" and has_col:
                    denominator = ((payload.get("col_totals") or {}).get(
                        _skey(row_keys[1] if len(row_keys) > 1 else None), {}) or {}).get(
                            descriptor["key"], 0)
                cells.append(_ratio(value, denominator))
            rows.append(cells)
        return {"columns": columns, "rows": rows}

    def _report_data(self, options=None):
        """A render-friendly list of blocks for the QWeb PDF: KPI numbers, data
        tables (charts / list / pivot) and content. Numbers are pre-formatted so
        the template stays declarative and wkhtmltopdf renders pure HTML."""
        self.ensure_one()
        options = self._analysis_options(
            self.env.context.get("eh_board_options") if options is None else options)
        blocks = []
        for item in self.item_ids:
            payload = self._analysis_payload(item, options)
            title = item.title or item.item_type
            fmt = payload.get("number_format", "compact")
            if payload.get("error"):
                blocks.append({"title": title, "kind": "error", "text": payload["error"]})
            elif payload.get("category") == "content":
                blocks.append({"title": title, "kind": "content",
                               "html": payload.get("content", "")})
            elif payload.get("category") == "kpi":
                unit = payload.get("unit") or ""
                value = self._fmt_num(payload.get("value", 0), fmt)
                if unit:
                    value = "%s %s" % (value, unit)
                if (payload.get("currency") or {}).get("code"):
                    value = "%s %s" % (payload["currency"]["code"], value)
                blk = {"title": title, "kind": "kpi", "value": value}
                if payload.get("target"):
                    blk["target"] = self._fmt_num(payload["target"], fmt)
                blocks.append(blk)
            else:
                table = self._payload_table(payload)
                columns = [column.get("label", "Value")
                           for column in table.get("columns", [])]
                rows = []
                for source_row in table.get("rows", []):
                    formatted = []
                    for index, value in enumerate(source_row):
                        column = table["columns"][index]
                        if column.get("percentage"):
                            formatted.append("{:.1f}%".format(float(value or 0) * 100))
                        elif column.get("numeric"):
                            formatted.append(self._fmt_num(value, fmt))
                        else:
                            formatted.append(str(value or ""))
                    rows.append(formatted)
                blocks.append({"title": title, "kind": "table",
                               "columns": columns, "rows": rows})
            blocks[-1]["description"] = item.description or ""
            blocks[-1]["warning"] = payload.get("warning") or ""
            status = payload.get("source_status") or {}
            blocks[-1]["last_success"] = status.get("last_success") or ""
        return blocks

    def get_item_drilled(self, item_id, path, options=None):
        """Payload for one widget drilled to the given click path (breadcrumb)."""
        self.ensure_one()
        options = self._analysis_options(options)
        item = self.item_ids.filtered(lambda i: i.id == item_id)
        if not item:
            return {"id": item_id, "error": "Unknown widget."}
        return item.get_drilled_payload(path or [], options or {})

    def get_item_decomp(self, item_id, path, options=None):
        """One level of a decomposition tree for the given widget + click path."""
        self.ensure_one()
        item = self.item_ids.filtered(lambda i: i.id == item_id)
        if not item:
            return {"nodes": [], "error": "Unknown widget."}
        return item.get_decomp(path or [], options or {})

    # -- insights -----------------------------------------------------------
    def get_insights(self, options=None):
        """Plain-language read-outs of each data widget - offline and always on.
        A BYO-key LLM can later rewrite these through the same seam."""
        self.ensure_one()
        options = self._analysis_options(options)
        out = []
        for item in self.item_ids:
            if not item.datasource_id:
                continue
            path = options["drill_paths"].get(str(item.id))
            item_options = item._drill_options(path, options)
            payload = self._analysis_payload(item, options)
            text = item._insight_text(item_options, payload)
            if text:
                if payload.get("warning"):
                    text = "%s %s" % (payload["warning"], text)
                if (payload.get("currency") or {}).get("code"):
                    text += " (%s)" % payload["currency"]["code"]
                out.append({"title": item.title or item.item_type, "text": text})
            # Key-influencers-lite: the biggest single driver of the measure.
            inf = item._influencer_text(item_options)
            if inf:
                out.append({"title": (item.title or item.item_type) + " · top contributor", "text": inf})
        return out

    @api.model
    def ai_available(self):
        """Client passthrough: is the optional BYO-key LLM configured?"""
        return self.env["eh.board.ai"].ai_available()

    def get_ai_insights(self, options=None):
        """Offline-first insights, optionally rewritten into an executive
        narrative by the customer's own LLM. The offline list is ALWAYS
        returned; the narrative is a best-effort extra that silently degrades.

        Only verified, already-computed facts are sent to the LLM - never raw
        record rows, credentials, the database name, or any SQL."""
        self.ensure_one()
        options = self._analysis_options(options)
        insights = self.get_insights(options)
        result = {"source": "offline", "narrative": "", "insights": insights}
        result["scope"] = self._analysis_scope(options)
        AI = self.env["eh.board.ai"]
        if not insights or not AI.ai_available():
            return result
        facts = ["%s: %s" % (i["title"], i["text"]) for i in insights]
        narrative = AI._narrate(facts)
        if narrative:
            cfg = AI._provider_config()
            result.update({
                "source": "llm",
                "narrative": narrative,
                "provider": cfg.get("provider"),
            })
        return result

    def _as_owner(self):
        """This dashboard bound to its owner's environment, so automated
        aggregation (snapshots, digests) respects the owner's record rules
        instead of leaking data as superuser."""
        self.ensure_one()
        owner = self.owner_id
        if owner and owner.active and owner.id != self.env.uid:
            return self.with_user(owner)
        return self

    # -- snapshots + digest -------------------------------------------------
    def capture_snapshot(self):
        """Record each data widget's headline value with a timestamp."""
        self.ensure_one()
        Snap = self.env["eh.board.snapshot"]
        now = fields.Datetime.now()
        for item in self.item_ids:
            if not item.datasource_id:
                continue
            value = item._headline_value()
            if value is None:
                continue
            Snap.create({
                "dashboard_id": self.id, "item_id": item.id,
                "value": value, "captured_on": now,
                "label": item.title or item.item_type})
        return True

    def save_digest_view(self, options=None, preset="all"):
        """Save the current view for scheduled delivery, preserving relative dates."""
        self.ensure_one()
        self._require_edit()
        normalized = self._analysis_options(options)
        if preset not in ("all", "custom"):
            probe = self.item_ids[:1]
            if not probe or not probe._preset_range(preset):
                raise UserError(_("Choose a valid date range."))
            normalized.pop("date_range", None)
        self.digest_view = {"preset": preset, "options": normalized}
        return True

    def _scheduled_analysis_options(self):
        saved = self.digest_view or {}
        options = dict(saved.get("options") or {})
        selected = options.get("company_ids") or self.with_context(active_test=False).company_ids.ids or self.env.companies.ids
        options["company_ids"] = [cid for cid in selected if cid in self.env.companies.ids]
        preset = saved.get("preset") or self.default_date_preset or "all"
        if preset not in ("all", "custom") and self.item_ids:
            span = self.item_ids[:1]._preset_range(preset)
            if span:
                options["date_range"] = {"start": span[0], "end": span[1]}
        return self._analysis_options(options)

    def send_digest(self):
        """Render a separate saved-view report under each recipient's rights.

        Recipient addresses come only from configured internal users. A user
        without access gets no report, rather than another user's figures.
        """
        self.ensure_one()
        self._require_edit()
        from markupsafe import escape
        first_mail_id = False
        recipients = self.digest_user_ids or self.owner_id
        for recipient in recipients:
            if not recipient.active or not recipient.email or recipient.share:
                continue
            scoped = self.with_user(recipient).with_context(
                allowed_company_ids=recipient.company_ids.ids,
                tz=recipient.tz or "UTC", lang=recipient.lang or "en_US")
            try:
                options = scoped._scheduled_analysis_options()
                scope = scoped._analysis_scope(options)
            except (AccessError, UserError):
                _logger.info("eh_board digest skipped: recipient %s cannot access board %s",
                             recipient.id, self.id)
                continue
            attachments = []
            try:
                # A savepoint keeps PDF failures from aborting subsequent recipients.
                with self.env.cr.savepoint():
                    report = scoped.env.ref("eh_board.action_report_eh_board_dashboard").with_context(
                        eh_board_options=options)
                    pdf, _kind = report._render_qweb_pdf(report.report_name, scoped.ids)
                    att = self.env["ir.attachment"].create({
                        "name": "%s.pdf" % self.name, "type": "binary",
                        "raw": pdf, "mimetype": "application/pdf"})
                    attachments = [att.id]
            except Exception:
                _logger.info("eh_board digest PDF unavailable for board %s", self.id)
            texts = scoped._digest_texts()
            body = "<p>%s</p><p>%s</p>" % (escape(texts["ready"]), escape(scope["label"]))
            if not attachments:
                body += "<p>%s</p>" % escape(texts["fallback"])
            mail = self.env["mail.mail"].sudo().create({
                "subject": texts["subject"],
                "body_html": body, "email_to": recipient.email,
                "attachment_ids": [(6, 0, attachments)],
            })
            try:
                mail.send()
            except Exception:
                _logger.info("eh_board digest queued")
            first_mail_id = first_mail_id or mail.id
        return first_mail_id

    def _digest_texts(self):
        """Resolve mail text in the recipient environment on every Odoo series."""
        return {
            "ready": _("Your dashboard %s is ready.", self.name or ""),
            "subject": _("Dashboard: %s", self.name or ""),
            "fallback": _("PDF could not be generated. Open the dashboard to view your figures."),
        }

    @api.model
    def _cron_send_digests(self):
        now = fields.Datetime.now()
        for dash in self.search([("digest_enabled", "=", True)]):
            # An archived (or missing) regular owner makes _as_owner() fall
            # through to the cron's SUPERUSER env, which would email full-database
            # figures with every record rule bypassed. Skip those - a digest must
            # never leak data the owner could not see. A board owned by the system
            # user (no narrower identity) is left to send normally.
            owner = dash.owner_id
            if owner and not owner.active and owner.id != SUPERUSER_ID:
                _logger.info("eh_board digest skipped: dashboard %s owner inactive", dash.id)
                continue
            if not dash._digest_due(now):
                continue
            # Savepoint per board: a late failure rolls back only this board's
            # mail/attachment rows, not every digest already prepared this run.
            try:
                # Render + send as the owner so the emailed figures respect the
                # owner's record rules, not the superuser cron's.
                with self.env.cr.savepoint():
                    mail_id = dash._as_owner().send_digest()
                    if mail_id:
                        dash.digest_last_sent_on = now
            except Exception:  # noqa: BLE001
                _logger.exception("eh_board digest skipped for %s", dash.id)
        return True

    def _digest_due(self, now=None):
        """Return whether this board's local schedule is due exactly once.

        Cron runs hourly. Frequency, weekday/month-day, and hour belong to each
        board; last-sent time prevents repeats after restarts or delayed workers.
        Owner timezone defines local schedule, while stored datetimes remain UTC.
        """
        self.ensure_one()
        now_utc = fields.Datetime.to_datetime(now or fields.Datetime.now())
        if now_utc.tzinfo:
            now_aware = now_utc.astimezone(pytz.UTC)
        else:
            now_aware = pytz.UTC.localize(now_utc)
        timezone_name = (self.owner_id.tz if self.owner_id else None) \
            or self.env.user.tz or "UTC"
        try:
            timezone = pytz.timezone(timezone_name)
        except pytz.UnknownTimeZoneError:
            timezone = pytz.UTC
        local_now = now_aware.astimezone(timezone)
        if local_now.hour < max(0, min(self.digest_hour or 0, 23)):
            return False

        last_date = None
        if self.digest_last_sent_on:
            last_utc = fields.Datetime.to_datetime(self.digest_last_sent_on)
            if not last_utc.tzinfo:
                last_utc = pytz.UTC.localize(last_utc)
            last_date = last_utc.astimezone(timezone).date()

        today = local_now.date()
        if self.digest_frequency == "daily":
            target = today
        elif self.digest_frequency == "monthly":
            last_day = calendar.monthrange(today.year, today.month)[1]
            target = today.replace(day=min(max(self.digest_month_day or 1, 1), last_day))
            if today < target:
                return False
        else:
            week_start = today.fromordinal(today.toordinal() - today.weekday())
            target = week_start.fromordinal(
                week_start.toordinal() + int(self.digest_weekday or "0"))
            if today < target:
                return False
        return not last_date or last_date < target

    # -- templates ----------------------------------------------------------
    def get_templates(self):
        """Available templates for the in-board gallery picker."""
        return self.env["eh.board.template"].gallery()

    def apply_template(self, template_id):
        """Create a new dashboard from a template and return an action to open it."""
        if not self.can_build():
            raise AccessError(_("Only a dashboard builder can create a dashboard."))
        tmpl = self.env["eh.board.template"].browse(template_id)
        if not tmpl.exists():
            return {"error": "Unknown template."}
        return tmpl.apply_and_open()

    def _readable_field_metadata(self, field):
        """Resolve metadata without granting access to the underlying data field."""
        metadata = field.sudo()
        if not metadata:
            return metadata
        metadata.ensure_one()
        model_name = metadata.model_id.model
        if model_name not in self.env:
            raise AccessError(_("This field is not available with your current access rights."))
        Model = self.env[model_name]
        if hasattr(Model, "check_access"):
            Model.check_access("read")
        else:
            Model.check_access_rights("read")
        if metadata.name not in Model.fields_get([metadata.name], attributes=["type"]):
            raise AccessError(_("This field is not available with your current access rights."))
        return metadata

    def _definition_payload(self):
        """Portable, secret-free board definition used by templates/backups."""
        self.ensure_one()
        layout = self._active_layout()
        grid = (layout.grid if layout else {}) or {}
        items = []
        for index, item in enumerate(self.item_ids):
            g = grid.get(str(item.id), {})
            spec = {
                "ref": "widget_%s" % index,
                "type": item.item_type, "title": item.title or "",
                "x": g.get("x", 0), "y": g.get("y", 0),
                "w": g.get("w", 4), "h": g.get("h", 6),
            }
            scalar_fields = (
                "accent", "tile_style", "icon", "content", "domain", "subtitle",
                "description", "list_mode", "date_granularity", "sort_mode",
                "sort_order", "include_archived", "record_limit_visibility",
                "record_limit", "data_label_type", "color_mode", "chart_options",
                "conditional_rules", "show_legend", "show_values", "show_grid",
                "semi_circle", "stacked", "smooth", "goal_value", "combo_line",
                "cumulative", "fill_gaps", "group_others", "click_action",
                "default_date_filter",
            )
            for key in scalar_fields:
                value = item[key]
                if (value not in (None, False, "", [], {})
                        or item._fields[key].type == "boolean"):
                    spec[key] = value
            if item.datasource_id:
                source = item.datasource_id
                spec["source"] = {
                    "ref": "source_%s" % source.id,
                    "name": source.name,
                    "provider": source.provider_type,
                    "model": source.model_name,
                }
                if source.provider_type == "orm":
                    spec["model"] = source.model_name
                elif source.provider_type == "join":
                    spec["source"]["config"] = source._guided_portable_config() \
                        if (source.config or {}).get("guided_query") else source._join_config()
                elif source._is_tabular_source():
                    spec["source"]["columns"] = [{
                        "name": column.name, "label": column.label,
                        "dtype": column.dtype, "sequence": column.sequence,
                    } for column in source.column_ids]
                    spec["source"]["requires_file"] = True
                    remote_kind = source.provider_type if source.provider_type in ("rest", "sheets") \
                        else (source.config or {}).get("requires_remote")
                    if remote_kind in ("rest", "sheets"):
                        # Import produces a disconnected column-preserving placeholder.
                        # Reconnection requires the destination administrator's approval.
                        spec["source"]["provider"] = "file"
                        spec["source"]["requires_remote"] = remote_kind
                elif source.provider_type == "sql":
                    # Query text may contain commercially sensitive table names or
                    # literals. Portable JSON never exports it; reconnect in vault.
                    spec["source"]["requires_sql"] = True
                spec["measures"] = [{
                    "verb": m.aggregate, "field": self._readable_field_metadata(m.field_id).name if m.field_id else None,
                    "column": m.column_id.name if m.column_id else None,
                    "label": m.name,
                    "number_format": m.number_format, "unit": m.unit or "",
                    "target": m.target_value or 0.0, "compare_mode": m.compare_mode,
                    "target_schedule": m.target_schedule or [],
                    "as_line": bool(m.as_line),
                    "table_calculation": m.table_calculation or "none",
                    "formula": m.formula or "", "multiplier": m.multiplier or 1.0,
                    # ISO code is portable across databases; numeric ids are not.
                    "currency": m.currency_id.name if m.currency_id else False,
                } for m in item.measure_ids]
                if item.target_dashboard_id:
                    spec["target_dashboard"] = item.target_dashboard_id.name
                if item.window_action_id:
                    external = item.window_action_id.get_external_id().get(
                        item.window_action_id.id)
                    if external:
                        spec["window_action_xmlid"] = external
                if item.item_type == "list":
                    spec["list_mode"] = item.list_mode or "grouped"
                    spec["list_fields"] = (item.list_field_order or []) \
                        if source._is_tabular_source() \
                        else [self._readable_field_metadata(field).name for field in item._ordered_list_fields()]
                if item.primary_dimension_id:
                    spec["dimension"] = self._readable_field_metadata(item.primary_dimension_id).name
                if item.secondary_dimension_id:
                    spec["secondary_dimension"] = self._readable_field_metadata(item.secondary_dimension_id).name
                if item.date_granularity:
                    spec["granularity"] = item.date_granularity
                if item.date_filter_field_id:
                    spec["date_field"] = self._readable_field_metadata(item.date_filter_field_id).name
                if item.sort_field_id:
                    spec["sort_field"] = self._readable_field_metadata(item.sort_field_id).name
                if item.primary_column_id:
                    spec["primary_column"] = item.primary_column_id.name
                if item.secondary_column_id:
                    spec["secondary_column"] = item.secondary_column_id.name
                if item.drill_ids:
                    spec["drills"] = [{
                        "field": self._readable_field_metadata(drill.field_id).name,
                        "chart_type": drill.chart_type or None,
                        "sort": drill.sort or "value_desc",
                        "limit": drill.limit or 0,
                    } for drill in item.drill_ids]
            items.append(spec)
        filters = [{
            "name": f.name,
            "type": f.filter_type,
            "model": self._readable_field_metadata(f.field_id).model_id.model if f.field_id else None,
            "field": self._readable_field_metadata(f.field_id).name if f.field_id else None,
            "date_preset": f.date_preset,
            "default": f.default_value or {},
            "options": f.options or {},
        } for f in self.filter_ids]
        result = {
            "schema": "eh_board/v1",
            "name": self.name,
            "settings": {
                "description": self.description or "",
                "palette": self.palette or "default",
                "default_date_preset": self.default_date_preset or "all",
                "refresh_mode": self.refresh_mode if self.refresh_mode != "live" else "interval",
                "refresh_interval": self.refresh_interval or 60,
                "is_kiosk": bool(self.is_kiosk),
                "density": layout.density if layout else "comfortable",
            },
            "items": items,
            "filters": filters,
        }
        result["scorecard"] = self._scorecard_portable_definition({
            item.id: spec["ref"] for item, spec in zip(self.item_ids, items)})
        return result

    def save_as_template(self, name=None):
        """Serialise live board into reusable, version-portable template."""
        self.ensure_one()
        self._require_edit()
        payload = self._definition_payload()
        tmpl = self.env["eh.board.template"].create({
            "name": name or ("%s template" % self.name),
            "category": "general", "is_predefined": False,
            "description": "Saved from %s" % self.name,
            "payload": payload,
        })
        return {"template_id": tmpl.id, "name": tmpl.name}

    def export_definition(self):
        self.ensure_one()
        return self._definition_payload()

    @api.model
    def import_definition(self, payload):
        """Create a draft board from bounded portable JSON; never import secrets."""
        if not (self.env.su
                or self.env.user.has_group("eh_board.group_board_builder")):
            from odoo.exceptions import AccessError
            raise AccessError(_("Only a dashboard builder can import a dashboard."))
        if not isinstance(payload, dict) or payload.get("schema") != "eh_board/v1":
            raise UserError(_("Not an eh_board/v1 dashboard backup."))
        import json
        if len(json.dumps(payload)) > 2 * 1024 * 1024:
            raise UserError(_("Dashboard backup is larger than 2 MB."))
        if len(payload.get("items") or []) > 200:
            raise UserError(_("Dashboard backup exceeds the 200-widget limit."))
        Template = self.env["eh.board.template"]
        template = Template.create({
            "name": payload.get("name") or _("Imported dashboard"),
            "category": "general",
            "description": _("Temporary import record"),
            "payload": payload,
        })
        try:
            dashboard = template.create_from_template()
        finally:
            template.unlink()
        return {"dashboard_id": dashboard.id, "name": dashboard.name}

    def save_layout(self, grid, density=None):
        """Persist the grid geometry onto the active layout version."""
        self.ensure_one()
        if not self._can_edit():
            from odoo.exceptions import AccessError
            raise AccessError(_("You may not change this dashboard's layout."))
        layout = self._active_layout()
        if not layout:
            layout = self.env["eh.board.layout.version"].create({
                "dashboard_id": self.id,
                "name": "Default",
                "is_active": True,
                "is_default": True,
            })
            self.active_layout_id = layout
        layout.write({
            "grid": self._clean_grid(grid),
            **({"density": density} if density in ("comfortable", "compact") else {}),
        })
        return True

    def _clean_grid(self, grid):
        """Bound and normalise client geometry before storing it as JSON."""
        self.ensure_one()
        if not isinstance(grid, dict):
            raise UserError(_("Dashboard layout must be an object."))
        owned_ids = set(self.item_ids.ids)
        clean = {}
        for raw_id, raw_geometry in list(grid.items())[:200]:
            try:
                item_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            if item_id not in owned_ids or not isinstance(raw_geometry, dict):
                continue

            def _integer(name, default, minimum, maximum):
                try:
                    value = int(raw_geometry.get(name, default))
                except (TypeError, ValueError):
                    value = default
                return max(minimum, min(value, maximum))

            width = _integer("w", 4, 1, 12)
            x = _integer("x", 0, 0, 11)
            width = min(width, 12 - x)
            clean[str(item_id)] = {
                "x": x,
                "y": _integer("y", 0, 0, 10000),
                "w": width,
                "h": _integer("h", 6, 1, 200),
            }
        return clean

    def commit_layout(self, previous_grid=None, previous_density=None):
        """Checkpoint pre-edit arrangement before finishing an edit session.

        Dragging autosaves active layout for crash safety. Client sends snapshot
        captured before first move; this method stores it as immutable history
        and links active version to it. No-op when arrangement did not change.
        """
        self.ensure_one()
        if not self._can_edit():
            from odoo.exceptions import AccessError
            raise AccessError(_("You may not change this dashboard's layout."))
        layout = self._active_layout()
        if not layout:
            return False
        previous_grid = self._clean_grid(previous_grid or {})
        previous_density = previous_density or layout.density
        if previous_grid == (layout.grid or {}) and previous_density == layout.density:
            return False
        stamp = fields.Datetime.context_timestamp(
            self, fields.Datetime.now()).strftime("%Y-%m-%d %H:%M")
        history = self.env["eh.board.layout.version"].create({
            "dashboard_id": self.id,
            "name": _("Before edit · %s") % stamp,
            "is_active": False,
            "is_default": False,
            "company_id": layout.company_id.id,
            "grid": previous_grid,
            "density": previous_density,
            "parent_id": layout.parent_id.id,
        })
        layout.parent_id = history
        return history.id

    def get_layout_history(self, limit=30):
        """Bounded layout timeline for in-board restore dialog."""
        self.ensure_one()
        versions = self.layout_version_ids.sorted(
            key=lambda version: (version.create_date or fields.Datetime.now(), version.id),
            reverse=True)[:max(1, min(int(limit or 30), 100))]
        active = self._active_layout()
        return [{
            "id": version.id,
            "name": version.name,
            "created": fields.Datetime.to_string(version.create_date),
            "active": version == active,
            "density": version.density,
            "widgets": len(version.grid or {}),
        } for version in versions]

    def restore_layout(self, version_id):
        """Restore selected version while preserving current state as history."""
        self.ensure_one()
        if not self._can_edit():
            from odoo.exceptions import AccessError
            raise AccessError(_("You may not restore this dashboard's layout."))
        target = self.layout_version_ids.filtered(lambda version: version.id == version_id)
        if not target:
            raise UserError(_("That layout version does not belong to this dashboard."))
        target = target[:1]
        active = self._active_layout()
        if not active:
            target.write({"is_active": True})
            self.active_layout_id = target
            return {"grid": target.grid or {}, "density": target.density}
        if target != active:
            stamp = fields.Datetime.context_timestamp(
                self, fields.Datetime.now()).strftime("%Y-%m-%d %H:%M")
            snapshot = self.env["eh.board.layout.version"].create({
                "dashboard_id": self.id,
                "name": _("Before restore · %s") % stamp,
                "is_active": False,
                "company_id": active.company_id.id,
                "grid": active.grid or {},
                "density": active.density,
                "parent_id": active.parent_id.id,
            })
            active.write({
                "grid": target.grid or {},
                "density": target.density,
                "parent_id": snapshot.id,
            })
        return {"grid": active.grid or {}, "density": active.density}

    # ----------------------------------------------------------- builder API
    def _create_item_from_builder(self, vals):
        """Create an item from the in-canvas builder shortcut vals.

        ``vals`` may carry ``model_id`` + ``measure`` + ``dimension`` shortcuts,
        in which case a data source and measure are spun up so the user never
        leaves the canvas. Returns the created ``eh.board.item`` record.
        """
        self.ensure_one()
        self._require_edit()
        # A widget's dashboard_id is NOT NULL; refuse a non-persisted (NewId)
        # dashboard with a clear message instead of a raw not-null violation.
        if not self.id:
            raise UserError(_("Save the dashboard before adding a widget."))
        item_vals = self._builder_item_vals(vals)
        return self.env["eh.board.item"].create(item_vals)

    def _builder_item_vals(self, vals):
        """Translate builder shortcut vals into eh.board.item write values,
        spinning up the data source + measures. Handles a single measure or a
        list, a secondary dimension, and field-name -> id conversions."""
        vals = dict(vals)
        Item = self.env["eh.board.item"]
        model_id = vals.pop("model_id", None)
        source_id = vals.pop("source_id", None)
        measure = vals.pop("measure", None)
        measures_supplied = "measures" in vals
        measures = vals.pop("measures", None)
        list_fields = vals.pop("list_fields", None)
        dimension = vals.pop("dimension", None)
        secondary = vals.pop("secondary_dimension", None)
        granularity = vals.pop("granularity", None)
        drill_field = vals.pop("drill_field", None)
        drill_fields = vals.pop("drill_fields", None)
        date_field = vals.pop("date_field", None)
        sort_field = vals.pop("sort_field", None)
        target_dashboard_id = vals.pop("target_dashboard_id", None)
        window_action_id = vals.pop("window_action_id", None)
        # Public builder seam accepts scalar presentation/query options only.
        # Relational ids are resolved below against this exact dashboard/model;
        # never trust raw datasource_id, measure_ids, field ids or dashboard_id.
        builder_fields = {
            "item_type", "title", "subtitle", "description", "sequence",
            "accent", "tile_style", "icon", "content", "domain",
            "list_mode", "sort_mode", "sort_order", "record_limit",
            "record_limit_visibility", "include_archived", "show_legend",
            "show_values", "show_grid", "semi_circle", "stacked", "smooth",
            "goal_value", "combo_line", "data_label_type", "cumulative",
            "fill_gaps", "group_others", "click_action", "default_date_filter",
            "conditional_rules", "color_mode", "chart_options", "show_trend",
        }
        item_vals = {k: v for k, v in vals.items() if k in builder_fields}
        # Authoritative: set dashboard_id AFTER the client-vals merge so a stray
        # dashboard_id in vals can never null it out.
        item_vals["dashboard_id"] = self.id
        if item_vals.get("item_type") not in ("richtext", "todo"):
            source = self._owned_source(source_id) if source_id else (
                self._ensure_datasource(model_id) if model_id else False)
        else:
            source = False
        click_action = item_vals.get("click_action") or "records"
        item_vals.update({"target_dashboard_id": False, "window_action_id": False})
        if click_action == "dashboard":
            try:
                target_id = int(target_dashboard_id or 0)
            except (TypeError, ValueError):
                target_id = 0
            target = self.search([
                ("id", "=", target_id), ("id", "!=", self.id),
            ], limit=1)
            if not target:
                raise UserError(_("Choose a visible destination dashboard."))
            item_vals["target_dashboard_id"] = target.id
        elif click_action == "action":
            try:
                action_id = int(window_action_id or 0)
            except (TypeError, ValueError):
                action_id = 0
            action = self.env["ir.actions.act_window"].browse(action_id).exists()
            source_model = source.model_name if source else False
            if not action or not source_model or action.res_model != source_model:
                raise UserError(_("Choose an Odoo action for this widget's model."))
            item_vals["window_action_id"] = action.id
        if source:
            if source.provider_type in ("rest", "sheets") and source.dashboard_id != self:
                raise AccessError(_("Remote snapshots can only be used on their owning dashboard."))
            if source.provider_type == "orm":
                model_id = source.model_id.id
            item_vals["datasource_id"] = source.id
            specs = measures if isinstance(measures, list) and measures else (
                [measure] if measure else [])
            if source._is_tabular_source():
                ids = [self._ensure_tabular_measure(source, m).id for m in specs if m]
            elif source.provider_type == "orm":
                ids = [self._ensure_measure(source, m).id for m in specs if m]
            else:
                ids = []
            if ids or measures_supplied:
                item_vals["measure_ids"] = [(6, 0, ids)]
            if list_fields is not None and model_id:
                names = []
                for name in list_fields:
                    if isinstance(name, str) and name not in names:
                        names.append(name)
                    if len(names) == 12:
                        break
                list_records = self.env["ir.model.fields"].sudo().search([
                    ("model_id", "=", model_id),
                    ("name", "in", names),
                    ("store", "=", True),
                    ("ttype", "not in", ("one2many", "many2many", "binary")),
                ])
                visible = self.env[source.model_name].fields_get(names, attributes=["type"])
                by_name = {field.name: field.id for field in list_records if field.name in visible}
                valid_names = [name for name in names if name in by_name]
                item_vals["list_field_ids"] = [
                    (6, 0, [by_name[name] for name in valid_names])]
                item_vals["list_field_order"] = valid_names
            if source._is_tabular_source():
                columns = {column.name: column for column in source.column_ids}
                if list_fields is not None:
                    names = []
                    for name in list_fields:
                        if isinstance(name, str) and name in columns and name not in names:
                            names.append(name)
                        if len(names) == 12:
                            break
                    item_vals["list_field_ids"] = [(5, 0, 0)]
                    item_vals["list_field_order"] = names
                item_vals["primary_column_id"] = columns.get(dimension).id \
                    if dimension in columns else False
                item_vals["secondary_column_id"] = columns.get(secondary).id \
                    if secondary in columns else False
            elif model_id and dimension:
                item_vals["primary_dimension_id"] = self._field_id(model_id, dimension)
            if model_id and secondary:
                item_vals["secondary_dimension_id"] = self._field_id(model_id, secondary)
            chain = drill_fields if isinstance(drill_fields, list) else (
                [drill_field] if drill_field else [])
            if chain and model_id:
                drill_ids = [self._field_id(model_id, name) for name in chain[:8]]
                drill_ids = [field_id for field_id in drill_ids if field_id]
                item_vals["drill_field_id"] = drill_ids[0] if drill_ids else False
                item_vals["drill_ids"] = [(5, 0, 0)] + [
                    (0, 0, {"field_id": field_id, "sequence": (index + 1) * 10})
                    for index, field_id in enumerate(drill_ids)]
            if date_field and model_id:
                item_vals["date_filter_field_id"] = self._field_id(model_id, date_field)
            if sort_field and model_id:
                item_vals["sort_field_id"] = self._field_id(model_id, sort_field)
            if granularity:
                item_vals["date_granularity"] = granularity
        return item_vals

    def add_item(self, vals):
        self.ensure_one()
        item = self._create_item_from_builder(vals)
        return {"meta": item._meta(), "payload": item.get_payload()}

    def smart_build(self, model_id, replace=False):
        """Build a useful dashboard from one readable model, deterministically.

        This is intentionally not an LLM guessing schema semantics.  Stored
        field types plus a small preference table select dates, dimensions and
        measures; every resulting widget still passes through the same secured
        builder seam as a manually-authored widget.  One RPC either completes
        atomically or rolls back, so users never receive a half-built canvas.
        """
        self.ensure_one()
        self._require_edit()
        try:
            model_id = int(model_id or 0)
        except (TypeError, ValueError):
            model_id = 0
        model = self.env["ir.model"].sudo().browse(model_id).exists()
        if not model or model.model not in self.env:
            raise UserError(_("Choose a valid Odoo model."))
        # Performs concrete/transient and current-user read checks before any
        # metadata is used or records are created.
        self._ensure_datasource(model.id)

        Field = self.env["ir.model.fields"].sudo()
        available = Field.search([
            ("model_id", "=", model.id), ("store", "=", True),
            ("ttype", "not in", ("one2many", "many2many", "binary")),
        ])
        by_name = {field.name: field for field in available}
        Runtime = self.env[model.model]
        visible = Runtime.fields_get(attributes=["type"])
        available = available.filtered(lambda field: field.name in visible)
        by_name = {field.name: field for field in available}

        def _preferred(records, names, type_order=()):
            name_rank = {name: index for index, name in enumerate(names)}
            type_rank = {name: index for index, name in enumerate(type_order)}
            return records.sorted(key=lambda field: (
                name_rank.get(field.name, len(name_rank) + 10),
                type_rank.get(field.ttype, len(type_rank) + 10),
                field.field_description or field.name,
            ))

        dates = _preferred(
            available.filtered(lambda field: field.ttype in ("date", "datetime")),
            ("date_order", "invoice_date", "date", "order_date", "create_date",
             "write_date", "date_done", "date_start", "date_deadline"),
            ("date", "datetime"))
        dimension_names = (
            "state", "stage_id", "state_id", "team_id", "product_id",
            "partner_id", "category_id", "categ_id", "user_id",
            "salesperson_id", "country_id", "city", "company_id", "type",
        )
        ignored_dimension_names = {
            "id", "display_name", "name", "create_uid", "write_uid",
            "commercial_company_name", "email_normalized", "complete_name",
        }
        semantic_chars = {
            "city", "channel", "source", "medium", "campaign", "ref",
            "code", "country_code", "state_code", "status", "type",
            "category", "department",
        }
        raw_dimensions = _preferred(
            available.filtered(lambda field: field.ttype in (
                "selection", "many2one", "boolean", "char")
                and field.name not in ignored_dimension_names
                and not field.name.startswith((
                    "message_", "activity_", "website_", "access_"))
                and (field.ttype != "char" or field.name in semantic_chars
                     or field.name.endswith(("_code", "_type", "_category", "_status")))),
            dimension_names,
            ("selection", "many2one", "boolean", "char"))

        def _dimension_quality(field):
            """Return bounded observed cardinality; metadata alone picks junk.

            Three groups are enough to distinguish a useful segment from an
            empty/singleton field without loading records into Python.
            """
            try:
                with self.env.cr.savepoint():
                    groups = grouped_read(
                        Runtime, [], [field.name], [], limit=3)
                    values = [row[0] for row in groups]
            except Exception:  # a model-specific non-groupable field is skipped
                return 0, False
            meaningful = any(value not in (False, None, "") for value in values)
            return len(groups), meaningful

        diverse_dimensions = Field.browse()
        populated_dimensions = Field.browse()
        for field in raw_dimensions[:36]:
            cardinality, meaningful = _dimension_quality(field)
            if not meaningful:
                continue
            populated_dimensions |= field
            if cardinality >= 2:
                diverse_dimensions |= field
        dimensions = _preferred(
            diverse_dimensions or populated_dimensions,
            dimension_names,
            ("selection", "many2one", "boolean", "char"))
        ignored_numbers = {
            "id", "sequence", "color", "priority", "message_attachment_count",
            "message_follower_count", "activity_exception_icon",
            "partner_latitude", "partner_longitude", "geo_latitude",
            "geo_longitude", "currency_rate", "company_currency_rate",
        }
        number_names = (
            "amount_total", "price_total", "balance", "amount", "total",
            "amount_untaxed", "price_subtotal", "margin", "revenue", "cost",
            "qty_invoiced", "product_uom_qty", "quantity", "qty", "duration",
            "hours", "list_price", "standard_price", "credit_limit",
        )
        raw_numbers = _preferred(
            available.filtered(lambda field: field.ttype in (
                "integer", "float", "monetary") and field.name not in ignored_numbers
                and not field.name.endswith(("_rank", "_count"))
                and not field.name.startswith((
                    "message_", "activity_", "website_", "access_"))),
            number_names,
            ("monetary", "float", "integer"))
        useful_numbers = Field.browse()
        for field in raw_numbers[:36]:
            try:
                with self.env.cr.savepoint():
                    populated = Runtime.search_count(
                        [(field.name, "!=", 0)], limit=1)
            except Exception:  # model-specific search implementations may refuse a field
                populated = 0
            if populated:
                useful_numbers |= field
        numbers = _preferred(
            useful_numbers, number_names, ("monetary", "float", "integer"))

        date = dates[:1]
        category = dimensions[:1]
        secondary = dimensions[1:2]
        tertiary = dimensions[2:3]
        primary_number = numbers[:1]
        secondary_number = numbers[1:2]
        current_currency = self.env.company.currency_id
        records_label = _("Records")
        yes_label = _("Yes")
        no_label = _("No")

        def _measure(field=None, verb=None, compare="none", calculation="none"):
            if not field:
                return {
                    "verb": "count", "field": "", "label": records_label,
                    "number_format": "compact", "compare_mode": compare,
                    "table_calculation": calculation,
                }
            currency_like = field.ttype == "monetary" or (
                by_name.get("currency_id")
                and any(token in field.name for token in (
                    "amount", "price", "total", "subtotal", "balance",
                    "debit", "credit", "revenue", "cost", "margin")))
            return {
                "verb": verb or "sum", "field": field.name,
                "label": field.field_description or field.name,
                "number_format": "compact", "compare_mode": compare,
                "table_calculation": calculation,
                "currency_id": current_currency.id if currency_like else False,
            }

        count_measure = _measure(compare="prev_period" if date else "none")
        main_measure = _measure(
            primary_number, compare="prev_period" if date else "none")
        average_measure = _measure(primary_number, verb="avg") \
            if primary_number else False

        base = {
            "model_id": model.id,
            "domain": "[]",
            "date_field": date.name if date else "",
            "click_action": "records",
            "show_legend": True,
            "show_values": True,
            "show_grid": True,
            "fill_gaps": True,
        }
        planned = []

        def _plan(geometry, **values):
            planned.append((geometry, {**base, **values}))

        def _top_segments(field, limit=3):
            """Build compact executive segments from observed top groups."""
            if not field:
                return []
            try:
                with self.env.cr.savepoint():
                    rows = grouped_read(
                        Runtime, [], [field.name], ["__count"],
                        order="__count DESC", limit=max(limit * 2, 6))
            except Exception:
                return []
            selection = {}
            if field.ttype == "selection":
                description = Runtime.fields_get(
                    [field.name], attributes=["selection"]).get(field.name, {})
                selection = dict(description.get("selection") or [])
            segments = []
            for value, count in rows:
                if field.ttype != "boolean" and value in (False, None, ""):
                    continue
                if hasattr(value, "ids"):
                    if not value:
                        continue
                    domain_value = value.id
                    label = value.display_name
                elif field.ttype == "many2one" and isinstance(value, (tuple, list)):
                    # Odoo 16 read_group returns ``(id, display_name)`` while
                    # newer _read_group versions return a recordset.
                    if not value or not value[0]:
                        continue
                    domain_value = value[0]
                    label = value[1] if len(value) > 1 else str(value[0])
                elif field.ttype == "boolean":
                    domain_value = bool(value)
                    label = yes_label if value else no_label
                else:
                    domain_value = value
                    label = selection.get(value, str(value))
                segments.append({
                    "title": "%s: %s" % (
                        field.field_description or field.name, label),
                    "domain": repr([(field.name, "=", domain_value)]),
                    "count": count,
                })
                if len(segments) >= limit:
                    break
            return segments

        # Executive row: volume, value, and average.  Empty-schema models still
        # get a valid count tile rather than an unusable blank dashboard.
        segments = _top_segments(category) if not primary_number else []
        executive_width = {1: 12, 2: 6, 3: 4, 4: 3}[1 + len(segments)]
        _plan((0, 0, executive_width, 4), item_type="tile",
              title=_("Record volume"),
              measures=[count_measure], accent="blue", tile_style="soft")
        for index, segment in enumerate(segments, start=1):
            _plan((index * executive_width, 0, executive_width, 4),
                  item_type="tile", title=segment["title"],
                  domain=segment["domain"], measures=[count_measure],
                  accent=("mint", "violet", "amber")[index - 1],
                  tile_style="soft")
        if primary_number:
            _plan((3, 0, 3, 4), item_type="kpi",
                  title=primary_number.field_description or _("Total value"),
                  measures=[main_measure], accent="mint", tile_style="soft")
            _plan((6, 0, 3, 4), item_type="tile",
                  title=_("Average %s") % (primary_number.field_description
                                             or primary_number.name),
                  measures=[average_measure], accent="violet", tile_style="outline")
        if secondary_number:
            _plan((9, 0, 3, 4), item_type="tile",
                  title=secondary_number.field_description or _("Secondary value"),
                  measures=[_measure(secondary_number)], accent="amber",
                  tile_style="soft")

        chart_measure = main_measure if primary_number else count_measure
        if date:
            _plan((0, 4, 8 if category else 12, 6), item_type="area",
                  title=_("%s over time") % chart_measure["label"],
                  measures=[chart_measure], dimension=date.name,
                  granularity="month", smooth=True, show_values=False,
                  color_mode="measure", accent="blue")
        if category:
            drill_chain = [field.name for field in (secondary | tertiary)]
            interaction = {
                "click_action": "drill" if drill_chain else "records",
                "drill_fields": drill_chain,
            }
            _plan((8 if date else 0, 4, 4 if date else 6, 6),
                  item_type="doughnut",
                  title=_("%s by %s") % (
                      chart_measure["label"], category.field_description),
                  measures=[chart_measure], dimension=category.name,
                  record_limit=10, group_others=True, accent="violet",
                  **interaction)
            _plan((0, 10, 6, 6), item_type="bar",
                  title=_("Top %s") % (category.field_description or category.name),
                  measures=[chart_measure], dimension=category.name,
                  sort_mode="value_desc", record_limit=12, group_others=True,
                  accent="mint", **interaction)
            country = dimensions.filtered(
                lambda field: field.ttype == "many2one"
                and field.relation == "res.country")[:1]
            if country:
                _plan((6, 10, 6, 6), item_type="map",
                      title=_("%s by country") % chart_measure["label"],
                      measures=[chart_measure], dimension=country.name,
                      accent="teal")
            elif secondary:
                _plan((6, 10, 6, 7), item_type="pivot",
                      title=_("%s analysis") % (model.name or _("Model")),
                      measures=[{
                          **chart_measure,
                          "table_calculation": "percent_grand",
                      }], dimension=category.name,
                      secondary_dimension=secondary.name, record_limit=20,
                      accent="indigo")
            elif secondary_number:
                _plan((6, 10, 6, 6), item_type="scatter",
                      title=_("%s vs %s") % (
                          primary_number.field_description,
                          secondary_number.field_description),
                      measures=[main_measure, _measure(secondary_number)],
                      dimension=category.name, record_limit=30, accent="rose")

        rec_name = self.env[model.model]._rec_name or "name"
        list_names = []
        for field in (
                by_name.get(rec_name), date, category, secondary,
                primary_number, secondary_number, by_name.get("state"),
                by_name.get("company_id")):
            if field and field.name not in list_names:
                list_names.append(field.name)
        if not list_names and by_name.get("id"):
            list_names.append("id")
        bottom = max((geo[1] + geo[3] for geo, _vals in planned), default=3)
        _plan((0, bottom, 12, 7), item_type="list",
              title=_("%s details") % (model.name or _("Records")),
              list_mode="records", list_fields=list_names[:8], measures=[],
              record_limit=50, sort_mode="field",
              sort_field=date.name if date else (rec_name if rec_name in by_name else "id"),
              sort_order="desc", accent="slate")

        if replace:
            self.item_ids.unlink()
            self.filter_ids.unlink()
        old_grid = {} if replace else dict(
            (self._active_layout().grid if self._active_layout() else {}) or {})
        y_offset = 0
        if old_grid:
            y_offset = max(
                int(geometry.get("y", 0)) + int(geometry.get("h", 4))
                for geometry in old_grid.values())
        created = self.env["eh.board.item"]
        grid = dict(old_grid)
        base_sequence = len(self.item_ids)
        for sequence, (geometry, values) in enumerate(planned, start=1):
            item = self._create_item_from_builder({
                **values, "sequence": (base_sequence + sequence) * 10,
            })
            created |= item
            x, y, width, height = geometry
            grid[str(item.id)] = {
                "x": x, "y": y + y_offset, "w": width, "h": height,
            }

        # Add global controls once.  Field filters remain semantic and therefore
        # safely scope widgets from compatible models only.
        existing_fields = set(self.filter_ids.mapped("field_id").ids)
        if date and date.id not in existing_fields:
            self.env["eh.board.filter"].create({
                "dashboard_id": self.id,
                "name": date.field_description or _("Date"),
                "filter_type": "date", "field_id": date.id,
                "date_preset": "this_year",
            })
        if (category and category.ttype in ("selection", "many2one", "boolean")
                and category.id not in existing_fields):
            self.env["eh.board.filter"].create({
                "dashboard_id": self.id,
                "name": category.field_description or category.name,
                "filter_type": "field", "field_id": category.id,
            })
        self.save_layout(grid, "comfortable")
        return {
            "created": len(created),
            "model": model.name or model.model,
            "item_ids": created.ids,
        }

    def get_item_config(self, item_id):
        """Return the builder config of an existing item so the luxury builder
        can open pre-filled for editing (instead of the raw backend form)."""
        self.ensure_one()
        self._require_edit()
        item = self._owned_item(item_id)
        measures = [{
            "verb": m.aggregate,
            "label": m.name or "",
            "field": (m.column_id.name if m.column_id else m.field_name) or "",
            "number_format": m.number_format,
            "unit": m.unit or "",
            "formula": m.formula or "",
            "as_line": bool(m.as_line),
            "table_calculation": m.table_calculation or "none",
            "multiplier": m.multiplier or 1.0,
            "currency_id": m.currency_id.id if m.currency_id else False,
            "target": m.target_value or 0.0,
            "target_schedule": m.target_schedule or [],
            "compare_mode": m.compare_mode or "none",
        } for m in item.measure_ids]
        first = item.measure_ids[:1]
        return {
            "item_type": item.item_type,
            "title": item.title or "",
            "source_id": item.datasource_id.id if item.datasource_id else False,
            "provider": item.provider_type or "",
            "model_id": item.datasource_id.model_id.id if item.datasource_id else False,
            "model_name": item.datasource_id.model_name if item.datasource_id else "",
            "domain": item.domain or "[]",
            "measures": measures,
            "verb": first.aggregate if first else "count",
            "measure_field": (first.field_name or "") if first else "",
            "dimension": (item.primary_column_id.name if item.primary_column_id
                          else item.primary_dimension_id.name
                          if item.primary_dimension_id else ""),
            "secondary_dimension": (
                item.secondary_column_id.name if item.secondary_column_id
                else item.secondary_dimension_id.name
                if item.secondary_dimension_id else ""),
            "list_mode": item.list_mode or "grouped",
            "list_fields": (item.list_field_order or []) if item._is_tabular() \
                else item._ordered_list_fields().mapped("name"),
            "granularity": item.date_granularity or "month",
            "accent": item._resolved_accent(),
            "tile_style": item.tile_style or "soft",
            "content": item.content or "",
            "sort_mode": item.sort_mode or "value_desc",
            "sort_field": item.sort_field_id.name if item.sort_field_id else "",
            "sort_order": item.sort_order or "desc",
            "record_limit": item.record_limit or 0,
            "record_limit_visibility": item.record_limit_visibility,
            "include_archived": item.include_archived,
            "number_format": first.number_format if first else "compact",
            "target": first.target_value if first else 0.0,
            "compare": (first.compare_mode or "none") if first else "none",
            "target_schedule": (first.target_schedule or []) if first else [],
            "show_legend": item.show_legend,
            "show_values": item.show_values,
            "show_grid": item.show_grid,
            "semi_circle": item.semi_circle,
            "stacked": item.stacked,
            "smooth": item.smooth,
            "goal_value": item.goal_value,
            "combo_line": item.combo_line,
            "data_label_type": item.data_label_type or "value",
            "cumulative": item.cumulative,
            "fill_gaps": item.fill_gaps,
            "group_others": item.group_others,
            "click_action": item.click_action or "records",
            "target_dashboard_id": item.target_dashboard_id.id
            if item.target_dashboard_id else False,
            "window_action_id": item.window_action_id.id
            if item.window_action_id else False,
            "window_action_name": item.window_action_id.name
            if item.window_action_id else "",
            "drill_field": item.drill_field_id.name if item.drill_field_id else "",
            "drill_fields": item.drill_ids.mapped("field_name"),
            "date_field": item.date_filter_field_id.name if item.date_filter_field_id else "",
            "default_date_filter": item.default_date_filter or "none",
            "description": item.description or "",
            "conditional_rules": item.conditional_rules or [],
            "color_mode": item.color_mode or "theme",
            "chart_options": item.chart_options or {},
            "show_trend": item.show_trend,
        }

    def update_item_from_builder(self, item_id, vals):
        """Apply builder config back onto an existing item (in-canvas edit)."""
        self.ensure_one()
        self._require_edit()
        item = self._owned_item(item_id)
        write_vals = self._builder_item_vals(vals)
        write_vals.pop("dashboard_id", None)
        target_source = self.env["eh.board.datasource"].browse(
            write_vals.get("datasource_id") or item.datasource_id.id).exists()
        if vals.get("item_type") in ("richtext", "todo"):
            write_vals.update({
                "datasource_id": False, "measure_ids": [(5, 0, 0)],
                "primary_dimension_id": False, "secondary_dimension_id": False,
                "primary_column_id": False, "secondary_column_id": False,
                "list_field_ids": [(5, 0, 0)], "list_field_order": [],
                "drill_ids": [(5, 0, 0)], "drill_field_id": False,
            })
            target_source = self.env["eh.board.datasource"]
        is_tabular = bool(target_source and target_source._is_tabular_source())
        if is_tabular:
            write_vals.update({
                "primary_dimension_id": False,
                "secondary_dimension_id": False,
                "list_field_ids": [(5, 0, 0)],
            })
        else:
            write_vals.update({"primary_column_id": False, "secondary_column_id": False})
        if target_source.provider_type in ("join", "sql"):
            write_vals.update({
                "primary_dimension_id": False,
                "secondary_dimension_id": False,
                "primary_column_id": False,
                "secondary_column_id": False,
                "measure_ids": [(5, 0, 0)],
                "list_mode": "grouped",
            })
        # explicit clears when the builder sent an empty dimension
        if not vals.get("dimension") and not is_tabular:
            write_vals["primary_dimension_id"] = False
        if not vals.get("secondary_dimension") and not is_tabular:
            write_vals["secondary_dimension_id"] = False
        if not vals.get("sort_field"):
            write_vals["sort_field_id"] = False
        if (vals.get("click_action") != "drill"
                or not (vals.get("drill_fields") or vals.get("drill_field"))):
            write_vals["drill_field_id"] = False
            write_vals["drill_ids"] = [(5, 0, 0)]
        item.write(write_vals)
        return {"meta": item._meta(), "payload": item.get_payload()}

    def _ensure_datasource(self, model_id):
        Source = self.env["eh.board.datasource"]
        model = self.env["ir.model"].sudo().browse(int(model_id or 0)).exists()
        if not model or model.model not in self.env:
            raise UserError(_("Choose a valid Odoo model."))
        Model = self.env[model.model]
        if Model._abstract or Model._transient:
            raise UserError(_("That model cannot be used as a dashboard source."))
        if hasattr(Model, "check_access"):
            Model.check_access("read")
        else:
            Model.check_access_rights("read")
        existing = Source.search(
            [("model_id", "=", model_id), ("provider_type", "=", "orm"),
             ("dashboard_id", "=", self.id)], limit=1)
        if existing:
            return existing
        return Source.create({
            "name": model.name or model.model,
            "provider_type": "orm",
            "model_id": model_id,
            "dashboard_id": self.id,
        })

    def _ensure_measure(self, source, measure):
        Measure = self.env["eh.board.measure"]
        field_name = measure.get("field")
        verb = measure.get("verb", "count")
        if verb not in ("count", "count_distinct", "sum", "avg", "min", "max", "formula"):
            raise UserError(_("Unsupported aggregation: %s", verb))
        field_id = self._field_id(source.model_id.id, field_name) if field_name else False
        field = self.env["ir.model.fields"].sudo().browse(field_id).exists() if field_id else False
        if verb not in ("count", "formula"):
            if not field or not field.store:
                raise UserError(_("Choose a stored field for %s.", verb))
            numeric = field.ttype in ("integer", "float", "monetary")
            scalar = field.ttype not in ("one2many", "many2many", "binary")
            if verb in ("sum", "avg", "min", "max") and not numeric:
                raise UserError(_("%s requires a numeric field.", verb.title()))
            if verb == "count_distinct" and not scalar:
                raise UserError(_("Distinct count requires a scalar field."))
        fmt = measure.get("number_format") or "compact"
        if fmt not in ("plain", "thousands", "millions", "compact"):
            fmt = "compact"
        unit = str(measure.get("unit") or "")[:24]
        try:
            target = float(measure.get("target") or 0.0)
        except (TypeError, ValueError):
            target = 0.0
        if not math.isfinite(target):
            target = 0.0
        compare = measure.get("compare_mode") or "none"
        if compare not in ("none", "prev_period", "prev_year"):
            compare = "none"
        schedule = Measure._sanitize_target_schedule(
            measure.get("target_schedule") or [])
        formula = str(measure.get("formula") or "")[:512]
        as_line = bool(measure.get("as_line"))
        table_calculation = measure.get("table_calculation") or "none"
        if table_calculation not in (
                "none", "percent_grand", "percent_row", "percent_column"):
            table_calculation = "none"
        try:
            multiplier = float(measure.get("multiplier") or 1.0)
        except (TypeError, ValueError):
            multiplier = 1.0
        if not math.isfinite(multiplier) or abs(multiplier) > 1e12:
            multiplier = 1.0
        try:
            currency_id = int(measure.get("currency_id") or 0) or False
        except (TypeError, ValueError):
            currency_id = False
        if currency_id:
            currency = self.env["res.currency"].browse(currency_id).exists()
            currency_id = currency.id if currency else False
        # Dedup on the full presentation, not just the aggregation: a measure
        # with a target or a different format/unit is a distinct measure, so two
        # widgets never share (and clobber) each other's goal or formatting.
        existing = source.measure_ids.filtered(
            lambda m: m.aggregate == verb
            and (m.field_id.id if m.field_id else False) == (field_id or False)
            and (m.number_format or "compact") == fmt
            and (m.unit or "") == unit
            and float(m.target_value or 0.0) == target
            and (m.compare_mode or "none") == compare
            and (m.target_schedule or []) == schedule
            and bool(m.as_line) == as_line
            and (m.table_calculation or "none") == table_calculation
            and (m.formula or "") == formula
            and float(m.multiplier or 1.0) == multiplier
            and (m.currency_id.id if m.currency_id else False) == currency_id)
        if existing:
            return existing[:1]
        name = str(measure.get("label") or (
            "Calculated" if verb == "formula"
            else (field_name.replace("_", " ").title() if field_name else "Records")))[:120]
        return Measure.create({
            "name": name,
            "datasource_id": source.id,
            "field_id": field_id or False,
            "aggregate": verb,
            "formula": formula,
            "number_format": fmt,
            "unit": unit,
            "target_value": target,
            "compare_mode": compare,
            "target_schedule": schedule,
            "as_line": as_line,
            "table_calculation": table_calculation,
            "multiplier": multiplier,
            "currency_id": currency_id,
        })

    def _ensure_tabular_measure(self, source, measure):
        """Create/reuse one bounded file-column measure from visual builder."""
        Measure = self.env["eh.board.measure"]
        verb = measure.get("verb") or "count"
        if verb not in ("count", "count_distinct", "sum", "avg", "min", "max", "formula"):
            raise UserError(_("Unsupported aggregation: %s", verb))
        column_name = measure.get("field")
        column = source.column_ids.filtered(
            lambda candidate: candidate.name == column_name)[:1]
        if verb not in ("count", "formula") and not column:
            raise UserError(_("Choose a file column for %s.", verb))
        if verb in ("sum", "avg", "min", "max") and column.dtype != "number":
            raise UserError(_("%s requires a numeric file column.", verb.title()))
        fmt = measure.get("number_format") or "compact"
        if fmt not in ("plain", "thousands", "millions", "compact"):
            fmt = "compact"
        unit = str(measure.get("unit") or "")[:24]
        formula = str(measure.get("formula") or "")[:512]
        calculation = measure.get("table_calculation") or "none"
        if calculation not in ("none", "percent_grand", "percent_row", "percent_column"):
            calculation = "none"
        compare = measure.get("compare_mode") or "none"
        if compare not in ("none", "prev_period", "prev_year"):
            compare = "none"
        schedule = Measure._sanitize_target_schedule(
            measure.get("target_schedule") or [])
        try:
            multiplier = float(measure.get("multiplier") or 1.0)
        except (TypeError, ValueError):
            multiplier = 1.0
        if not math.isfinite(multiplier) or abs(multiplier) > 1e12:
            multiplier = 1.0
        try:
            target = float(measure.get("target") or 0.0)
        except (TypeError, ValueError):
            target = 0.0
        if not math.isfinite(target):
            target = 0.0
        try:
            currency_id = int(measure.get("currency_id") or 0) or False
        except (TypeError, ValueError):
            currency_id = False
        if currency_id:
            currency = self.env["res.currency"].browse(currency_id).exists()
            currency_id = currency.id if currency else False
        values = {
            "aggregate": verb,
            "column_id": column.id if column else False,
            "formula": formula,
            "number_format": fmt,
            "unit": unit,
            "target_value": target,
            "compare_mode": compare,
            "target_schedule": schedule,
            "as_line": bool(measure.get("as_line")),
            "table_calculation": calculation,
            "multiplier": multiplier,
            "currency_id": currency_id,
        }
        existing = source.measure_ids.filtered(lambda candidate:
            candidate.aggregate == values["aggregate"]
            and candidate.column_id.id == (values["column_id"] or False)
            and (candidate.formula or "") == values["formula"]
            and (candidate.number_format or "compact") == values["number_format"]
            and (candidate.unit or "") == values["unit"]
            and float(candidate.target_value or 0.0) == values["target_value"]
            and (candidate.compare_mode or "none") == values["compare_mode"]
            and (candidate.target_schedule or []) == values["target_schedule"]
            and bool(candidate.as_line) == values["as_line"]
            and (candidate.table_calculation or "none") == values["table_calculation"]
            and float(candidate.multiplier or 1.0) == values["multiplier"]
            and candidate.currency_id.id == (values["currency_id"] or False))
        if existing:
            return existing[:1]
        default_name = "Calculated" if verb == "formula" else (
            column.label if column else "Records")
        return Measure.create({
            "name": str(measure.get("label") or default_name)[:120],
            "datasource_id": source.id,
            **values,
        })

    def _field_id(self, model_id, field_name):
        if not field_name:
            return False
        model = self.env["ir.model"].sudo().browse(model_id).exists()
        if not model or model.model not in self.env:
            return False
        Model = self.env[model.model]
        if hasattr(Model, "check_access"):
            Model.check_access("read")
        else:
            Model.check_access_rights("read")
        if field_name not in Model.fields_get([field_name], attributes=["type"]):
            raise AccessError(_("This field is not available with your current access rights."))
        # Resolve metadata IDs only after normal model and field permission checks.
        field = self.env["ir.model.fields"].sudo().search(
            [("model_id", "=", model_id), ("name", "=", field_name),
             ("store", "=", True),
             ("ttype", "not in", ("one2many", "many2many", "binary"))],
            limit=1)
        return field.id or False

    def update_item(self, item_id, vals):
        self.ensure_one()
        self._require_edit()
        item = self._owned_item(item_id)
        # Legacy lightweight seam: presentation only. Data relationships and
        # ownership are changed exclusively through update_item_from_builder().
        allowed = {
            "title", "subtitle", "description", "sequence", "accent",
            "tile_style", "icon", "show_legend", "show_values", "show_grid",
            "semi_circle", "stacked", "smooth", "data_label_type", "color_mode",
            "chart_options", "show_trend",
        }
        item.write({k: v for k, v in dict(vals or {}).items() if k in allowed})
        return {"meta": item._meta(), "payload": item.get_payload()}

    def delete_item(self, item_id):
        self.ensure_one()
        self._require_edit()
        self._owned_item(item_id).unlink()
        return True

    def duplicate_item(self, item_id):
        """Clone a widget (copy config, place it just after the original)."""
        self.ensure_one()
        self._require_edit()
        item = self._owned_item(item_id)
        clone = item.copy({
            "title": (item.title or item.item_type) + " (copy)",
            "sequence": item.sequence + 1,
        })
        return {"meta": clone._meta(), "payload": clone.get_payload()}

    def add_filter(self, vals):
        """Create a global field filter from the in-canvas add-filter dialog."""
        self.ensure_one()
        self._require_edit()
        vals = dict(vals or {})
        try:
            model_id = int(vals.get("model_id") or 0)
        except (TypeError, ValueError):
            model_id = 0
        field_name = str(vals.get("field") or "")
        if not (model_id and field_name):
            return {"error": "Pick a model and a field."}
        model = self.env["ir.model"].sudo().browse(model_id).exists()
        if not model or model.model not in self.env or model.transient:
            return {"error": "Unknown model."}
        try:
            self.env[model.model].check_access_rights("read")
        except AccessError:
            return {"error": "You cannot read that model."}
        field = self.env["ir.model.fields"].sudo().search(
            [("model_id", "=", model_id), ("name", "=", field_name)], limit=1)
        field = self._readable_field_metadata(field)
        supported_types = {"boolean", "char", "date", "datetime", "integer",
                           "many2one", "selection"}
        if not field or field.ttype not in supported_types:
            return {"error": "Choose a searchable date, category, or scalar field."}
        runtime_field = self.env[model.model]._fields.get(field.name)
        if not runtime_field or (not runtime_field.store and not runtime_field.search):
            return {"error": "That field cannot be searched."}
        flt = self.env["eh.board.filter"].create({
            "dashboard_id": self.id,
            "name": vals.get("name") or field.field_description or field.name,
            "filter_type": "field",
            "field_id": field.id,
        })
        return {"filter": flt.spec()}

    def remove_filter(self, filter_id):
        self.ensure_one()
        self._require_edit()
        self._owned_filter(filter_id).unlink()
        return True

    def get_alerts(self):
        """Alert rules plus safe picker metadata for in-board management."""
        self.ensure_one()
        users = self.env["res.users"]
        if self._can_edit():
            users = users.search(
                [("share", "=", False), ("active", "=", True)], order="name")
        return {
            "can_edit": self._can_edit(),
            "items": [{
                "id": item.id,
                "name": item.title or item.item_type,
            } for item in self.item_ids if item.datasource_id],
            "users": [{"id": user.id, "name": user.name} for user in users],
            "alerts": [{
                "id": alert.id,
                "name": alert.name,
                "active": alert.active,
                "item_id": alert.item_id.id,
                "operator": alert.operator,
                "threshold": alert.threshold,
                "user_id": alert.user_id.id,
                "state": alert.state,
                "last_value": alert.last_value,
                "last_triggered_on": fields.Datetime.to_string(
                    alert.last_triggered_on) if alert.last_triggered_on else False,
            } for alert in self.alert_ids],
        }

    def save_alert(self, vals):
        """Create/update one threshold rule, scoped to exact dashboard/item."""
        self.ensure_one()
        self._require_edit()
        vals = dict(vals or {})
        item = self._owned_item(vals.get("item_id"))
        if not item.datasource_id:
            raise UserError(_("Choose a data widget for this alert."))
        operator = vals.get("operator") or "gt"
        if operator not in ("gt", "gte", "lt", "lte"):
            raise UserError(_("Unsupported alert operator."))
        try:
            threshold = float(vals.get("threshold") or 0.0)
        except (TypeError, ValueError):
            raise UserError(_("Enter a numeric threshold."))
        if not math.isfinite(threshold):
            raise UserError(_("Enter a finite threshold."))
        user = self.env["res.users"].browse(int(vals.get("user_id") or 0)).exists()
        if not user or user.share or not user.active:
            user = self.env.user
        alert_vals = {
            "name": str(vals.get("name") or item.title or _("Alert"))[:120],
            "active": bool(vals.get("active", True)),
            "dashboard_id": self.id,
            "item_id": item.id,
            "operator": operator,
            "threshold": threshold,
            "user_id": user.id,
        }
        alert_id = vals.get("id")
        if alert_id:
            alert = self._owned_alert(alert_id)
            # Editing condition re-arms rule; next cron evaluates fresh crossing.
            alert_vals["state"] = "armed"
            alert.write(alert_vals)
        else:
            alert = self.env["eh.board.alert"].create(alert_vals)
        return {"id": alert.id}

    def delete_alert(self, alert_id):
        self.ensure_one()
        self._require_edit()
        self._owned_alert(alert_id).unlink()
        return True

    def get_builder_source(self, source_id):
        """Return editable, provider-specific values for one canvas source.

        Generic source metadata deliberately excludes SQL text. This narrower
        endpoint returns it only after dashboard ownership, edit permission and
        SQL-admin permission have all been proved.
        """
        self.ensure_one()
        self._require_edit()
        source = self._owned_source(source_id)
        if source.dashboard_id != self:
            raise UserError(_(
                "Only a source owned by this dashboard can be edited here."
            ))
        result = self._source_meta(source)
        if source.provider_type in ("rest", "sheets") or result.get("requires_remote"):
            source._require_remote_admin()
            # Details and secrets use the dedicated administrator-only dialog.
            return result
        if source.provider_type == "file":
            result["filename"] = source.file_name or ""
            result["has_file"] = bool(source.file_data)
        elif source.provider_type == "join":
            config = source._join_config()
            left_model = source.join_left_model_id or self.env["ir.model"]._get(
                config.get("left_model") or "")
            right_model = source.join_right_model_id or self.env["ir.model"]._get(
                config.get("right_model") or "")
            left_measure = config.get("left_measure") or {}
            right_measure = config.get("right_measure") or {}
            result.update({
                "left_model_id": left_model.id or False,
                "right_model_id": right_model.id or False,
                "left_key": source.join_left_key or config.get("join_left") or "",
                "right_key": source.join_right_key or config.get("join_right") or "",
                "left_agg": source.join_left_agg or left_measure.get("verb") or "count",
                "right_agg": source.join_right_agg or right_measure.get("verb") or "count",
                "left_value": source.join_left_value or left_measure.get("field") or "",
                "right_value": source.join_right_value or right_measure.get("field") or "",
                "left_label": source.join_left_label or config.get("left_label") or "Left",
                "right_label": source.join_right_label or config.get("right_label") or "Right",
            })
        elif source.provider_type == "sql":
            if not (self.env.su
                    or self.env.user.has_group("eh_board.group_board_admin")):
                raise AccessError(_(
                    "Only a Dashboard Administrator can edit SQL sources."
                ))
            result["query"] = source.sql_query or ""
        else:
            raise UserError(_("This source type is not editable in the canvas."))
        return result

    def create_builder_source(self, vals):
        """Create or update File/Join/SQL source in visual workspace.

        RPC accepts narrow provider-specific fields, validates model/field
        access, bounds uploads/query text, and always owns source by this board.
        Passing ``source_id`` updates that exact owned source instead of making
        an anonymous duplicate. Credentials and arbitrary model values never
        cross this seam.
        """
        self.ensure_one()
        self._require_edit()
        vals = dict(vals or {})
        provider = vals.get("provider")
        if provider not in ("file", "join", "sql"):
            raise UserError(_("Choose File, Join, or Safe SQL."))
        source_id = vals.pop("source_id", False)
        source = self._owned_source(source_id) if source_id \
            else self.env["eh.board.datasource"]
        if source:
            if source.dashboard_id != self:
                raise UserError(_(
                    "Only a source owned by this dashboard can be edited here."
                ))
            if source.provider_type != provider:
                raise UserError(_("A data source type cannot be changed."))
        source_name = vals.get("name") or (source.name if source else False) \
            or _("New data source")
        source_vals = {
            "name": str(source_name)[:120],
            "provider_type": provider,
            "dashboard_id": self.id,
        }
        if provider == "file":
            encoded = vals.get("data") or ""
            if encoded:
                if isinstance(encoded, str) and "," in encoded[:200]:
                    encoded = encoded.split(",", 1)[1]
                if not isinstance(encoded, str) or len(encoded) > 28 * 1024 * 1024:
                    raise UserError(_("Dashboard files are limited to 20 MB."))
                try:
                    raw = base64.b64decode(encoded, validate=True)
                except (binascii.Error, ValueError):
                    raise UserError(_("The uploaded file is not valid base64 data."))
                if not raw or len(raw) > self.env["eh.board.datasource"]._MAX_FILE_BYTES:
                    raise UserError(_("Dashboard files are limited to 20 MB."))
                filename = str(vals.get("filename") or "data.csv")[:255]
                if not filename.lower().endswith(
                        (".csv", ".tsv", ".txt", ".xlsx", ".xlsm")):
                    raise UserError(_("Upload CSV, TSV, TXT, or XLSX data."))
                source_vals.update({"file_data": encoded, "file_name": filename})
            elif not source or not source.file_data:
                raise UserError(_("Choose a CSV or Excel file."))
        elif provider == "join":
            def _model(model_id):
                model = self.env["ir.model"].sudo().browse(int(model_id or 0)).exists()
                if not model or model.model not in self.env:
                    raise UserError(_("Choose two valid models for the join."))
                Model = self.env[model.model]
                if Model._abstract or Model._transient:
                    raise UserError(_("A transient/abstract model cannot be joined."))
                Model.check_access_rights("read")
                return model, Model

            left_model, Left = _model(vals.get("left_model_id"))
            right_model, Right = _model(vals.get("right_model_id"))

            def _field(Model, name, numeric=False):
                field = Model._fields.get(str(name or ""))
                if not field or not field.store \
                        or field.type in ("one2many", "many2many", "binary"):
                    raise UserError(_("Choose a stored scalar join field."))
                if numeric and field.type not in ("integer", "float", "monetary"):
                    raise UserError(_("Join value fields must be numeric."))
                return field

            left_key_name = str(vals.get("left_key") or "")
            right_key_name = str(vals.get("right_key") or "")
            left_key = _field(Left, left_key_name)
            right_key = _field(Right, right_key_name)

            def _namespace(model, name, field):
                if field.type == "many2one":
                    return field.comodel_name
                return model._name if name == "id" else field.type

            if (_namespace(Left, left_key_name, left_key)
                    != _namespace(Right, right_key_name, right_key)):
                raise UserError(_(
                    "Join fields are incompatible. Match the same related model "
                    "(for example partner_id to res.partner id) or same scalar type."))
            left_agg = vals.get("left_agg") or "count"
            right_agg = vals.get("right_agg") or "count"
            allowed_agg = ("count", "sum", "avg", "min", "max")
            if left_agg not in allowed_agg or right_agg not in allowed_agg:
                raise UserError(_("Unsupported join aggregation."))
            left_value = str(vals.get("left_value") or "")
            right_value = str(vals.get("right_value") or "")
            if left_agg != "count":
                _field(Left, left_value, numeric=True)
            else:
                left_value = ""
            if right_agg != "count":
                _field(Right, right_value, numeric=True)
            else:
                right_value = ""
            source_vals.update({
                "config": {},
                "join_left_model_id": left_model.id,
                "join_left_key": left_key_name,
                "join_left_agg": left_agg,
                "join_left_value": left_value,
                "join_left_label": str(vals.get("left_label") or left_model.name)[:80],
                "join_right_model_id": right_model.id,
                "join_right_key": right_key_name,
                "join_right_agg": right_agg,
                "join_right_value": right_value,
                "join_right_label": str(vals.get("right_label") or right_model.name)[:80],
            })
        else:
            if not (self.env.su
                    or self.env.user.has_group("eh_board.group_board_admin")):
                raise AccessError(_(
                    "Only a Dashboard Administrator can create or edit SQL sources."
                ))
            query = str(vals.get("query") if "query" in vals
                        else source.sql_query if source else "").strip()
            if len(query) > 20000:
                raise UserError(_("SQL query is limited to 20,000 characters."))
            problem = get_datasource("sql")._validate_sql(query.rstrip(";").strip())
            if problem:
                raise UserError(problem)
            source_vals["sql_query"] = query
        if source:
            source.write(source_vals)
        else:
            source = self.env["eh.board.datasource"].create(source_vals)
        if provider == "file" and encoded:
            source.action_parse_file()
        return self._source_meta(source)

    def get_builder_meta(self):
        """Models and their groupable / measurable fields for the add dialog."""
        self.ensure_one()
        self._require_edit()
        models = self.env["ir.model"].sudo().search([
            ("transient", "=", False),
            ("model", "not like", "ir.%"),
            ("model", "not like", "bus.%"),
        ])
        allowed = []
        for model in models:
            if model.model not in self.env:
                continue
            Model = self.env[model.model]
            # Include every concrete, queryable model - crucially the analytical
            # SQL-VIEW report models (sale.report, account.invoice.report,
            # pos.order.report, ...) which have _auto=False but a real table and
            # full _read_group support. Only ABSTRACT mixins (no table) are
            # excluded here; transient wizards are already filtered above.
            readable = Model.has_access("read") if hasattr(Model, "has_access") \
                else Model.check_access_rights("read", raise_exception=False)
            if not Model._abstract and not Model._transient and readable:
                allowed.append({"id": model.id, "model": model.model, "name": model.name})
        currencies = self.env["res.currency"].search(
            [("active", "=", True)], order="name")
        sources = self.env["eh.board.datasource"].search([
            ("active", "=", True),
            "|", ("dashboard_id", "=", self.id),
            ("item_ids.dashboard_id", "=", self.id),
        ], order="provider_type, name")
        return {
            "models": sorted(allowed, key=lambda m: m["name"]),
            "sources": [self._source_meta(source) for source in sources],
            "boards": [{"id": board.id, "name": board.name}
                       for board in self.search([
                           ("id", "!=", self.id)], order="sequence, name")],
            "can_sql": bool(self.env.su
                            or self.env.user.has_group("eh_board.group_board_admin")),
            "currencies": [{
                "id": currency.id,
                "code": currency.name,
                "symbol": currency.symbol or currency.name,
                "position": currency.position,
            } for currency in currencies],
        }

    def preview_item(self, vals):
        """Build a payload + meta from unsaved builder config, WITHOUT
        persisting. Creates real records inside a savepoint (so measures link
        and validation is exact), computes the payload, then rolls everything
        back. Drives the live preview in the add-widget builder."""
        self.ensure_one()
        item_type = vals.get("item_type", "bar")
        if (item_type not in ("richtext", "todo")
                and not (vals.get("model_id") or vals.get("source_id"))):
            return {"meta": None, "payload": {"error": "Choose a data source to preview."}}

        out = {"meta": None, "payload": {"error": "Configure a widget to preview it."}}

        class _Abort(Exception):
            pass

        try:
            with self.env.cr.savepoint():
                item = self._create_item_from_builder(vals)
                out = {"meta": item._meta(), "payload": item.get_payload()}
                raise _Abort()  # discard the preview records
        except _Abort:
            pass
        except Exception as err:  # noqa: BLE001 - preview never crashes the dialog
            out = {"meta": None, "payload": {"error": str(err)}}
        return out

    def get_model_fields(self, model_id):
        """Groupable dimensions and aggregatable measures for one model."""
        self.ensure_one()
        self._require_edit()
        model = self.env["ir.model"].sudo().browse(int(model_id or 0)).exists()
        if not model or model.model not in self.env:
            raise UserError(_("Unknown model."))
        Model = self.env[model.model]
        if hasattr(Model, "check_access"):
            Model.check_access("read")
        else:
            Model.check_access_rights("read")
        Fields = self.env["ir.model.fields"].sudo()
        visible = Model.fields_get(attributes=["type"])
        fields = Fields.search([("model_id", "=", model_id), ("store", "=", True)])
        fields = fields.filtered(lambda field: field.name in visible)
        dimensions, measures, columns = [], [], []
        for f in fields:
            if f.ttype in ("many2one", "selection", "date", "datetime", "boolean", "char"):
                dimensions.append({"name": f.name, "label": f.field_description,
                                   "ttype": f.ttype})
            if f.ttype in ("integer", "float", "monetary"):
                measures.append({"name": f.name, "label": f.field_description,
                                 "ttype": f.ttype})
            if f.ttype not in ("one2many", "many2many", "binary"):
                columns.append({"name": f.name, "label": f.field_description,
                                "ttype": f.ttype})
        return {
            "dimensions": sorted(dimensions, key=lambda x: x["label"] or x["name"]),
            "measures": sorted(measures, key=lambda x: x["label"] or x["name"]),
            "columns": sorted(columns, key=lambda x: x["label"] or x["name"]),
        }

    # --------------------------------------------------------------- actions
    def action_open_board(self):
        self.ensure_one()
        return {
            "type": "ir.actions.client",
            "tag": "eh_board.board",
            "name": self.name,
            "params": {"dashboard_id": self.id},
        }
