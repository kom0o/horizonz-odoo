# -*- coding: utf-8 -*-
# Copyright (C) 2026 ERP Heritage.
"""Server-owned AI metric definitions for explicitly selected data.

Only metadata is placed in the provider catalogue. Model fields, domains and
source settings never come from the proposal, and definitions are rebuilt for
every preview/apply. A content digest in each metric ID rejects stale plans.
"""
import copy
import hashlib
import json

from odoo import _, models
from odoo.exceptions import AccessError, ValidationError

_SCOPE_LIMIT = 3
_NUMERIC_LIMIT = 2
_DIMENSION_LIMIT = 6
_DATE_LIMIT = 3
_SKIP_FIELDS = {"id", "sequence", "color", "message_attachment_count"}
_GROUP_TYPES = {"many2one", "selection", "boolean", "date", "datetime"}


class EhBoardAuthoringScope(models.Model):
    _inherit = "eh.board.dashboard"

    def _authoring_scope(self, data_scope=None):
        if data_scope is None:
            return {"models": [], "sources": []}
        if not isinstance(data_scope, dict) or set(data_scope) - {"models", "sources"}:
            raise ValidationError(_("Choose models and dashboard sources from the data picker."))
        scope = {}
        for key in ("models", "sources"):
            values = data_scope.get(key, [])
            if (not isinstance(values, list) or len(values) > _SCOPE_LIMIT
                    or any(type(value) is not int or value <= 0 for value in values)
                    or len(values) != len(set(values))):
                raise ValidationError(_("Choose up to three different data sources."))
            scope[key] = sorted(values)
        if sum(len(values) for values in scope.values()) > _SCOPE_LIMIT:
            raise ValidationError(_("Choose up to three different data sources."))
        return scope

    def _authoring_model(self, model_id):
        # Registry metadata can require Settings access; it never grants access
        # to records. Model ACLs and fields_get below use the original operator.
        model = self.env["ir.model"].sudo().browse(model_id).exists()
        if not model or model.model not in self.env:
            raise AccessError(_("The selected model is no longer available."))
        Model = self.env[model.model]
        if Model._abstract or Model._transient:
            raise AccessError(_("Choose a readable business model."))
        if hasattr(Model, "check_access"):
            Model.check_access("read")
        else:
            Model.check_access_rights("read")
        return model, Model

    def search_authoring_models(self, query=""):
        """Bounded, normal-access model picker; no record values are searched."""
        self._authoring_require_edit()
        if not isinstance(query, str) or len(query) > 80:
            raise ValidationError(_("Keep the model search under 80 characters."))
        domain = [("transient", "=", False), ("model", "not like", "ir.%"),
                  ("model", "not like", "bus.%")]
        if query.strip():
            domain += ["|", ("name", "ilike", query.strip()), ("model", "ilike", query.strip())]
        result = []
        for model in self.env["ir.model"].sudo().search(domain, order="name, id", limit=250):
            try:
                self._authoring_model(model.id)
            except AccessError:
                continue
            result.append({"id": model.id, "name": model.name, "model": model.model})
            if len(result) == 40:
                break
        return result

    def _authoring_source_choices(self):
        sources = self.env["eh.board.datasource"].search([
            ("dashboard_id", "=", self.id), ("active", "=", True),
            ("provider_type", "in", ["orm", "file", "rest", "sheets", "join"]),
        ], order="name, id", limit=80)
        result = []
        for source in sources:
            if source.provider_type == "join" and not (source.config or {}).get("guided_query"):
                continue
            result.append({"id": source.id, "name": source.name, "provider": source.provider_type})
        return result

    def _authoring_scope_source(self, source_id):
        source = self._owned_source(source_id)
        if source.dashboard_id != self or not source.active:
            raise AccessError(_("Choose an active source owned by this dashboard."))
        if hasattr(source, "check_access"):
            source.check_access("read")
        else:
            source.check_access_rights("read")
            source.check_access_rule("read")
        return source

    def _authoring_scoped_catalog(self, data_scope=None):
        scope = self._authoring_scope(data_scope)
        result = []
        for model_id in scope["models"]:
            result.extend(self._authoring_model_metrics(model_id))
        for source_id in scope["sources"]:
            source = self._authoring_scope_source(source_id)
            if source.provider_type == "orm":
                result.extend(self._authoring_model_metrics(source.model_id.id, source))
            elif source._is_tabular_source():
                result.extend(self._authoring_tabular_metrics(source))
            elif source.provider_type == "join" and (source.config or {}).get("guided_query"):
                if not hasattr(source, "_guided_authoring_metric"):
                    raise ValidationError(_("This saved query cannot yet be used for AI proposals."))
                fixed = source._guided_authoring_metric()
                result.append(self._authoring_signed_metric({
                    "title": fixed["title"], "description": fixed["description"],
                    "provider_description": _("Saved comparison with fixed grouping, measures, dates and row filters. Review its full definition in the preview."),
                    "assumptions": fixed["assumptions"], "allowed_dimensions": [],
                    "allowed_date_fields": [], "date_field": "", "allowed_date_presets": ["none"],
                    "allowed_charts": fixed["allowed_chart_types"], "fixed_grouping": True,
                    "builder_vals": {"source_id": source.id, "item_type": "bar",
                                     "title": fixed["title"], "show_trend": False},
                    "source_token": fixed["definition_token"],
                }, "source%s.fixed" % source.id))
            else:
                raise ValidationError(_("AI proposals support Odoo models, saved snapshots and guided queries."))
        return result

    def _authoring_signed_metric(self, spec, prefix):
        """A digest is a version identifier, not a client-authorized signature."""
        spec["scope_context"] = {
            "company": self.env.company.id, "allowed_companies": sorted(self.env.companies.ids),
            "board": self.id, "user": self.env.uid,
        }
        payload = json.dumps(spec, sort_keys=True, ensure_ascii=True, default=str)
        digest = hashlib.sha256(payload.encode()).hexdigest()[:24]
        spec["id"] = "scope.%s.%s.v1" % (prefix, digest)
        spec["scoped"] = True
        return spec

    def _authoring_model_metrics(self, model_id, source=None):
        model, Model = self._authoring_model(model_id)
        # fields_get omits fields hidden from this operator by field groups.
        available = Model.fields_get(attributes=["type", "string", "store", "currency_field"])
        available = {name: value for name, value in available.items()
                     if name in Model._fields and Model._fields[name].store}
        company_domain = []
        if "company_id" in Model._fields:
            if ("company_id" not in available or available["company_id"]["type"] != "many2one"
                    or Model._fields["company_id"].comodel_name != "res.company"):
                raise AccessError(_("This model's company scope cannot be verified with your access rights."))
            company_domain = [("company_id", "in", [False, self.env.company.id])]
            scope_note = _("Current company and shared records: %s", self.env.company.display_name)
        else:
            scope_note = _("This model has no direct company field. Your record rules and selected companies determine access.")
        ordered = sorted(available, key=lambda name: (name in {"create_date", "write_date"}, name))
        dates = [name for name in ordered if available[name]["type"] in ("date", "datetime")][:_DATE_LIMIT]
        dimensions = [name for name in ordered if available[name]["type"] in _GROUP_TYPES
                      and name not in {"company_id", "create_uid", "write_uid"}][:_DIMENSION_LIMIT]
        # Always retain one date breakdown when the model has one.
        if dates and not any(name in dates for name in dimensions):
            dimensions = dimensions[:_DIMENSION_LIMIT - 1] + dates[:1]
        numeric = [name for name in ordered if available[name]["type"] in ("integer", "float")
                   and name not in _SKIP_FIELDS and not available[name].get("currency_field")][:_NUMERIC_LIMIT]
        default_date = dates[0] if dates else ""
        label = source.name if source else model.name
        vals = {"model_id": model.id, "domain": repr(company_domain), "date_field": default_date,
                "default_date_filter": "none", "item_type": "kpi", "show_trend": False,
                "click_action": "records", "record_limit": 20, "show_legend": True,
                "show_values": True, "show_grid": True, "sort_mode": "value_desc"}
        source_token = None
        if source:
            vals["source_id"] = source.id
            # Validate existing domain through the provider; never send it to AI.
            source_token = {"id": source.id, "provider": source.provider_type,
                            "model": model.id, "domain": source.get_domain()}
        else:
            vals["authoring_clean_source"] = True
        base = {
            "model": model.model, "source_token": source_token,
            "allowed_dimensions": [{"field": name, "label": available[name]["string"]}
                                   for name in dimensions],
            "allowed_date_fields": [{"field": name, "label": available[name]["string"]} for name in dates],
            "allowed_charts": ["kpi", "tile", "bar", "hbar", "line"],
            "date_field": default_date,
            "assumptions": [scope_note, _("Includes all readable records matching the selected source; no business-status filter is inferred."),
                            _("Monetary fields are excluded. Use a defined business metric for financial totals.")],
            "field_definition": {name: {"type": available[name]["type"],
                                        "label": available[name]["string"],
                                        "groups": str(Model._fields[name].groups or "")}
                                 for name in set(dimensions + dates + numeric)},
        }
        if source and source.get_domain():
            base["assumptions"].append(_("The existing source filter is preserved."))
        if default_date:
            base["assumptions"].append(_("Choose the date basis explicitly when applying a period."))
        metrics = [("count", "", _("%s: record count", label))]
        for name in numeric:
            metrics += [("sum", name, _("%s: total %s", label, available[name]["string"])),
                        ("avg", name, _("%s: average %s", label, available[name]["string"]))]
        result = []
        for verb, field, title in metrics:
            spec = copy.deepcopy(base)
            spec.update({"title": title, "description": title, "builder_vals": copy.deepcopy(vals)})
            spec["builder_vals"].update({"title": title, "measure": {
                "verb": verb, "field": field, "label": title, "number_format": "plain", "compare_mode": "none"}})
            result.append(self._authoring_signed_metric(
                spec, "%s%s.%s.%s" % ("source" if source else "model", source.id if source else model.id, verb, field or "records")))
        return result

    def _authoring_tabular_metrics(self, source):
        columns = source.column_ids.sorted(lambda column: (column.sequence, column.id))
        if not columns:
            raise ValidationError(_("Refresh or import this source before creating a proposal."))
        dimensions = [{"field": column.name, "label": column.label or column.name}
                      for column in columns if column.dtype in ("text", "boolean", "date")][:_DIMENSION_LIMIT]
        dates = columns.filtered(lambda column: column.dtype == "date")
        # The existing tabular engine has a unique-date/default-date policy.
        # With multiple date columns offer grouping, but no ambiguous period.
        title = _("%s: row count", source.name)
        spec = {
            "title": title, "description": title,
            "builder_vals": {"source_id": source.id, "title": title, "item_type": "kpi",
                             "measure": {"verb": "count", "label": title, "number_format": "plain"},
                             "show_trend": False, "default_date_filter": "none"},
            "date_field": dates.name if len(dates) == 1 else "",
            "allowed_date_fields": [], "allowed_dimensions": dimensions,
            "allowed_charts": ["kpi", "tile", "bar", "hbar", "line"],
            "assumptions": [_('Uses the saved snapshot. This proposal does not contact the external service.'),
                            _("Only row counts are offered because snapshot columns have no verified currency or unit definitions."),
                            _("The snapshot is shared with the dashboard audience; Odoo record rules do not filter its rows.")],
            "source_token": {"id": source.id, "provider": source.provider_type,
                             "updated": str(source.write_date), "domain": source.get_domain(),
                             "columns": [(column.id, column.name, column.dtype) for column in columns]},
        }
        if len(dates) != 1:
            spec["allowed_date_presets"] = ["none"]
        return [self._authoring_signed_metric(spec, "source%s.count" % source.id)]

    def _create_authoring_metric(self, metric_id, overrides, catalog):
        spec = catalog[metric_id]
        if not spec.get("scoped"):
            return self._create_business_metric(metric_id, overrides)
        vals = copy.deepcopy(spec["builder_vals"])
        if spec.get("fixed_grouping"):
            vals.update({key: value for key, value in overrides.items() if key in {"title", "item_type"}})
        else:
            vals.update(overrides)
        if vals.pop("authoring_clean_source", False):
            # Do not silently pick up a differently filtered source on this board.
            Source = self.env["eh.board.datasource"]
            source = Source.search([("dashboard_id", "=", self.id), ("model_id", "=", vals["model_id"]),
                                    ("provider_type", "=", "orm"), ("domain", "in", [False, "[]"])], limit=1)
            if not source:
                source = Source.create({"dashboard_id": self.id, "provider_type": "orm",
                                        "model_id": vals["model_id"], "name": spec["title"], "domain": "[]"})
            vals["source_id"] = source.id
        vals["description"] = "\n".join([spec["description"]] + spec["assumptions"])
        return self.env["eh.board.item"].create(self._builder_item_vals(vals))
