# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
import math

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from ..lib.formula import compile_formula, FormulaError, ALLOWED_VARIABLES


class EhBoardMeasure(models.Model):
    _name = "eh.board.measure"
    _description = "Dashboard Measure"
    _order = "sequence, id"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    datasource_id = fields.Many2one(
        "eh.board.datasource", string="Data Source",
        required=True, ondelete="cascade")
    model_id = fields.Many2one(related="datasource_id.model_id", store=False)
    field_id = fields.Many2one(
        "ir.model.fields", string="Field", ondelete="cascade",
        domain="[('model_id', '=', model_id), "
               "('ttype', 'in', ('integer', 'float', 'monetary', "
               "'many2one', 'char', 'date', 'datetime', 'boolean'))]",
        help="The field to aggregate. Leave empty for a record count.",
    )
    field_name = fields.Char(related="field_id.name", store=True, readonly=True)
    # For tabular (file / REST) sources the measure points at a parsed column
    # instead of an ir.model.fields - no schema pollution, same spec contract.
    column_id = fields.Many2one(
        "eh.board.source.column", string="Column", ondelete="set null",
        domain="[('datasource_id', '=', datasource_id)]",
        help="The file column to aggregate (for a file data source).")
    aggregate = fields.Selection(
        [("sum", "Sum"), ("avg", "Average"), ("count", "Count"),
         ("count_distinct", "Distinct count"), ("min", "Minimum"),
         ("max", "Maximum"), ("formula", "Calculated (formula)")],
        required=True, default="sum",
    )
    formula = fields.Char(
        help="For a Calculated measure: arithmetic over the item's other "
             "measures as a, b, c ... in order. E.g. 'a / b * 100' for a margin.")

    @api.constrains("aggregate", "formula")
    def _check_formula(self):
        for rec in self:
            if rec.aggregate == "formula":
                try:
                    compiled = compile_formula(rec.formula or "0")
                except FormulaError as err:
                    raise ValidationError(str(err))
                # A misspelled or out-of-range variable (anything but a..f, the
                # positional base measures) would silently evaluate to 0.0 at
                # render time. Reject it at save so the mistake surfaces now.
                unknown = compiled.variables - ALLOWED_VARIABLES
                if unknown:
                    raise ValidationError(
                        "A formula may only reference the base measures a, b, c, "
                        "d, e, f (in order). Unknown name(s): %s."
                        % ", ".join(sorted(unknown)))
    unit = fields.Char(help="Suffix shown after the value, e.g. %, kg, orders.")
    as_line = fields.Boolean(
        string="Show as line",
        help="On a bar chart, draw THIS measure as a line overlay instead of a "
             "bar - a combo chart (e.g. revenue bars + margin-% line).")
    table_calculation = fields.Selection(
        [("none", "Value only"),
         ("percent_grand", "Value + % of grand total"),
         ("percent_row", "Value + % of row total"),
         ("percent_column", "Value + % of column total")],
        default="none", required=True,
        help="For grouped lists and pivots, add a percentage column beside the "
             "value. Pivot measures may compare against the row, column, or "
             "grand total; grouped lists use the grand total.\n"
             "The percentage is a true SHARE, adding up to 100%, only for Sum "
             "and Count. For Average, Minimum, Maximum and Distinct count the "
             "total is itself an average (or a min, or a max), so the column "
             "shows each row as a percentage OF that figure - 100% means "
             "exactly average - and is labelled '% of grand avg' rather than "
             "'% grand'.")
    currency_id = fields.Many2one("res.currency")
    number_format = fields.Selection(
        [("plain", "Plain"), ("thousands", "Thousands (K)"),
         ("millions", "Millions (M)"), ("compact", "Compact (K/M/B)")],
        default="compact",
    )
    multiplier = fields.Float(
        default=1.0, help="Scale the raw value, e.g. 0.001 to show thousands.")
    target_value = fields.Float(help="Optional goal used by KPI and gauge items.")
    target_schedule = fields.Json(
        default=lambda self: [],
        help="Date-effective targets as [{date: YYYY-MM-DD, value: number}]. "
             "The latest target on or before a period is used.")
    compare_mode = fields.Selection(
        [("none", "No comparison"), ("prev_period", "Previous period"),
         ("prev_year", "Same period last year")],
        default="none",
    )

    @api.model
    def _sanitize_target_schedule(self, schedule):
        """Canonical, bounded target history safe for JSON/UI rendering."""
        by_date = {}
        for point in (schedule if isinstance(schedule, list) else [])[:120]:
            if not isinstance(point, dict):
                continue
            try:
                target_date = fields.Date.to_date(point.get("date"))
                value = float(point.get("value"))
            except (TypeError, ValueError):
                continue
            if not target_date or not math.isfinite(value) or abs(value) > 1e18:
                continue
            by_date[target_date.isoformat()] = value
        return [{"date": target_date, "value": by_date[target_date]}
                for target_date in sorted(by_date)]

    @api.model_create_multi
    def create(self, vals_list):
        clean = []
        for vals in vals_list:
            vals = dict(vals)
            if "target_schedule" in vals:
                vals["target_schedule"] = self._sanitize_target_schedule(
                    vals.get("target_schedule"))
            clean.append(vals)
        return super().create(clean)

    def write(self, vals):
        vals = dict(vals)
        if "target_schedule" in vals:
            vals["target_schedule"] = self._sanitize_target_schedule(
                vals.get("target_schedule"))
        return super().write(vals)

    def target_at(self, on_date=None):
        """Resolve date-effective target; static target remains fallback."""
        self.ensure_one()
        schedule = self._sanitize_target_schedule(self.target_schedule or [])
        if not schedule:
            return self.target_value or 0.0
        try:
            anchor = fields.Date.to_date(on_date) if on_date else fields.Date.context_today(self)
        except (TypeError, ValueError):
            anchor = fields.Date.context_today(self)
        eligible = [point for point in schedule
                    if fields.Date.to_date(point["date"]) <= anchor]
        return eligible[-1]["value"] if eligible else (self.target_value or 0.0)

    def dated_targets_for_rows(self, rows):
        """One target per date-bucket row, empty for non-dated/static targets."""
        self.ensure_one()
        if not self.target_schedule:
            return []
        values = []
        for row in rows or []:
            key = (row.get("keys") or [None])[0]
            try:
                target_date = fields.Date.to_date(
                    key[:10] if isinstance(key, str) else key)
            except (TypeError, ValueError):
                return []
            if not target_date:
                return []
            values.append(self.target_at(target_date))
        return values

    @api.onchange("field_id")
    def _onchange_field_id(self):
        for rec in self:
            if rec.field_id and not rec.name:
                rec.name = rec.field_id.field_description or rec.field_id.name
            if rec.field_id and rec.field_id.ttype in ("many2one", "char", "boolean"):
                # Non-numeric fields can only be counted.
                if rec.aggregate in ("sum", "avg", "min", "max"):
                    rec.aggregate = "count_distinct"

    def measure_key(self):
        self.ensure_one()
        return "m_%s" % (self.id,)

    def apply_scale(self, value):
        self.ensure_one()
        return (value or 0.0) * (self.multiplier or 1.0)
