# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Cross-model join provider - combine two models without a line of SQL.

Each side is aggregated independently with ``_read_group`` (so record rules and
company scoping apply to both), then the two grouped results are merged in
Python on a shared key. This is the headline "join any two models" capability,
delivered without the live-cursor SQL concatenation the incumbents rely on: the
two reads stay rule-safe, and there is no raw join to inject into.

Config (stored on ``eh.board.datasource.config``)::

    {
      "left_model": "sale.order",  "join_left":  "user_id",
      "right_model": "account.move","join_right": "invoice_user_id",
      "left_measure":  {"verb": "sum", "field": "amount_total"},
      "right_measure": {"verb": "sum", "field": "amount_total"},
      "left_label": "Ordered", "right_label": "Invoiced"
    }
"""
from ..lib.registry import BoardDataSource, register_datasource
from ..lib import aggregation
from odoo.exceptions import UserError


@register_datasource
class JoinDataSource(BoardDataSource):
    key = "join"
    label = "Join two models"
    read_only = True
    external = False

    def aggregate(self, source, spec):
        cfg = source._join_config()
        if cfg.get("guided_query"):
            return source._guided_query_result(spec)
        env = source.env
        lm, rm = cfg.get("left_model"), cfg.get("right_model")
        if not (lm and rm and lm in env and rm in env):
            return {"rows": [], "measures": [], "dimensions": [],
                    "error": "Configure the join: pick two models and a shared field."}
        # Never silently drop an active domain. Showing an unfiltered total next
        # to a filtered total is a convincing lie. Join-specific mappings belong
        # in source config; until mapped, fail visibly.
        domain = spec.get("domain") or []
        left = self._side(env[lm], cfg.get("join_left"), cfg.get("left_measure"), domain)
        right = self._side(env[rm], cfg.get("join_right"), cfg.get("right_measure"), domain)
        rows, seen = [], set()
        for sk, d in left.items():
            rows.append({
                "keys": [d["key"]], "labels": [d["label"]],
                "values": {"left": d["val"], "right": right.get(sk, {}).get("val", 0.0)}})
            seen.add(sk)
        for sk, d in right.items():
            if sk in seen:
                continue
            rows.append({
                "keys": [d["key"]], "labels": [d["label"]],
                "values": {"left": 0.0, "right": d["val"]}})
        result = {
            "rows": rows, "measures": ["left", "right"],
            "dimensions": [cfg.get("join_left")],
            "measure_labels": {
                "left": cfg.get("left_label") or "Left",
                "right": cfg.get("right_label") or "Right"},
        }
        return aggregation.sort_and_cap(
            result, spec.get("sort", "value_desc"), spec.get("limit"))

    def _domain_ok(self, model, domain):
        """True when every field-leaf in the domain exists on this model, so the
        whole domain can be applied without unbalancing operators."""
        for leaf in domain or []:
            if isinstance(leaf, (list, tuple)) and len(leaf) == 3:
                fname = str(leaf[0]).split(".")[0]
                if fname not in model._fields:
                    return False
        return True

    def _side(self, model, key, measure, domain=None):
        measure = measure or {"verb": "count"}
        verb = measure.get("verb", "count")
        field = measure.get("field")
        token = "__count" if (verb == "count" or not field) \
            else aggregation.measure_aggregate_token(field, verb)
        groupby = [key] if key else []
        if not self._domain_ok(model, domain):
            missing = sorted({str(leaf[0]).split(".")[0] for leaf in domain or []
                              if isinstance(leaf, (list, tuple)) and len(leaf) == 3
                              and str(leaf[0]).split(".")[0] not in model._fields})
            raise UserError(
                "Join filter cannot be applied to %s; missing field(s): %s. "
                "Configure equivalent fields or remove that filter."
                % (model._description, ", ".join(missing)))
        dom = domain
        raw = aggregation.grouped_read(model, dom, groupby, [token],
                                       limit=aggregation._SAFETY_CAP)
        # Namespace the merge key by the RECORD SET it points at, so two sides
        # combine iff their keys reference the same kind of value. A many2one maps
        # to its comodel; grouping a model by its own "id" maps to that model - so
        # the classic "sale.order by partner_id  vs  res.partner by id" join lines
        # up (both -> res.partner), while user_id (res.users) vs partner_id
        # (res.partner), both plain ints, stay apart instead of merging unrelated
        # records that happen to share an id.
        field_def = model._fields.get(key) if key else None
        if field_def is None:
            ns = "raw"
        elif field_def.type == "many2one":
            ns = field_def.comodel_name
        elif key == "id":
            ns = model._name
        else:
            ns = field_def.type
        out = {}
        for tup in raw:
            gval = tup[0] if key else None
            val = tup[len(groupby)]
            val = 0.0 if val in (None, False) else val
            k = aggregation._group_key(gval)
            out["%s:%s" % (ns, k)] = {
                "key": k, "label": aggregation._label_for(gval), "val": val}
        return out

    def validate(self, source):
        cfg = source._join_config()
        problems = []
        if not cfg.get("left_model"):
            problems.append("Pick the first (left) model to join.")
        if not cfg.get("right_model"):
            problems.append("Pick the second (right) model to join.")
        return problems
