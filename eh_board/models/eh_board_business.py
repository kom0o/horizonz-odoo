"""Business packs and immutable metric references on ordinary board items."""
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

from ..lib.business_metrics import METRICS, PACKS, metric_definition, metric_domain


_PERIODS = ["none", "this_month", "this_quarter", "this_year", "last_month",
            "last_7", "last_30", "last_90", "ytd"]


class EhBoardBusiness(models.Model):
    _inherit = "eh.board.dashboard"

    def _definition_payload(self):
        result = super()._definition_payload()
        for item, spec in zip(self.item_ids, result.get("items", [])):
            if item.business_metric_id:
                spec["business_metric_id"] = item.business_metric_id
                # The trusted version resolves source, measures and fixed
                # company on import. Database-local company IDs are not portable.
                spec.pop("domain", None)
        return result

    def _require_business_builder(self):
        if not (self.env.su or self.env.user.has_group("eh_board.group_board_builder")):
            raise AccessError(_("Only dashboard builders may create or preview business packs."))

    def _translated_metric_definition(self, metric_id):
        definition = metric_definition(metric_id)
        if definition:
            for key in ("title", "definition"):
                definition[key] = str(definition[key])
        return definition

    def _business_pack_definition(self, pack_id):
        pack = dict(PACKS.get(pack_id) or {})
        for key in ("name", "description"):
            if key in pack:
                pack[key] = str(pack[key])
        return pack

    def _business_metric_available(self, metric_id):
        definition = metric_definition(metric_id)
        if not definition or definition["model"] not in self.env:
            return False
        Model = self.env[definition["model"]]
        try:
            readable = Model.has_access("read") if hasattr(Model, "has_access") \
                else Model.check_access_rights("read", raise_exception=False)
            if not readable:
                return False
            # fields_get excludes group-restricted fields for this exact user.
            available = Model.fields_get(attributes=["type", "string", "store"])
        except AccessError:
            return False
        required = {"company_id"} | {leaf[0] for leaf in definition["domain"]}
        required.update(name for name in (definition.get("field"), definition.get("date_field")) if name)
        if definition.get("currency") == "order_company":
            required.add("currency_id")
        if definition.get("dynamic") == "overdue":
            required.add("invoice_date_due")
        if definition.get("dynamic") == "late":
            required.add("scheduled_date")
        return all(name in available and Model._fields[name].store for name in required)

    def _metric_authoring_spec(self, metric_id):
        """Trusted builder values. Dynamic predicates stay on the metric item."""
        self._require_business_builder()
        if not self._business_metric_available(metric_id):
            raise UserError(_("This business metric is unavailable for your installed apps or access rights."))
        definition = self._translated_metric_definition(metric_id)
        company = self.env.company
        measure = {"verb": definition["aggregate"], "field": definition.get("field") or "",
                   "label": definition["title"], "number_format": "plain", "compare_mode": "none"}
        if definition.get("currency") and definition["aggregate"] != "count":
            measure["currency_id"] = company.currency_id.id
        return {
            "model_id": self.env["ir.model"]._get(definition["model"]).id,
            "item_type": "kpi", "title": definition["title"], "measure": measure,
            "domain": repr(metric_domain(metric_id, company.id, company.currency_id.id)),
            "date_field": definition.get("date_field") or "", "default_date_filter": "none",
            "description": "%s\n\n%s: %s. %s: %s." % (
                definition["definition"], _("Company"), company.display_name,
                _("Definition version"), metric_id),
            "show_trend": False, "click_action": "records", "record_limit": 20,
            "show_legend": True, "show_values": True, "show_grid": True,
            "sort_mode": "value_desc", "fill_gaps": definition["aggregate"] in ("sum", "count"),
        }

    def _metric_authoring_catalog(self):
        self._require_business_builder()
        out = []
        for metric_id in METRICS:
            if not self._business_metric_available(metric_id):
                continue
            definition = self._translated_metric_definition(metric_id)
            Model = self.env[definition["model"]]
            available = Model.fields_get(attributes=["string", "type"])
            dimensions = [{"field": name, "label": available[name]["string"]}
                          for name in definition["dimensions"]
                          if name in available and Model._fields[name].store]
            out.append({
                "id": metric_id, "title": definition["title"], "model": definition["model"],
                "description": definition["definition"], "builder_vals": self._metric_authoring_spec(metric_id),
                "allowed_dimensions": dimensions,
                "allowed_charts": ["kpi", "tile", "bar", "hbar", "line", "list"],
                "date_field": definition.get("date_field") or False,
                "allowed_date_presets": _PERIODS if definition.get("date_field") else ["none"],
                "assumptions": [definition["definition"], _("Fixed to company: %s", self.env.company.display_name)],
            })
        return out

    def _create_business_metric(self, metric_id, overrides=None):
        """Shared apply seam for packs and validated AI plans; no raw query input."""
        self.ensure_one()
        self._require_edit()
        vals = self._metric_authoring_spec(metric_id)
        definition = self._translated_metric_definition(metric_id)
        overrides = dict(overrides or {})
        allowed = {"title", "item_type", "dimension", "date_field", "default_date_filter", "granularity"}
        if set(overrides) - allowed:
            raise ValidationError(_("Unsupported business metric customization."))
        chart = overrides.get("item_type", vals["item_type"])
        if chart not in ("kpi", "tile", "bar", "hbar", "line", "list"):
            raise ValidationError(_("This chart is not supported by the business metric."))
        dimension = overrides.get("dimension") or ""
        accessible = self.env[definition["model"]].fields_get(attributes=["type"])
        if dimension and (dimension not in definition["dimensions"] or dimension not in accessible):
            raise ValidationError(_("Choose a permitted breakdown for this metric."))
        if chart not in ("kpi", "tile") and not dimension:
            raise ValidationError(_("Choose a breakdown for this chart."))
        if "date_field" in overrides and (overrides["date_field"] or "") != (definition.get("date_field") or ""):
            raise ValidationError(_("This metric has a fixed date basis."))
        preset = overrides.get("default_date_filter") or "none"
        if preset not in (_PERIODS if definition.get("date_field") else ["none"]):
            raise ValidationError(_("Current-balance metrics do not support historical date filters."))
        granularity = overrides.get("granularity") or "month"
        if granularity not in ("day", "week", "month", "quarter", "year"):
            raise ValidationError(_("Unsupported date grouping."))
        vals.update(overrides)
        vals.update({"item_type": chart, "dimension": dimension, "granularity": granularity,
                     "default_date_filter": preset})
        if dimension and accessible[dimension]["type"] in ("date", "datetime"):
            vals["sort_mode"] = "label"
        if chart in ("kpi", "tile"):
            vals["dimension"] = ""
        elif "title" not in overrides:
            field_label = self.env[definition["model"]].fields_get([dimension], attributes=["string"])[dimension]["string"]
            vals["title"] = _("%s by %s", definition["title"], field_label)
        source = self._ensure_datasource(vals["model_id"])
        if source.get_domain():
            # An existing custom source filter is not part of the published
            # metric definition. Use a clean source, still owned by this board.
            source = self.env["eh.board.datasource"].create({
                "name": definition["title"], "dashboard_id": self.id,
                "provider_type": "orm", "model_id": vals["model_id"], "domain": "[]"})
        vals["source_id"] = source.id
        item_vals = self._builder_item_vals(vals)
        item_vals.update({"business_metric_id": metric_id, "business_company_id": self.env.company.id})
        return self.env["eh.board.item"].create(item_vals)

    def detach_business_metric(self, item_id):
        """Explicitly turn a definition-backed item into an ordinary custom one."""
        self.ensure_one()
        self._require_edit()
        item = self._owned_item(item_id)
        if item.business_metric_id:
            # Preserve the scope visible at detachment. Relative overdue/late
            # predicates become fixed cutoffs; the UI explains this tradeoff.
            domain = item._parse_domain(item.domain) + item._business_scope_domain()
            item.write({"business_metric_id": False, "business_company_id": False,
                        "description": "", "domain": repr(domain)})
        return {"meta": item._meta(), "payload": item.get_payload({})}

    @api.model
    def get_business_packs(self):
        self._require_business_builder()
        metrics = {entry["id"]: entry for entry in self._metric_authoring_catalog()}
        packs = []
        for pack_id in PACKS:
            pack = self._business_pack_definition(pack_id)
            usable = all(mid in metrics and (not dim or dim in {
                d["field"] for d in metrics[mid]["allowed_dimensions"]})
                for mid, _chart, dim in pack["widgets"])
            packs.append({"id": pack_id, "name": pack["name"], "category": pack["category"],
                          "description": pack["description"], "available": usable,
                          "required_module": pack["module"], "widget_count": len(pack["widgets"]),
                          "unavailable_reason": "" if usable else _("Install the required app and grant read access to its metric fields."),
                          "company": self.env.company.display_name, "currency": self.env.company.currency_id.name})
        return packs

    def _build_business_pack(self, pack_id):
        self._require_business_builder()
        pack = self._business_pack_definition(pack_id)
        offered = next((p for p in self.get_business_packs() if p["id"] == pack_id), None)
        if not pack or not offered or not offered["available"]:
            raise UserError(_("This business pack is unavailable for your installed apps or access rights."))
        dash = self.create({"name": pack["name"], "state": "draft", "owner_id": self.env.uid,
                            "company_ids": [(6, 0, self.env.company.ids)], "description": pack["description"],
                            "default_date_preset": pack["preset"]})
        grid = {}
        headline_count = sum(1 for _mid, chart, _dim in pack["widgets"] if chart == "kpi")
        width = 12 // headline_count
        chart_index = 0
        for index, (metric_id, chart, dimension) in enumerate(pack["widgets"]):
            item = dash._create_business_metric(metric_id, {"item_type": chart, "dimension": dimension or ""})
            if chart == "kpi":
                geom = {"x": index * width, "y": 0, "w": width, "h": 4}
            else:
                geom = {"x": (chart_index % 2) * 6, "y": 4 + (chart_index // 2) * 7, "w": 6, "h": 7}
                chart_index += 1
            grid[str(item.id)] = geom
        self.env["eh.board.layout.version"].create({
            "dashboard_id": dash.id, "name": "Default", "is_active": True,
            "is_default": True, "grid": grid, "density": "comfortable"})
        return dash

    @api.model
    def create_business_pack(self, pack_id):
        with self.env.cr.savepoint():
            dash = self._build_business_pack(pack_id)
        return {"type": "ir.actions.client", "tag": "eh_board.board", "name": dash.name,
                "params": {"dashboard_id": dash.id}}

    @api.model
    def preview_business_pack(self, pack_id):
        self._require_business_builder()
        result = {}

        class _RollbackPreview(Exception):
            pass

        try:
            with self.env.cr.savepoint():
                dash = self._build_business_pack(pack_id)
                options = {}
                if dash.default_date_preset != "all":
                    period = dash.item_ids[:1]._preset_range(dash.default_date_preset)
                    if period:
                        options["date_range"] = {"start": period[0], "end": period[1]}
                result = {"name": dash.name, "description": dash.description,
                          "company": self.env.company.display_name, "currency": self.env.company.currency_id.name,
                          "items": [{"meta": item._meta(), "payload": item.get_payload(options)} for item in dash.item_ids],
                          "period": dash.default_date_preset, "generated_at": fields.Datetime.to_string(fields.Datetime.now())}
                raise _RollbackPreview()
        except _RollbackPreview:
            pass
        return result


class EhBoardBusinessItem(models.Model):
    _inherit = "eh.board.item"

    business_metric_id = fields.Char(string="Business metric version", readonly=True, copy=True)
    business_company_id = fields.Many2one("res.company", string="Metric company", readonly=True, copy=True)

    @api.constrains("business_metric_id", "business_company_id", "datasource_id", "measure_ids", "date_filter_field_id")
    def _check_business_metric_reference(self):
        for item in self.filtered("business_metric_id"):
            definition = metric_definition(item.business_metric_id)
            if not definition or not item.business_company_id or item.datasource_id.model_name != definition["model"]:
                raise ValidationError(_("Business metric version, company and source must match."))
            measure = item.measure_ids
            expected_currency = item.business_company_id.currency_id if definition.get("currency") and definition["aggregate"] != "count" else self.env["res.currency"]
            if (len(measure) != 1 or measure.aggregate != definition["aggregate"]
                    or (measure.field_name or None) != definition.get("field")
                    or measure.multiplier != 1.0 or measure.currency_id != expected_currency
                    or (item.date_filter_field_id.name or None) != definition.get("date_field")
                    or item.datasource_id.get_domain()):
                raise ValidationError(_("This widget must match its business definition. Detach the definition before changing its calculation."))

    def _business_signature(self):
        self.ensure_one()
        return (self.business_metric_id, self.business_company_id.id,
                self.datasource_id.id, tuple(self.measure_ids.ids),
                self._parse_domain(self.domain), self.date_filter_field_id.id)

    def write(self, vals):
        vals = dict(vals)
        tracked = self.filtered("business_metric_id")
        if "business_metric_id" in vals and not vals["business_metric_id"]:
            vals.update({"business_company_id": False, "description": ""})
            return super().write(vals)
        signatures = {item.id: item._business_signature() for item in tracked}
        with self.env.cr.savepoint():
            result = super().write(vals)
            if any(item._business_signature() != signatures[item.id] for item in tracked):
                raise ValidationError(_("Detach the business definition before changing its calculation, source, scope or date basis."))
        return result

    def _business_scope_domain(self):
        self.ensure_one()
        if not self.business_metric_id:
            return []
        company = self.business_company_id
        if company not in self.env.companies:
            raise AccessError(_("Select the company attached to this business metric to view its data."))
        return metric_domain(self.business_metric_id, company.id, company.currency_id.id,
                             today=fields.Date.to_string(fields.Date.context_today(self)),
                             now=fields.Datetime.to_string(fields.Datetime.now()))

    def _effective_domain(self, options=None):
        return super()._effective_domain(options) + self._business_scope_domain()

    def _click_base_domain(self):
        return super()._click_base_domain() + self._business_scope_domain()

    def _runtime_domain(self, options):
        definition = metric_definition(self.business_metric_id) if self.business_metric_id else None
        if definition and not definition.get("date_field"):
            return list((options or {}).get("domain") or []) + self._runtime_field_domain(options)
        return super()._runtime_domain(options)

    def _meta(self):
        result = super()._meta()
        if self.business_metric_id:
            result.update({"business_metric_id": self.business_metric_id,
                           "business_company_id": self.business_company_id.id,
                           "current_balance": not bool(metric_definition(self.business_metric_id).get("date_field"))})
        return result


class EhBoardBusinessMeasure(models.Model):
    _inherit = "eh.board.measure"

    def write(self, vals):
        watched = {"aggregate", "field_id", "column_id", "formula", "multiplier", "currency_id", "datasource_id"}
        if not watched.intersection(vals):
            return super().write(vals)
        used = self.env["eh.board.item"].sudo().search([
            ("business_metric_id", "!=", False), ("measure_ids", "in", self.ids)])
        tracked = self & used.measure_ids
        before = {record.id: record.read(sorted(watched))[0] for record in tracked}
        with self.env.cr.savepoint():
            result = super().write(vals)
            if any(record.read(sorted(watched))[0] != before[record.id] for record in tracked):
                raise ValidationError(_("A business dashboard uses this measure. Detach its business definition before changing the calculation."))
        return result


class EhBoardBusinessSource(models.Model):
    _inherit = "eh.board.datasource"

    def write(self, vals):
        watched = {"provider_type", "model_id", "domain"}
        if not watched.intersection(vals):
            return super().write(vals)
        used = self.env["eh.board.item"].sudo().search([
            ("business_metric_id", "!=", False), ("datasource_id", "in", self.ids)])
        tracked = self & used.datasource_id
        before = {record.id: (record.provider_type, record.model_id.id, record.get_domain()) for record in tracked}
        with self.env.cr.savepoint():
            result = super().write(vals)
            if any((record.provider_type, record.model_id.id, record.get_domain()) != before[record.id] for record in tracked):
                raise ValidationError(_("A business dashboard uses this source. Detach its business definition before changing the source or scope."))
        return result
