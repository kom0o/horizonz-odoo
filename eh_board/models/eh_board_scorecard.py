# Copyright (C) 2026 ERP Heritage (https://www.erpheritage.com.au/)
"""Dashboard-owned, explicitly normalized KPI trees.

Actuals are never persisted: every read uses the caller's analysis context and
record rules. Group values combine dimensionless scores, never business units.
"""
import hashlib
import json
import math
import re

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

_MAX_NODES = 60
_MAX_DEPTH = 5
_CONFIG = ("name", "kind", "item_id", "owner_id", "date_from", "date_to",
           "weight", "direction", "baseline", "target", "target_upper",
           "baseline_upper", "note")


def _access(records, operation):
    if hasattr(records, "check_access"):
        records.check_access(operation)
    else:
        records.check_access_rights(operation)
        records.check_access_rule(operation)


class EhBoardScorecardNode(models.Model):
    _name = "eh.board.scorecard.node"
    _description = "Dashboard Scorecard Node"
    _order = "sequence, id"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    dashboard_id = fields.Many2one("eh.board.dashboard", required=True, ondelete="cascade", index=True)
    parent_id = fields.Many2one("eh.board.scorecard.node", ondelete="cascade", index=True)
    child_ids = fields.One2many("eh.board.scorecard.node", "parent_id")
    kind = fields.Selection([("group", "Weighted group"), ("metric", "Metric")], required=True, default="metric")
    item_id = fields.Many2one("eh.board.item", ondelete="set null")
    owner_id = fields.Many2one("res.users", required=True, default=lambda self: self.env.user)
    date_from = fields.Date(required=True, string="Effective from")
    date_to = fields.Date(required=True, string="Effective through")
    weight = fields.Float(required=True, default=1.0, help="Positive relative weight within the parent. A weight of 2 counts twice as much as 1.")
    direction = fields.Selection([("higher", "Higher is better"), ("lower", "Lower is better"), ("range", "Within a range")], required=True, default="higher")
    baseline = fields.Float(string="Zero-score baseline")
    target = fields.Float(string="Full-score target")
    target_upper = fields.Float(string="Full-score upper bound")
    baseline_upper = fields.Float(string="Zero-score upper bound")
    note = fields.Text(string="Target rationale")

    def _mutation_boards(self, values=None):
        boards = self.mapped("dashboard_id")
        if values and values.get("dashboard_id"):
            boards |= self.env["eh.board.dashboard"].browse(values["dashboard_id"])
        for board in boards.sorted("id"):
            board._require_edit()
            _access(board, "write")
            board._scorecard_lock()
            # Touch the parent row as well as locking it. Under PostgreSQL's
            # repeatable-read isolation, a waiter with an older snapshot must
            # retry instead of overwriting a concurrent child-only change.
            if hasattr(board, "invalidate_recordset"):
                board.invalidate_recordset(["scorecard_generation"])
            else:
                board.invalidate_cache(["scorecard_generation"])
            board.write({"scorecard_generation": board.scorecard_generation + 1})
        return boards

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._mutation_boards(vals)
            if vals.get("kind", "metric") == "metric" and not {"baseline", "target"}.issubset(vals):
                raise ValidationError(_("Enter an explicit baseline and target, including zero when intended."))
            if vals.get("kind", "metric") == "metric" and not vals.get("item_id"):
                raise ValidationError(_("Choose a metric widget from this dashboard."))
            if vals.get("direction") == "range" and not {"baseline", "target", "target_upper", "baseline_upper"}.issubset(vals):
                raise ValidationError(_("Enter both target bounds and both zero-score baselines for range scoring."))
        with self.env.cr.savepoint():
            records = super().create(vals_list)
            records._validate_tree()
            return records

    def write(self, vals):
        self._mutation_boards(vals)
        if "dashboard_id" in vals and any(node.dashboard_id.id != vals["dashboard_id"] for node in self):
            raise ValidationError(_("A scorecard node cannot move to another dashboard."))
        if vals.get("kind") == "metric" and any(node.kind == "group" for node in self) and not {"baseline", "target"}.issubset(vals):
            raise ValidationError(_("Enter an explicit baseline and target, including zero when intended."))
        with self.env.cr.savepoint():
            result = super().write(vals)
            self._validate_tree()
            return result

    def unlink(self):
        self._mutation_boards()
        return super().unlink()

    def _validate_tree(self):
        """Also guard direct ORM calls; UI validation is never authorization."""
        for board in self.mapped("dashboard_id"):
            nodes = self.search([("dashboard_id", "=", board.id)])
            if len(nodes) > _MAX_NODES:
                raise ValidationError(_("A scorecard supports at most 60 nodes."))
            for node in nodes:
                if not node.name.strip() or len(node.name) > 120 or len(node.note or "") > 2000:
                    raise ValidationError(_("Use a title of 1–120 characters and a rationale of at most 2,000 characters."))
                if not node.date_from or not node.date_to or node.date_from > node.date_to:
                    raise ValidationError(_("Choose a valid effective period for every scorecard node."))
                if not all(math.isfinite(node[key]) and abs(node[key]) <= 1e15 for key in ("weight", "baseline", "target", "target_upper", "baseline_upper")) or node.weight <= 0:
                    raise ValidationError(_("Targets and baselines must be finite numbers. Weights must be positive."))
                _access(node.owner_id, "read")
                if not node.owner_id.active or node.owner_id.share:
                    raise ValidationError(_("Choose an active internal user as the scorecard owner."))
                if node.parent_id:
                    _access(node.parent_id, "read")
                    if node.parent_id.dashboard_id != board or node.parent_id.kind != "group":
                        raise ValidationError(_("A parent must be a weighted group in the same dashboard."))
                    if (node.date_from, node.date_to) != (node.parent_id.date_from, node.parent_id.date_to):
                        raise ValidationError(_("A group and all its children must use the same effective period."))
                seen = set()
                current = node
                while current:
                    if current.id in seen:
                        raise ValidationError(_("A scorecard tree cannot contain a cycle."))
                    seen.add(current.id)
                    if len(seen) > _MAX_DEPTH:
                        raise ValidationError(_("A scorecard supports at most five levels."))
                    current = current.parent_id
                if node.kind == "group":
                    if node.item_id:
                        raise ValidationError(_("Weighted groups combine child scores and cannot reference a widget."))
                    continue
                if node.child_ids:
                    raise ValidationError(_("Only weighted groups can contain child nodes."))
                if node.item_id:
                    _access(node.item_id, "read")
                    if node.item_id.dashboard_id != board:
                        raise ValidationError(_("Choose a metric widget from this dashboard."))
                # A removed widget leaves a visibly unavailable node, not a zero.
                if node.direction == "higher" and node.target <= node.baseline:
                    raise ValidationError(_("For higher-is-better scoring, the target must exceed the baseline."))
                if node.direction == "lower" and node.target >= node.baseline:
                    raise ValidationError(_("For lower-is-better scoring, the target must be below the baseline."))
                if node.direction == "range" and not node.baseline < node.target <= node.target_upper < node.baseline_upper:
                    raise ValidationError(_("Range scoring requires: lower baseline < lower target ≤ upper target < upper baseline."))

    def _normalized_score(self, actual):
        self.ensure_one()
        if actual is None or isinstance(actual, bool) or not math.isfinite(actual):
            return None
        if self.direction == "higher":
            result = (actual - self.baseline) / (self.target - self.baseline)
        elif self.direction == "lower":
            result = (self.baseline - actual) / (self.baseline - self.target)
        elif actual < self.target:
            result = (actual - self.baseline) / (self.target - self.baseline)
        elif actual > self.target_upper:
            result = (self.baseline_upper - actual) / (self.baseline_upper - self.target_upper)
        else:
            result = 1.0
        return min(100.0, max(0.0, result * 100.0))

    def _score_explanation(self):
        self.ensure_one()
        if self.kind == "group":
            return _("Sum of each child score × its weight, divided by total child weight. Every child must have a score. Business amounts and currencies are never added.")
        if self.direction == "higher":
            return _("100 × (actual − baseline) / (target − baseline), capped between 0 and 100.")
        if self.direction == "lower":
            return _("100 × (baseline − actual) / (baseline − target), capped between 0 and 100.")
        return _("100 within the target range; linear progress from 0 at each outer baseline to 100 at the nearest target bound, capped between 0 and 100.")


class EhBoardScorecard(models.Model):
    _inherit = "eh.board.dashboard"

    scorecard_node_ids = fields.One2many("eh.board.scorecard.node", "dashboard_id", copy=False)
    scorecard_generation = fields.Integer(default=0, readonly=True, copy=False)

    def _scorecard_lock(self):
        self.ensure_one()
        # Only a configuration row lock; all metric reads use the caller ORM.
        self.env.cr.execute("SELECT id FROM eh_board_dashboard WHERE id = %s FOR UPDATE", [self.id])

    def _scorecard_config(self):
        self.ensure_one()
        _access(self, "read")
        nodes = self.scorecard_node_ids.sorted(lambda node: (node.sequence, node.id))
        _access(nodes, "read")
        result = []
        for node in nodes:
            row = {key: node[key] for key in _CONFIG}
            row.update({"key": str(node.id), "parent_key": str(node.parent_id.id) if node.parent_id else ""})
            for key in ("item_id", "owner_id"):
                row[key] = row[key].id or False
            for key in ("date_from", "date_to"):
                row[key] = fields.Date.to_string(row[key])
            result.append(row)
        return result

    def _scorecard_revision(self):
        value = {"generation": self.scorecard_generation, "nodes": self._scorecard_config()}
        return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()

    def _scorecard_item_problem(self, item):
        if not item or not item.exists():
            return _("The metric widget was removed. Choose another widget.")
        _access(item, "read")
        if not item.datasource_id or not item.measure_ids:
            return _("Choose a data widget with a numeric measure.")
        if item.measure_ids[:1].aggregate == "formula":
            return _("Calculated formulas are not eligible because undefined results can be displayed as zero. Choose a direct aggregate measure.")
        if item.datasource_id.provider_type in ("sql", "join") and item.item_type not in ("tile", "kpi", "gauge", "bullet"):
            return _("This source needs a scalar metric widget before it can be scored.")
        return ""

    def _scorecard_evaluate(self, options):
        nodes = self.scorecard_node_ids.sorted(lambda node: (node.sequence, node.id))
        values = {}
        actual_cache = {}
        today = fields.Date.context_today(self)
        period = options.get("date_range") or {}

        def evaluate(node, depth=0):
            if node.id in values:
                return values[node.id]
            result = {"key": str(node.id), "actual": None, "score": None, "status": "unavailable", "message": "", "definition": "", "unit": "", "currency": False, "policy": node._score_explanation()}
            values[node.id] = result
            if depth >= _MAX_DEPTH:
                result["message"] = _("This scorecard tree is invalid.")
                return result
            if period.get("start") != fields.Date.to_string(node.date_from) or period.get("end") != fields.Date.to_string(node.date_to):
                result.update(status="period", message=_("Select this node's complete effective period to compare its actual with its target."))
                return result
            if node.kind == "group":
                children = nodes.filtered(lambda child: child.parent_id == node)
                parts = [evaluate(child, depth + 1) for child in children]
                if not parts or any(part["score"] is None for part in parts):
                    result["message"] = _("Every child must have an available score. Missing or blocked children are not treated as zero or omitted.")
                    return result
                result.update(status="ok", score=sum(part["score"] * child.weight for part, child in zip(parts, children)) / sum(children.mapped("weight")))
                return result
            try:
                item = node.item_id
                problem = self._scorecard_item_problem(item)
                if problem:
                    result["message"] = problem
                    return result
                meta = item._meta()
                if (meta.get("current_balance") or not item._global_date_field()) and not node.date_from <= today <= node.date_to:
                    result["message"] = _("This widget shows a current balance or snapshot. It cannot score a historical target period.")
                    return result
                if item.id not in actual_cache:
                    scoped = item._drill_options(options.get("drill_paths", {}).get(str(item.id)), options)
                    payload = self._analysis_payload(item, options)
                    status = payload.get("source_status") or {}
                    if payload.get("error") or (status.get("state") and status["state"] != "fresh"):
                        actual_cache[item.id] = (None, payload)
                    else:
                        actual_cache[item.id] = (item._headline_value(scoped), payload)
                actual, payload = actual_cache[item.id]
                if actual is None or isinstance(actual, bool) or not isinstance(actual, (int, float)) or not math.isfinite(actual):
                    result["message"] = _("This metric is unavailable, blocked or stale for your current view. Its score has not been calculated.")
                    return result
                first = item.measure_ids[:1]
                currency = first.currency_id
                result.update(status="ok", actual=actual, score=node._normalized_score(actual), definition=item.description or _("Current widget definition; full-scope first measure with the selected filters and drill path."), unit=first.unit or "", currency={"code": currency.name, "symbol": currency.symbol} if currency else False)
            except (AccessError, UserError, ValueError, TypeError):
                # Do not serialize upstream errors, model names or hidden rows.
                result["message"] = _("This metric is unavailable, blocked or stale for your current view. Its score has not been calculated.")
            return result

        for node in nodes:
            evaluate(node)
        return [values[node.id] for node in nodes]

    def get_scorecard(self, options=None):
        self.ensure_one()
        options = self._analysis_options(options)
        config = self._scorecard_config()
        can_edit = self._can_edit()
        items = []
        for item in self.item_ids:
            try:
                problem = self._scorecard_item_problem(item)
                items.append({"id": item.id, "title": item.title or item.item_type, "unavailable": problem})
            except AccessError:
                continue
        owners = self.scorecard_node_ids.owner_id
        if can_edit:
            owners |= self.env["res.users"].search([("active", "=", True), ("share", "=", False)], limit=200) | self.env.user
        return {"nodes": config, "results": self._scorecard_evaluate(options), "revision": self._scorecard_revision(), "can_edit": can_edit, "default_owner_id": self.env.uid, "items": items, "owners": [{"id": owner.id, "name": owner.name} for owner in owners], "scope": self._analysis_scope(options), "options": options, "limits": {"nodes": _MAX_NODES, "depth": _MAX_DEPTH}, "notice": _("Targets are entered by an editor, never invented. Filters and drill paths change actuals but do not rescale targets. Scores range from 0 to 100; groups combine scores, not business amounts.")}

    def _scorecard_replace(self, rows, revision):
        self.ensure_one()
        self._require_edit()
        _access(self, "write")
        self._scorecard_lock()
        if hasattr(self, "invalidate_recordset"):
            self.invalidate_recordset(["scorecard_node_ids", "scorecard_generation"])
            self.env["eh.board.scorecard.node"].invalidate_model()
        else:
            self.invalidate_cache(["scorecard_node_ids", "scorecard_generation"])
            self.env["eh.board.scorecard.node"].invalidate_cache()
        if not isinstance(revision, str) or revision != self._scorecard_revision():
            raise UserError(_("The scorecard changed in another session. Reload it before saving."))
        if not isinstance(rows, list) or len(rows) > _MAX_NODES:
            raise ValidationError(_("A scorecard supports at most 60 nodes."))
        try:
            if len(json.dumps(rows, allow_nan=False)) > 150000:
                raise ValueError()
        except (ValueError, TypeError):
            raise ValidationError(_("The scorecard definition is invalid or too large."))
        clean = {}
        for index, row in enumerate(rows):
            if not isinstance(row, dict) or set(row) - set(_CONFIG) - {"key", "parent_key"}:
                raise ValidationError(_("The scorecard definition contains unsupported fields."))
            key = row.get("key")
            if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", key) or key in clean:
                raise ValidationError(_("Scorecard node keys must be unique."))
            vals = {name: row[name] for name in _CONFIG if name in row}
            if not isinstance(vals.get("name"), str) or vals.get("kind") not in ("group", "metric") or not all(name in vals for name in ("date_from", "date_to", "owner_id", "weight")):
                raise ValidationError(_("Complete the title, type, owner, effective period and weight for every node."))
            for field in ("owner_id", "item_id"):
                if vals.get(field) is not False and vals.get(field) is not None and type(vals[field]) is not int:
                    raise ValidationError(_("Choose valid scorecard owners and widgets."))
            for field in ("weight", "baseline", "target", "target_upper", "baseline_upper"):
                if field in vals and (type(vals[field]) not in (int, float) or not math.isfinite(vals[field])):
                    raise ValidationError(_("Enter finite numeric targets, baselines and weights."))
            if vals["kind"] == "metric":
                item = self._owned_item(vals.get("item_id"))
                problem = self._scorecard_item_problem(item)
                if problem:
                    raise ValidationError(problem)
            vals.update(dashboard_id=self.id, sequence=(index + 1) * 10)
            clean[key] = {"values": vals, "parent": row.get("parent_key") or ""}
        for entry in clean.values():
            if not isinstance(entry["parent"], str) or (entry["parent"] and entry["parent"] not in clean):
                raise ValidationError(_("A parent must be a weighted group in the same dashboard."))
        self.scorecard_node_ids.unlink()
        created = {}
        pending = dict(clean)
        while pending:
            progressed = False
            for key, entry in list(pending.items()):
                if entry["parent"] and entry["parent"] not in created:
                    continue
                vals = dict(entry["values"])
                vals["parent_id"] = created[entry["parent"]].id if entry["parent"] else False
                created[key] = self.env["eh.board.scorecard.node"].create(vals)
                pending.pop(key)
                progressed = True
            if not progressed:
                raise ValidationError(_("A scorecard tree cannot contain a cycle."))
        return created

    def save_scorecard(self, nodes, revision, options=None):
        options = self._analysis_options(options)
        with self.env.cr.savepoint():
            self._scorecard_replace(nodes, revision)
            return self.get_scorecard(options)

    def preview_scorecard(self, nodes, revision, options=None):
        options = self._analysis_options(options)
        class PreviewRollback(Exception):
            pass
        result = None
        try:
            with self.env.cr.savepoint():
                created = self._scorecard_replace(nodes, revision)
                result = self.get_scorecard(options)
                reverse = {str(node.id): key for key, node in created.items()}
                for row in result["nodes"]:
                    row["key"] = reverse[row["key"]]
                    row["parent_key"] = reverse.get(row["parent_key"], "")
                for row in result["results"]:
                    row["key"] = reverse[row["key"]]
                result["revision"] = revision
                raise PreviewRollback()
        except PreviewRollback:
            return result
