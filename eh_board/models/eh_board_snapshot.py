# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Snapshot history - "what did this look like last month".

A cron captures each published dashboard's headline values into dated rows, so
a KPI can trend on real recorded history that survives edits to the source
records - a capability none of the incumbent dashboard modules ship.
"""
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class EhBoardSnapshot(models.Model):
    _name = "eh.board.snapshot"
    _description = "Dashboard Snapshot"
    _order = "captured_on desc, id desc"

    dashboard_id = fields.Many2one(
        "eh.board.dashboard", required=True, ondelete="cascade", index=True)
    item_id = fields.Many2one(
        "eh.board.item", required=True, ondelete="cascade", index=True)
    label = fields.Char()
    value = fields.Float()
    captured_on = fields.Datetime(default=fields.Datetime.now, index=True)

    @api.model
    def _cron_capture_snapshots(self):
        """Capture every published dashboard AS ITS OWNER, so the recorded
        figures respect the owner's record rules - a snapshot must never store
        numbers the owner could not see. Never let one bad board stop the run.
        """
        dashboards = self.env["eh.board.dashboard"].search([("state", "=", "published")])
        from odoo import SUPERUSER_ID
        for dash in dashboards:
            # Never capture rule-free totals: an ARCHIVED regular owner makes
            # _as_owner() fall through to the cron's superuser env and store
            # full-database numbers. Skip those. A board owned by the system user
            # (no narrower identity exists) is left to capture normally.
            owner = dash.owner_id
            if owner and not owner.active and owner.id != SUPERUSER_ID:
                continue
            # A savepoint per board rolls back only the failing one and KEEPS
            # every snapshot captured earlier in this run; a blanket
            # cr.rollback() would discard them all.
            try:
                with self.env.cr.savepoint():
                    dash._as_owner().capture_snapshot()
            except Exception:  # noqa: BLE001
                _logger.exception("eh_board snapshot skipped for dashboard %s", dash.id)
        self._purge_old_snapshots()
        return True

    def _purge_old_snapshots(self):
        """Bounded retention so the daily capture cannot grow the table forever.

        Keeps the configured number of days (default ~2 years); set the config
        parameter ``eh_board.snapshot_retention_days`` to 0 to keep everything."""
        from datetime import timedelta
        ICP = self.env["ir.config_parameter"].sudo()
        try:
            days = int(ICP.get_param("eh_board.snapshot_retention_days", 730) or 730)
        except (TypeError, ValueError):
            days = 730
        if days <= 0:
            return
        cutoff = fields.Datetime.now() - timedelta(days=days)
        # Batch the delete so one run never unlinks an unbounded number of rows.
        old = self.sudo().search([("captured_on", "<", cutoff)], limit=20000)
        if old:
            old.unlink()
