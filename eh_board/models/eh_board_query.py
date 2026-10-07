"""Bounded, rule-aware comparisons of independently grouped Odoo models."""
import ast
import hashlib
import json
from datetime import datetime, time, timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from ..lib import aggregation
from ..lib.formula import FormulaError, compile_formula, _eval

_GROUP_CAP = 1000
_AGGREGATES = {"count", "sum", "avg", "min", "max"}
_KEYS = {"many2one", "char", "selection", "integer", "boolean"}
_OPERATORS = {"=", "!=", ">", ">=", "<", "<=", "in", "not in", "ilike", "not ilike"}
_CHARTS = {"bar", "hbar", "line", "list"}
_PLAN_KEYS = {"version", "name", "company_id", "left", "right", "join_type", "formula", "formula_label", "chart_type", "limit"}
_SIDE_KEYS = {"model_id", "model", "key", "aggregate", "field", "label", "filters", "date_field", "date_start", "date_end"}


def _object(value, keys, message):
    if not isinstance(value, dict) or set(value) - keys:
        raise ValidationError(message)
    return value


def _read_access(record):
    if hasattr(record, "check_access"):
        record.check_access("read")
    else:
        record.check_access_rights("read")
        record.check_access_rule("read")


class EhBoardQuery(models.Model):
    _inherit = "eh.board.dashboard"

    def query_options(self, model_ids=None):
        self.ensure_one()
        self._require_edit()
        metadata = self.get_builder_meta()
        result = {
            "models": metadata["models"],
            "companies": [{"id": company.id, "name": company.name}
                          for company in self.env.companies],
            "company_id": self.env.company.id, "fields": {},
        }
        if model_ids is not None:
            if not isinstance(model_ids, list) or len(model_ids) > 2:
                raise ValidationError(_("Choose at most two models for a guided query."))
            for model_id in model_ids:
                Model = self._query_model({"model_id": model_id})
                definitions = Model.fields_get(attributes=["string", "type", "relation", "selection"])
                columns = []
                for name, info in definitions.items():
                    field = Model._fields[name]
                    if not field.store or field.type not in _KEYS | {"float", "monetary", "date", "datetime"}:
                        continue
                    columns.append({"name": name, "label": info.get("string") or name,
                                    "type": field.type, "relation": getattr(field, "comodel_name", None),
                                    "selection": info.get("selection") or [],
                                    "key": field.type in _KEYS,
                                    "numeric": field.type in {"integer", "float", "monetary"}})
                result["fields"][str(model_id)] = sorted(columns, key=lambda value: value["label"])
        return result

    def _query_model(self, side):
        if bool(side.get("model")) == bool(side.get("model_id")):
            raise ValidationError(_("Choose exactly one readable model for each side."))
        name = side.get("model")
        if not name:
            value = side.get("model_id")
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValidationError(_("Choose a valid model for each side."))
            model = self.env["ir.model"].sudo().browse(value).exists()
            name = model.model if model else None
        if not isinstance(name, str) or name not in self.env:
            raise ValidationError(_("Choose a valid model for each side."))
        Model = self.env[name]
        if Model._abstract or Model._transient:
            raise ValidationError(_("Guided queries require stored, non-transient models."))
        Model.check_access_rights("read")
        return Model

    def _query_field(self, Model, name, kinds=None):
        if not isinstance(name, str) or "." in name:
            raise ValidationError(_("Choose a direct, stored field for this query."))
        visible = Model.fields_get([name], attributes=["type"])
        field = Model._fields.get(name)
        if name not in visible:
            raise AccessError(_("This query uses a field you are not allowed to read."))
        if not field or not field.store or (kinds and field.type not in kinds):
            raise ValidationError(_("This field cannot be used in the selected query operation."))
        if field.type == "many2one":
            self.env[field.comodel_name].check_access_rights("read")
        return field

    def _query_value(self, field, value):
        if value is False or value is None:
            return False
        if field.type in {"integer", "many2one"}:
            if isinstance(value, bool):
                raise ValidationError(_("Enter a valid integer filter value."))
            try:
                parsed = int(value)
                if str(parsed) != str(value).strip():
                    raise ValueError()
                return parsed
            except (TypeError, ValueError):
                raise ValidationError(_("Enter a valid integer filter value."))
        if field.type in {"float", "monetary"}:
            import math
            try:
                parsed = float(value)
                if isinstance(value, bool) or not math.isfinite(parsed):
                    raise ValueError()
                return parsed
            except (TypeError, ValueError):
                raise ValidationError(_("Enter a finite numeric filter value."))
        if field.type == "boolean":
            if value in (True, "true", "True", "1", 1):
                return True
            if value in ("false", "False", "0", 0):
                return False
            raise ValidationError(_("Choose true or false for a boolean filter."))
        if not isinstance(value, str) or len(value) > 240:
            raise ValidationError(_("Filter text must contain at most 240 characters."))
        if field.type in {"date", "datetime"}:
            try:
                parsed = fields.Date.to_date(value) if field.type == "date" else fields.Datetime.to_datetime(value)
                if not parsed:
                    raise ValueError()
                return fields.Date.to_string(parsed) if field.type == "date" else fields.Datetime.to_string(parsed)
            except (ValueError, TypeError):
                raise ValidationError(_("Enter a valid date filter value."))
        return value

    def _normalize_query_side(self, side):
        _object(side, _SIDE_KEYS, _("Unsupported guided-query side settings."))
        Model = self._query_model(side)
        key = side.get("key")
        key_field = self._query_field(Model, key, _KEYS)
        aggregate = side.get("aggregate", "count")
        if not isinstance(aggregate, str) or aggregate not in _AGGREGATES:
            raise ValidationError(_("Choose Count, Sum, Average, Minimum or Maximum."))
        value_field = side.get("field") or ""
        if aggregate == "count":
            if value_field:
                raise ValidationError(_("A record count must not specify a value field."))
        else:
            self._query_field(Model, value_field, {"integer", "float", "monetary"})
        label = side.get("label") or Model._description
        if not isinstance(label, str) or not 1 <= len(label.strip()) <= 80:
            raise ValidationError(_("Each measure label must contain 1 to 80 characters."))
        filters = side.get("filters") or []
        if not isinstance(filters, list) or len(filters) > 12:
            raise ValidationError(_("Each side supports at most twelve filters."))
        clean_filters = []
        for item in filters:
            _object(item, {"field", "operator", "value"}, _("Invalid guided-query filter."))
            field = self._query_field(Model, item.get("field"), _KEYS | {"float", "monetary", "date", "datetime"})
            operator = item.get("operator")
            if not isinstance(operator, str) or operator not in _OPERATORS:
                raise ValidationError(_("This query filter operator is not supported."))
            if operator in {"ilike", "not ilike"} and field.type != "char":
                raise ValidationError(_("Text matching requires a text field."))
            value = item.get("value")
            if operator in {"in", "not in"}:
                if not isinstance(value, list) or not 1 <= len(value) <= 100:
                    raise ValidationError(_("A list filter requires 1 to 100 values."))
                value = [self._query_value(field, part) for part in value]
            else:
                if isinstance(value, (list, dict)):
                    raise ValidationError(_("Choose one scalar value for this filter."))
                value = self._query_value(field, value)
            clean_filters.append({"field": field.name, "operator": operator, "value": value})
        date_field = side.get("date_field") or ""
        start, end = side.get("date_start") or "", side.get("date_end") or ""
        if date_field:
            self._query_field(Model, date_field, {"date", "datetime"})
            try:
                first, last = fields.Date.to_date(start), fields.Date.to_date(end)
                if not first or not last or first > last:
                    raise ValueError()
                start, end = fields.Date.to_string(first), fields.Date.to_string(last)
            except (TypeError, ValueError):
                raise ValidationError(_("Choose a complete, valid date range for each dated side."))
        elif start or end:
            raise ValidationError(_("Choose a date field before entering a date range."))
        namespace = key_field.comodel_name if key_field.type == "many2one" else (
            Model._name if key == "id" else key_field.type)
        return {"model": Model._name, "key": key, "aggregate": aggregate,
                "field": value_field, "label": label.strip(), "filters": clean_filters,
                "date_field": date_field, "date_start": start, "date_end": end}, namespace

    def _normalize_query(self, plan):
        _object(plan, _PLAN_KEYS, _("Unsupported guided-query settings."))
        try:
            if len(json.dumps(plan, allow_nan=False)) > 16000:
                raise ValueError()
        except (ValueError, TypeError):
            raise ValidationError(_("The guided query is invalid or too large."))
        if type(plan.get("version", 1)) is not int or plan.get("version", 1) != 1:
            raise ValidationError(_("This guided-query version is not supported."))
        company_id = plan.get("company_id", self.env.company.id)
        if type(company_id) is not int or company_id not in self.env.companies.ids:
            raise AccessError(_("Choose a company available in your current session."))
        name = plan.get("name") or ""
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120:
            raise ValidationError(_("Name this analysis using 1 to 120 characters."))
        left, left_namespace = self._normalize_query_side(plan.get("left"))
        right, right_namespace = self._normalize_query_side(plan.get("right"))
        if left_namespace != right_namespace:
            raise ValidationError(_("Join keys must refer to the same related model or the same scalar type."))
        join_type = plan.get("join_type", "full")
        chart_type = plan.get("chart_type", "hbar")
        limit = plan.get("limit", 30)
        if not isinstance(join_type, str) or not isinstance(chart_type, str) or join_type not in {"inner", "left", "full"} or chart_type not in _CHARTS:
            raise ValidationError(_("Choose a supported comparison and chart type."))
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValidationError(_("Display between 1 and 100 joined groups."))
        expression = plan.get("formula") or ""
        label = plan.get("formula_label") or _("Calculated")
        if not isinstance(expression, str) or len(expression) > 240 or not isinstance(label, str) or len(label) > 80:
            raise ValidationError(_("The formula or its label is too long."))
        if expression:
            try:
                tree = ast.parse(expression, mode="eval")
                if sum(1 for _node in ast.walk(tree)) > 64:
                    raise FormulaError()
                fn = compile_formula(expression)
                if not fn.variables <= {"a", "b"}:
                    raise FormulaError()
            except (FormulaError, ValueError, SyntaxError, RecursionError):
                raise ValidationError(_("Use arithmetic with a and b only; function calls and other names are not allowed."))
        return {"version": 1, "name": name.strip(), "company_id": company_id,
                "left": left, "right": right, "join_type": join_type,
                "formula": expression.strip(), "formula_label": label.strip(),
                "chart_type": chart_type, "limit": limit}

    def _query_domain(self, side, Model, company_id):
        domain = [(item["field"], item["operator"], item["value"]) for item in side["filters"]]
        if "company_id" in Model._fields:
            self._query_field(Model, "company_id", {"many2one"})
            domain.append(("company_id", "in", [False, company_id]))
        if side["date_field"]:
            field = Model._fields[side["date_field"]]
            start, end = fields.Date.to_date(side["date_start"]), fields.Date.to_date(side["date_end"])
            if field.type == "datetime":
                zone = pytz.timezone(self.env.user.tz or "UTC")
                start = zone.localize(datetime.combine(start, time.min)).astimezone(pytz.UTC).replace(tzinfo=None)
                end = zone.localize(datetime.combine(end + timedelta(days=1), time.min)).astimezone(pytz.UTC).replace(tzinfo=None)
                domain.extend([(field.name, ">=", fields.Datetime.to_string(start)),
                               (field.name, "<", fields.Datetime.to_string(end))])
            else:
                domain.extend([(field.name, ">=", side["date_start"]), (field.name, "<=", side["date_end"])])
        return domain

    def _query_definition(self, plan):
        company = self.env["res.company"].browse(plan["company_id"])
        lines = [_("Two models are grouped independently before their keys are joined; matching records are never multiplied."),
                 _("Company: %s. Shared records are included when permitted by record rules.") % company.name]
        for variable, key in (("a", "left"), ("b", "right")):
            side = plan[key]
            Model = self.env[side["model"]]
            labels = Model.fields_get(attributes=["string"])
            operation = {"count": _("Count"), "sum": _("Sum"), "avg": _("Average"), "min": _("Minimum"), "max": _("Maximum")}[side["aggregate"]]
            measure = labels.get(side["field"], {}).get("string") or _("records")
            line = _("%(variable)s = %(operation)s of %(measure)s in %(model)s, grouped by %(key)s.") % {
                "variable": variable, "operation": operation, "measure": measure,
                "model": Model._description, "key": labels[side["key"]].get("string") or side["key"]}
            if side["date_field"]:
                line += " " + _("Dates: %(start)s to %(end)s (%(timezone)s).") % {
                    "start": side["date_start"], "end": side["date_end"], "timezone": self.env.user.tz or "UTC"}
            else:
                line += " " + _("All dates.")
            if side["filters"]:
                line += " " + _("All row filters must match: %s") % "; ".join(
                    "%s %s %s" % (labels[f["field"]].get("string") or f["field"], f["operator"], json.dumps(f["value"], ensure_ascii=False))
                    for f in side["filters"])
            lines.append(line)
        lines.append({"inner": _("Keep only keys present on both sides."), "left": _("Keep every left-side key, including keys with no right-side match."),
                      "full": _("Keep keys from either side, including unmatched keys.")}[plan["join_type"]])
        lines.append(_("Unassigned keys never match each other. Missing sides contribute zero. Access rules are applied again for every viewer."))
        lines.append(_("Saved side date ranges and filters define this analysis. Dashboard date filters do not replace them."))
        if plan["formula"]:
            lines.append(_("Formula: %s. Division by zero and non-finite results return zero.") % plan["formula"])
        return "\n".join(lines)

    def _execute_query(self, plan):
        plan = self._normalize_query(plan)
        company = self.env["res.company"].browse(plan["company_id"])
        context = dict(self.env.context, allowed_company_ids=[company.id])
        results, units = {}, {}
        for key in ("left", "right"):
            side = plan[key]
            Model = self.env[side["model"]].with_context(context)
            domain = self._query_domain(side, Model, company.id)
            value_field = Model._fields.get(side["field"])
            units[key] = "records" if side["aggregate"] == "count" else "number"
            if value_field and value_field.type == "monetary":
                currency_name = value_field.get_currency_field(Model) if hasattr(value_field, "get_currency_field") else value_field.currency_field
                self._query_field(Model, currency_name, {"many2one"})
                currencies = aggregation.grouped_read(Model, domain, [currency_name], ["__count"], limit=3)
                if any(aggregation._group_key(row[0]) != company.currency_id.id for row in currencies):
                    raise ValidationError(_("Monetary comparisons require both sides in the selected company's currency. Filter foreign-currency rows explicitly; no conversion is performed."))
                units[key] = "currency:%s" % company.currency_id.id
            token = "__count" if side["aggregate"] == "count" else aggregation.measure_aggregate_token(side["field"], side["aggregate"])
            raw = aggregation.grouped_read(Model, domain, [side["key"]], [token], limit=_GROUP_CAP + 1)
            if len(raw) > _GROUP_CAP:
                raise ValidationError(_("This comparison exceeds 1,000 groups on one side. Add filters before previewing; partial totals are not displayed."))
            grouped = {}
            for group, value in raw:
                group_key = aggregation._group_key(group)
                field = Model._fields[side["key"]]
                missing = group_key is None or (group_key is False and field.type != "boolean") or (group_key == "" and field.type == "char")
                merge_key = ("missing", key) if missing else ("value", type(group_key).__name__, str(group_key))
                grouped[merge_key] = {"key": None if missing else group_key,
                    "label": (_("Unassigned (%s)") % side["label"]) if missing else aggregation._label_for(group),
                    "value": 0.0 if value is None or value is False else value}
            results[key] = grouped
        if units["left"] != units["right"]:
            raise ValidationError(_("These measures have incompatible units. Compare counts with counts, numbers with numbers, or monetary fields in the same company currency."))
        left, right = results["left"], results["right"]
        keys = (left.keys() & right.keys()) if plan["join_type"] == "inner" else (
            left.keys() if plan["join_type"] == "left" else left.keys() | right.keys())
        expression = compile_formula(plan["formula"]) if plan["formula"] else None
        tree = ast.parse(plan["formula"], mode="eval") if expression else None
        rows, has_zero_divisor = [], False
        for key in keys:
            lrow, rrow = left.get(key), right.get(key)
            shown = lrow or rrow
            values = {"left": lrow["value"] if lrow else 0.0, "right": rrow["value"] if rrow else 0.0}
            zero_divisor = False
            if expression:
                variables = {"a": values["left"], "b": values["right"]}
                values["formula"] = expression(variables)
                zero_divisor = any(isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod))
                                   and not _eval(node.right, variables) for node in ast.walk(tree))
                has_zero_divisor = has_zero_divisor or zero_divisor
            rows.append({"keys": [shown["key"]], "labels": [shown["label"]], "values": values,
                         "matched": bool(lrow and rrow), "left_present": bool(lrow), "right_present": bool(rrow),
                         "zero_divisor": zero_divisor})
        rows.sort(key=lambda row: (-row["values"]["left"], str(row["labels"][0])))
        warnings = []
        if len(rows) > plan["limit"]:
            warnings.append(_("Showing the first %s groups by the left measure; additional groups are not displayed.") % plan["limit"])
        if has_zero_divisor:
            warnings.append(_("At least one formula has a zero denominator. Its result is shown as zero; review those rows before using the ratio."))
        if units["left"] == "number":
            warnings.append(_("Numeric field units are not converted. Check that these fields measure compatible quantities."))
        measure_keys = ["left", "right"] + (["formula"] if expression else [])
        return {"plan": plan, "rows": rows[:plan["limit"]], "group_count": len(rows),
                "measures": measure_keys, "dimensions": [plan["left"]["key"]],
                "measure_labels": {"left": plan["left"]["label"], "right": plan["right"]["label"], "formula": plan["formula_label"]},
                "measure_verbs": {"left": plan["left"]["aggregate"], "right": plan["right"]["aggregate"], "formula": "formula"},
                "unit": company.currency_id.name if units["left"].startswith("currency:") else (_("Records") if units["left"] == "records" else _("Number")),
                "unit_kind": "currency" if units["left"].startswith("currency:") else units["left"],
                "definition": self._query_definition(plan), "warnings": warnings, "warning": "\n".join(warnings)}

    def preview_query(self, plan):
        self.ensure_one()
        self._require_edit()
        # Reads only: no source, measure, widget or layout is created for preview.
        return self._execute_query(plan)

    def apply_query(self, plan):
        self.ensure_one()
        self._require_edit()
        with self.env.cr.savepoint():
            result = self._execute_query(plan)
            plan = result["plan"]
            source = self.env["eh.board.datasource"].create({
                "name": plan["name"], "provider_type": "join", "dashboard_id": self.id,
                "config": {"left_model": plan["left"]["model"], "right_model": plan["right"]["model"],
                           "join_left": plan["left"]["key"], "join_right": plan["right"]["key"], "guided_query": plan}})
            item = self._create_item_from_builder({"source_id": source.id, "title": plan["name"],
                "item_type": plan["chart_type"], "record_limit": plan["limit"], "sort_mode": "default",
                "default_date_filter": "none", "description": result["definition"], "click_action": "none"})
            payload = item.get_payload()
            if payload.get("error"):
                raise UserError(payload["error"])
            return {"source": self._source_meta(source), "meta": item._meta(), "payload": payload}

    def _restore_guided_query_config(self, config):
        """Portable definitions rebind company scope; they never replay record IDs."""
        self.ensure_one()
        self._require_edit()
        _object(config, {"guided_query", "guided_query_company"}, _("Invalid portable guided-query source."))
        if config.get("guided_query_company") != "current_company":
            raise ValidationError(_("Portable analyses must use the importing user's current company."))
        plan = config.get("guided_query")
        if not isinstance(plan, dict) or "company_id" in plan:
            raise ValidationError(_("Portable analyses must not contain database-specific company IDs."))
        for key in ("left", "right"):
            side = plan.get(key)
            if not isinstance(side, dict) or "model_id" in side or not isinstance(side.get("model"), str):
                raise ValidationError(_("Portable analyses must use model names instead of database-specific model IDs."))
        plan = self._normalize_query(dict(plan, company_id=self.env.company.id))
        self._validate_portable_query_filters(plan)
        return {"left_model": plan["left"]["model"], "right_model": plan["right"]["model"],
                "join_left": plan["left"]["key"], "join_right": plan["right"]["key"], "guided_query": plan}

    def _validate_portable_query_filters(self, plan):
        for side in (plan["left"], plan["right"]):
            if "model_id" in side:
                raise ValidationError(_("Portable analyses must use model names instead of database-specific model IDs."))
            Model = self.env[side["model"]]
            for condition in side["filters"]:
                field = Model._fields[condition["field"]]
                value = condition["value"]
                values = value if isinstance(value, list) else [value]
                if (field.type == "many2one" or field.name == "id") and any(value is not False for value in values):
                    raise ValidationError(_("This analysis filters specific record IDs. Replace those filters with portable names, states or dates before exporting or importing it."))

    def _source_meta(self, source):
        result = super()._source_meta(source)
        if source.provider_type == "join" and (source.config or {}).get("guided_query"):
            result.update({"guided_query": True, "editable": False})
        return result

    def _builder_item_vals(self, vals):
        if vals.get("source_id"):
            source = self._owned_source(vals["source_id"])
            if (source.config or {}).get("guided_query"):
                if source.dashboard_id != self:
                    raise AccessError(_("A guided query can only be used on its owning dashboard."))
                forbidden = {"model_id", "measure", "measures", "dimension", "secondary_dimension", "domain", "date_field", "drill_field", "drill_fields", "list_fields"}
                if any(vals.get(key) for key in forbidden) or vals.get("item_type", "hbar") not in _CHARTS:
                    raise ValidationError(_("This analysis owns its grouping, measures and filters. Create a new guided query to change its calculation."))
        return super()._builder_item_vals(vals)


class EhBoardQuerySource(models.Model):
    _inherit = "eh.board.datasource"

    def _guided_query_result(self, spec):
        self.ensure_one()
        board = self.dashboard_id
        if not board:
            raise AccessError(_("A guided query must belong to a dashboard."))
        _read_access(board)
        if spec.get("item_id"):
            item = self.env["eh.board.item"].browse(spec["item_id"]).exists()
            _read_access(item)
            if not item or item.datasource_id != self or item.dashboard_id != board:
                raise AccessError(_("A guided query can only be used on its owning dashboard."))
        if spec.get("domain"):
            raise ValidationError(_("This analysis uses separate filters for each side. Edit the guided query instead of applying a common row filter."))
        plan = (self.config or {}).get("guided_query")
        if spec.get("company_ids") and plan.get("company_id") not in spec["company_ids"]:
            raise AccessError(_("Select the company saved in this analysis to view its data."))
        result = board._execute_query(plan)
        # Units belong to the two base series. A ratio/formula is not labelled
        # with their currency or record unit because its dimensions may differ.
        if result["unit_kind"] == "currency":
            currency = self.env["res.company"].browse(result["plan"]["company_id"]).currency_id
            descriptor = {"id": currency.id, "code": currency.name,
                          "symbol": currency.symbol or currency.name, "position": currency.position,
                          "decimal_places": currency.decimal_places}
            spec["measure_currencies"] = {"left": descriptor, "right": descriptor}
        elif result["unit_kind"] == "records":
            spec["measure_units"] = {"left": _("Records"), "right": _("Records")}
        # Immutable definitions are revalidated for every reader, never sudoed.
        return result

    def _guided_authoring_metric(self):
        self.ensure_one()
        if self.provider_type != "join" or not (self.config or {}).get("guided_query"):
            return None
        board = self.dashboard_id
        _read_access(board)
        plan = board._normalize_query(self.config["guided_query"])
        fields_meta = {}
        for side in (plan["left"], plan["right"]):
            names = {side["key"], side["field"], side["date_field"]} | {value["field"] for value in side["filters"]}
            fields_meta.setdefault(side["model"], {}).update(self.env[side["model"]].fields_get(list(names - {""}), attributes=["type", "string", "relation"]))
        signature = json.dumps({"source": self.id, "board": board.id, "plan": plan, "fields": fields_meta}, sort_keys=True, default=str)
        return {"title": self.name, "description": board._query_definition(plan),
                "assumptions": [_('The source owns its grouping, measures and row filters.')],
                "allowed_dimensions": [], "allowed_chart_types": sorted(_CHARTS),
                "definition_token": hashlib.sha256(signature.encode()).hexdigest()}

    def _guided_portable_config(self):
        self.ensure_one()
        _read_access(self.dashboard_id)
        plan = self.dashboard_id._normalize_query((self.config or {}).get("guided_query"))
        self.dashboard_id._validate_portable_query_filters(plan)
        plan.pop("company_id")
        return {"guided_query": plan, "guided_query_company": "current_company"}

    @api.constrains("config", "dashboard_id", "provider_type")
    def _check_guided_query(self):
        for source in self:
            plan = (source.config or {}).get("guided_query")
            if not plan:
                continue
            actor = source.with_user(self.env.uid)
            if actor.provider_type != "join" or not actor.dashboard_id:
                raise ValidationError(_("A guided query requires a board-owned comparison source."))
            actor.dashboard_id._require_edit()
            actor.dashboard_id._normalize_query(plan)

    def write(self, vals):
        for source in self:
            if not (source.config or {}).get("guided_query"):
                continue
            source.dashboard_id._require_edit()
            if ("dashboard_id" in vals and vals["dashboard_id"] != source.dashboard_id.id) or ("provider_type" in vals and vals["provider_type"] != "join"):
                raise ValidationError(_("A saved guided query cannot be moved to another dashboard or provider."))
            if "config" in vals and vals["config"] != source.config:
                raise ValidationError(_("Create a new guided query to change a saved calculation. Existing analyses keep their original definition."))
        return super().write(vals)

    def copy_data(self, default=None):
        if any((source.config or {}).get("guided_query") for source in self):
            raise UserError(_("Create or import the guided analysis on the destination dashboard instead of copying its source."))
        return super().copy_data(default=default)
