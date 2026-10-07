# Copyright (C) 2026 ERP Heritage.
"""Portable scorecard definitions without database-local user or widget IDs."""
from odoo import _, models
from odoo.exceptions import ValidationError


class EhBoardPortable(models.Model):
    _inherit = "eh.board.dashboard"

    def _scorecard_portable_definition(self, item_refs):
        nodes = self._scorecard_config()
        key_refs = {row["key"]: "node_%s" % index for index, row in enumerate(nodes)}
        result = []
        for row in nodes:
            entry = dict(row)
            entry["key"] = key_refs[row["key"]]
            entry["parent_key"] = key_refs.get(row["parent_key"], "")
            entry["item_ref"] = item_refs.get(entry.pop("item_id"), "")
            entry.pop("owner_id")
            result.append(entry)
        return {"version": 1, "owner_policy": "importing_user", "nodes": result}

    def _restore_portable_scorecard(self, definition, item_refs):
        if definition is None:
            return
        if (not isinstance(definition, dict) or set(definition) != {"version", "owner_policy", "nodes"}
                or definition.get("version") != 1 or definition.get("owner_policy") != "importing_user"
                or not isinstance(definition.get("nodes"), list) or len(definition["nodes"]) > 60):
            raise ValidationError(_("The portable scorecard definition is invalid."))
        nodes = []
        for row in definition["nodes"]:
            if not isinstance(row, dict) or "item_id" in row or "owner_id" in row:
                raise ValidationError(_("Portable scorecards must use widget references, not database record IDs."))
            node = dict(row)
            ref = node.pop("item_ref", "")
            if not isinstance(ref, str) or (node.get("kind") == "metric" and ref not in item_refs):
                raise ValidationError(_("A scorecard metric could not be restored. Restore its widget before importing the scorecard."))
            node["item_id"] = item_refs[ref].id if ref in item_refs else False
            node["owner_id"] = self.env.uid
            nodes.append(node)
        self._scorecard_replace(nodes, self._scorecard_revision())
