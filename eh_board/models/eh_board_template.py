# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
import logging

from odoo import fields, models, _
from odoo.exceptions import UserError

from ..lib.business_metrics import PACKS

_logger = logging.getLogger(__name__)


class EhBoardTemplate(models.Model):
    """A ready-made dashboard, predefined or captured from a live board.

    The vertical packs (Contacts, CRM/Sales, Accounting, Warehouse, Point of
    Sale and HR) ship as predefined templates: their payload names target models
    as strings, so a template stays inert until its base app is installed - which
    is how the one module can bundle every vertical without hard-depending on
    every app.
    """
    _name = "eh.board.template"
    _description = "Dashboard Template"
    _order = "category, sequence, name"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    category = fields.Selection(
        [("general", "General"), ("account", "Accounting"), ("crm", "Sales & CRM"),
         ("pos", "Point of Sale"), ("stock", "Inventory"), ("hr", "Human Resources"),
         ("web", "Website")], default="general")
    is_predefined = fields.Boolean()
    required_module = fields.Char(
        help="Technical name of the base app a vertical template needs "
             "(e.g. account). Blank for a general template.")
    description = fields.Text()
    payload = fields.Json(default=lambda self: {})
    business_pack_key = fields.Char(string="Business pack version", readonly=True, copy=False, index=True)

    def is_available(self):
        """True when the base app this template targets is installed."""
        self.ensure_one()
        if not self.required_module:
            return True
        module = self.env["ir.module.module"].sudo().search(
            [("name", "=", self.required_module)], limit=1)
        return bool(module) and module.state == "installed"

    # -- apply --------------------------------------------------------------
    def create_from_template(self):
        with self.env.cr.savepoint():
            return self._create_from_template()

    def _create_from_template(self):
        """Materialise a live dashboard from this template's payload.

        Every item is created through the same builder path a hand-built widget
        uses, so measures/datasources are deduped and record rules apply. Items
        whose model or field is absent on this database are skipped rather than
        failing the whole apply - which is how one pack works across versions.
        """
        self.ensure_one()
        if self.business_pack_key:
            # Business definitions are all-or-nothing: never silently replace a
            # missing financial metric with a partial or unrelated dashboard.
            with self.env.cr.savepoint():
                return self.env["eh.board.dashboard"]._build_business_pack(self.business_pack_key)
        if not self.is_available():
            raise UserError(_(
                "This template needs the %s app. Install it first.",
                self.required_module))
        payload = self.payload or {}
        if "scorecard" in payload and not isinstance(payload["scorecard"], dict):
            raise UserError(_("The portable scorecard definition is invalid."))
        Dashboard = self.env["eh.board.dashboard"]
        settings = payload.get("settings") or {}
        dash_vals = {
            "name": payload.get("name") or self.name,
            # Imports/templates never publish themselves or inherit sharing.
            "state": "draft",
            "description": settings.get("description") or "",
            "palette": settings.get("palette")
            if settings.get("palette") in ("default", "ocean", "sunset", "forest", "mono")
            else "default",
            "default_date_preset": settings.get("default_date_preset")
            if settings.get("default_date_preset") in (
                "all", "today", "this_week", "this_month", "this_quarter",
                "this_year", "wtd", "mtd", "qtd", "ytd", "last_month",
                "last_7", "last_30", "last_90") else "all",
            "refresh_mode": settings.get("refresh_mode")
            if settings.get("refresh_mode") in ("off", "interval") else "off",
            "refresh_interval": max(1, min(int(settings.get("refresh_interval") or 60), 86400)),
            "is_kiosk": bool(settings.get("is_kiosk")),
        }
        dash = Dashboard.create(dash_vals)
        grid = {}
        first_model = None
        source_cache = {}
        item_refs = {}
        for spec in payload.get("items", []):
            try:
                item = self._materialise_item(dash, spec, source_cache)
            except Exception as err:  # noqa: BLE001 - skip, never break the apply
                if (spec.get("business_metric_id") or payload.get("scorecard", {}).get("nodes")
                        or ((spec.get("source") or {}).get("config") or {}).get("guided_query")):
                    raise UserError(_("The saved widget could not be restored: %s", str(err))) from err
                _logger.info("eh_board template item skipped: %s", err)
                continue
            if not item:
                continue
            if spec.get("ref"):
                if not isinstance(spec["ref"], str) or spec["ref"] in item_refs:
                    raise UserError(_("Dashboard widget references must be unique strings."))
                item_refs[spec["ref"]] = item
            grid[str(item.id)] = {
                "x": spec.get("x", 0), "y": spec.get("y", 0),
                "w": spec.get("w", 4), "h": spec.get("h", 6)}
            if not first_model and spec.get("model"):
                first_model = spec.get("model")
        self.env["eh.board.layout.version"].create({
            "dashboard_id": dash.id, "name": "Default",
            "is_active": True, "is_default": True, "grid": grid,
            "density": settings.get("density")
            if settings.get("density") in ("comfortable", "compact") else "comfortable"})
        for flt in payload.get("filters", []):
            self._materialise_filter(dash, flt, first_model)
        dash._restore_portable_scorecard(payload.get("scorecard"), item_refs)
        return dash

    def _materialise_source(self, dash, source_spec, cache):
        provider = (source_spec or {}).get("provider")
        remote_kind = provider if provider in ("rest", "sheets") else source_spec.get("requires_remote")
        if remote_kind in ("rest", "sheets"):
            # Portable remote schemas never import credentials, URLs or cached rows.
            provider = "file"
        if provider in (None, "orm"):
            return None
        ref = source_spec.get("ref") or "%s:%s" % (
            provider, source_spec.get("name") or "source")
        if ref in cache:
            return cache[ref]
        Source = self.env["eh.board.datasource"]
        vals = {
            "name": source_spec.get("name") or provider.title(),
            "provider_type": provider,
            "dashboard_id": dash.id,
        }
        if provider == "join":
            config = source_spec.get("config") or {}
            vals["config"] = dash._restore_guided_query_config(config) \
                if isinstance(config, dict) and config.get("guided_query") else config
        elif provider == "file":
            vals["file_name"] = source_spec.get("file_name") or "Reconnect data file"
            if remote_kind in ("rest", "sheets"):
                vals["file_name"] = _("Reconnect remote data source")
                vals["config"] = {"requires_remote": remote_kind}
        elif provider == "sql":
            if not (self.env.su
                    or self.env.user.has_group("eh_board.group_board_admin")):
                return None
            # Secret-free backup deliberately omits query; invalid placeholder
            # renders explicit reconnect error, never invented figures.
            vals["sql_query"] = ""
        else:
            return None
        source = Source.create(vals)
        if provider == "file":
            Col = self.env["eh.board.source.column"]
            for column in (source_spec.get("columns") or [])[:200]:
                if not column.get("name"):
                    continue
                Col.create({
                    "datasource_id": source.id,
                    "name": column["name"],
                    "label": column.get("label") or column["name"],
                    "dtype": column.get("dtype")
                    if column.get("dtype") in ("number", "date", "bool", "text")
                    else "text",
                    "sequence": int(column.get("sequence") or 10),
                })
        cache[ref] = source
        return source

    def _materialise_item(self, dash, spec, source_cache=None):
        if spec.get("business_metric_id"):
            # Portable definition references rebind to the importing user's
            # current company. Never replay another database's company IDs.
            return dash._create_business_metric(spec["business_metric_id"], {
                "title": spec.get("title") or "",
                "item_type": spec.get("type") or "kpi",
                "dimension": spec.get("dimension") or "",
                "default_date_filter": spec.get("default_date_filter") or "none",
                "granularity": spec.get("granularity") or "month",
            })
        model = spec.get("model")
        if model and model not in self.env:
            return None  # base app not installed -> skip this widget
        vals = {
            "item_type": spec.get("type", "bar"),
            "title": spec.get("title", ""),
        }
        portable_fields = (
            "accent", "tile_style", "content", "domain", "icon", "subtitle",
            "description", "list_mode", "date_granularity", "sort_mode",
            "sort_order", "include_archived", "record_limit_visibility",
            "record_limit", "data_label_type", "color_mode", "chart_options",
            "conditional_rules", "show_legend", "show_values", "show_grid",
            "semi_circle", "stacked", "smooth", "goal_value", "combo_line",
            "cumulative", "fill_gaps", "group_others", "click_action",
            "default_date_filter", "date_field", "sort_field",
        )
        for key in portable_fields:
            if key in spec:
                vals[key] = spec[key]
        if vals.get("click_action") == "dashboard":
            target = self.env["eh.board.dashboard"].search([
                ("name", "=", spec.get("target_dashboard") or ""),
                ("id", "!=", dash.id),
            ], limit=1)
            if target:
                vals["target_dashboard_id"] = target.id
            else:
                vals["click_action"] = "none"
        elif vals.get("click_action") == "action":
            xmlid = spec.get("window_action_xmlid") or ""
            action = self.env.ref(xmlid, raise_if_not_found=False) if xmlid else False
            if (action and action._name == "ir.actions.act_window"
                    and (not model or action.res_model == model)):
                vals["window_action_id"] = action.id
            else:
                vals["click_action"] = "none"
        source = self._materialise_source(
            dash, spec.get("source") or {},
            source_cache if source_cache is not None else {})
        if model:
            model_rec = self.env["ir.model"]._get(model)
            model_obj = self.env[model]
            vals["model_id"] = model_rec.id
            measures = spec.get("measures") or ([spec["measure"]] if spec.get("measure") else [])
            # Drop measures whose field is absent on this version.
            measures = [self._restore_measure_currency(m) for m in measures
                        if not m.get("field") or m["field"] in model_obj._fields]
            if measures:
                vals["measures"] = measures
            if spec.get("type") == "list":
                vals["list_mode"] = spec.get("list_mode", "grouped")
                vals["list_fields"] = [
                    name for name in (spec.get("list_fields") or [])
                    if name in model_obj._fields
                ]
            dim = spec.get("dimension")
            if dim:
                if dim in model_obj._fields:
                    vals["dimension"] = dim
                    if model_obj._fields[dim].type in ("date", "datetime"):
                        vals["granularity"] = spec.get("granularity", "month")
                elif spec.get("type") not in ("kpi", "tile", "gauge", "richtext", "todo"):
                    return None  # a chart lost its group-by on this version -> skip
            sec = spec.get("secondary_dimension")
            if sec and sec in model_obj._fields:
                vals["secondary_dimension"] = sec
            item = dash._create_item_from_builder(vals)
        elif source:
            Item = self.env["eh.board.item"]
            direct = {key: value for key, value in vals.items() if key in Item._fields}
            direct.update({"dashboard_id": dash.id, "datasource_id": source.id})
            if source.provider_type == "join" and (source.config or {}).get("guided_query"):
                direct.update({"description": dash._query_definition(source.config["guided_query"]),
                               "default_date_filter": "none", "click_action": "none"})
            if source.provider_type == "file":
                columns = {column.name: column for column in source.column_ids}
                primary = columns.get(spec.get("primary_column"))
                secondary = columns.get(spec.get("secondary_column"))
                if primary:
                    direct["primary_column_id"] = primary.id
                if secondary:
                    direct["secondary_column_id"] = secondary.id
                measure_ids = []
                for measure_spec in (spec.get("measures") or [])[:6]:
                    measure_spec = self._restore_measure_currency(measure_spec)
                    column = columns.get(measure_spec.get("column"))
                    measure = self.env["eh.board.measure"].create({
                        "name": measure_spec.get("label") or measure_spec.get("column") or "Records",
                        "datasource_id": source.id,
                        "column_id": column.id if column else False,
                        "aggregate": measure_spec.get("verb") or "count",
                        "formula": measure_spec.get("formula") or "",
                        "number_format": measure_spec.get("number_format") or "compact",
                        "unit": measure_spec.get("unit") or "",
                        "multiplier": float(measure_spec.get("multiplier") or 1.0),
                        "target_value": float(measure_spec.get("target") or 0.0),
                        "target_schedule": measure_spec.get("target_schedule") or [],
                        "compare_mode": measure_spec.get("compare_mode") or "none",
                        "as_line": bool(measure_spec.get("as_line")),
                        "table_calculation": measure_spec.get("table_calculation") or "none",
                        "currency_id": measure_spec.get("currency_id") or False,
                    })
                    measure_ids.append(measure.id)
                direct["measure_ids"] = [(6, 0, measure_ids)]
            item = Item.create(direct)
        elif spec.get("type") in ("richtext", "todo"):
            item = dash._create_item_from_builder(vals)
        else:
            return None

        # Restore full multi-level drill chain after builder has resolved model.
        if item.datasource_id.model_id and spec.get("drills"):
            commands = [(5, 0, 0)]
            for index, drill in enumerate((spec.get("drills") or [])[:8]):
                field_name = drill.get("field")
                if field_name not in self.env[item.datasource_id.model_name]._fields:
                    continue
                field_id = dash._field_id(item.datasource_id.model_id.id, field_name)
                if field_id:
                    commands.append((0, 0, {
                        "sequence": (index + 1) * 10,
                        "field_id": field_id,
                        "chart_type": drill.get("chart_type") or False,
                        "sort": drill.get("sort") or "value_desc",
                        "limit": int(drill.get("limit") or 0),
                    }))
            item.write({"drill_ids": commands})
        return item

    def _restore_measure_currency(self, measure_spec):
        """Resolve portable ISO currency code to this database's record id."""
        measure = dict(measure_spec or {})
        code = measure.pop("currency", None)
        if code:
            currency = self.env["res.currency"].search(
                [("name", "=", str(code).upper())], limit=1)
            if currency:
                measure["currency_id"] = currency.id
        # Reject numeric ids from old/untrusted backups: ids are database-local.
        elif "currency_id" in measure:
            measure.pop("currency_id", None)
        return measure

    def _materialise_filter(self, dash, flt, first_model):
        model = flt.get("model") or first_model
        field_name = flt.get("field")
        filter_type = flt.get("type") or "field"
        if filter_type == "date" and not field_name:
            self.env["eh.board.filter"].create({
                "dashboard_id": dash.id,
                "name": flt.get("name") or "Date",
                "filter_type": "date",
                "date_preset": flt.get("date_preset") or "this_month",
                "default_value": flt.get("default") or {},
                "options": flt.get("options") or {},
            })
            return
        if not (model and field_name and model in self.env):
            return
        if field_name not in self.env[model]._fields:
            return
        model_rec = self.env["ir.model"]._get(model)
        field = self.env["ir.model.fields"].sudo().search(
            [("model_id", "=", model_rec.id), ("name", "=", field_name)], limit=1)
        if not field:
            return
        field = dash._readable_field_metadata(field)
        self.env["eh.board.filter"].create({
            "dashboard_id": dash.id,
            "name": flt.get("name") or field.field_description or field_name,
            "filter_type": filter_type, "field_id": field.id,
            "date_preset": flt.get("date_preset") or "this_month",
            "default_value": flt.get("default") or {},
            "options": flt.get("options") or {}})

    def apply_and_open(self):
        """Create the dashboard and return an action opening it on the board."""
        self.ensure_one()
        dash = self.create_from_template()
        return {
            "type": "ir.actions.client",
            "tag": "eh_board.board",
            "name": dash.name,
            "params": {"dashboard_id": dash.id},
        }

    def gallery(self):
        """Available templates for the picker, availability resolved."""
        return [{
            "id": t.id, "name": t.name, "category": t.category,
            "description": t.description or "",
            "required_module": t.required_module or "",
            "available": t.is_available(),
            "business_pack_key": t.business_pack_key or False,
        } for t in self.search([])]

    # -- predefined vertical packs ------------------------------------------
    @staticmethod
    def _pack_items(model, heading, sum_field=None, cat_dim=None,
                    second_dim=None, date_field=None):
        """Build the standard vertical layout: heading, a count tile, an
        optional value KPI, a category bar, and a time series / split."""
        items = [
            {"type": "richtext", "title": "",
             "content": "<h2>%s</h2>" % heading, "x": 0, "y": 0, "w": 12, "h": 2},
            {"type": "tile", "title": "Total records", "model": model,
             "measure": {"verb": "count"}, "accent": "mint", "tile_style": "solid",
             "icon": "fa-hashtag", "x": 0, "y": 2, "w": 3, "h": 4},
        ]
        x = 3
        if sum_field:
            items.append({"type": "kpi", "title": "Total value", "model": model,
                          "measure": {"verb": "sum", "field": sum_field},
                          "accent": "blue", "x": 3, "y": 2, "w": 3, "h": 4})
            x = 6
        if cat_dim:
            items.append({"type": "bar", "title": "By category", "model": model,
                          "measure": {"verb": "count"}, "dimension": cat_dim,
                          "accent": "violet", "x": x, "y": 2, "w": 12 - x, "h": 4})
        if date_field:
            items.append({"type": "area", "title": "Over time", "model": model,
                          "measure": {"verb": "count"}, "dimension": date_field,
                          "granularity": "month", "accent": "teal",
                          "x": 0, "y": 6, "w": 8, "h": 6})
            if second_dim:
                items.append({"type": "doughnut", "title": "Split", "model": model,
                              "measure": {"verb": "count"}, "dimension": second_dim,
                              "accent": "amber", "x": 8, "y": 6, "w": 4, "h": 6})
        elif second_dim:
            items.append({"type": "doughnut", "title": "Split", "model": model,
                          "measure": {"verb": "count"}, "dimension": second_dim,
                          "accent": "amber", "x": 0, "y": 6, "w": 6, "h": 6})
        return items

    def _seed_predefined(self):
        """Ship the six vertical packs once. Each targets a base app by string
        and stays inert (greyed in the gallery) until that app is installed."""
        self._seed_business_packs()
        if self.search_count([("is_predefined", "=", True), ("business_pack_key", "=", False)]):
            return
        P = self._pack_items
        packs = [
            ("Contacts overview", "general", "", "res.partner",
             P("res.partner", "Contacts overview", None, "country_id", "is_company", "create_date"),
             {"name": "Country", "field": "country_id"}),
            ("Sales & CRM pipeline", "crm", "crm", "crm.lead",
             P("crm.lead", "Sales pipeline", "expected_revenue", "stage_id", "type", "create_date"),
             {"name": "Salesperson", "field": "user_id"}),
            ("Sales overview", "crm", "sale", "sale.order",
             P("sale.order", "Sales overview", "amount_total", "state", "user_id", "date_order"),
             {"name": "Salesperson", "field": "user_id"}),
            ("Accounting overview", "account", "account", "account.move",
             P("account.move", "Accounting", "amount_total", "move_type", "state", "invoice_date"),
             {"name": "Journal", "field": "journal_id"}),
            ("Warehouse operations", "stock", "stock", "stock.picking",
             P("stock.picking", "Warehouse operations", None, "state", "picking_type_id", "scheduled_date"),
             {"name": "Operation type", "field": "picking_type_id"}),
            ("Point of Sale", "pos", "point_of_sale", "pos.order",
             P("pos.order", "Point of Sale", "amount_total", "state", None, "date_order"),
             {"name": "Session", "field": "session_id"}),
            ("Human Resources", "hr", "hr", "hr.employee",
             P("hr.employee", "Human Resources", None, "department_id", "job_id", None),
             {"name": "Department", "field": "department_id"}),
        ]
        for name, cat, mod, model, items, flt in packs:
            self.create({
                "name": name, "category": cat, "is_predefined": True,
                "required_module": mod,
                "description": "Ready-made %s dashboard. Install %s to use it." % (name, mod),
                "payload": {"name": name, "items": items,
                            "filters": [dict(flt, model=model)]},
            })

    def _seed_business_packs(self):
        """Add new versioned templates on install/upgrade, preserving old data."""
        for key, pack in PACKS.items():
            if self.search_count([("business_pack_key", "=", key)]):
                continue
            self.create({
                "name": str(pack["name"]), "category": pack["category"], "sequence": 1,
                "is_predefined": True, "required_module": pack["module"],
                "business_pack_key": key, "description": str(pack["description"]),
                "payload": {"business_pack_key": key, "version": 1},
            })
