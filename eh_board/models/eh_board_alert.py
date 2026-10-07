# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""KPI alerts - notify when a widget crosses a threshold.

Unlike the incumbent's one-shot "stop after first hit" flag, an alert re-arms
when the value recovers, so it fires on every genuine crossing rather than once
forever. Evaluation reuses the widget's own payload, so the number that trips
the alert is exactly the number on the board.
"""
import logging

from odoo import api, fields, models, SUPERUSER_ID

_logger = logging.getLogger(__name__)


class EhBoardAlert(models.Model):
    _name = "eh.board.alert"
    _description = "Dashboard Alert"
    _inherit = ["mail.thread"]
    _order = "name"

    name = fields.Char(required=True, default="Alert")
    active = fields.Boolean(default=True)
    dashboard_id = fields.Many2one(
        "eh.board.dashboard", required=True, ondelete="cascade", index=True)
    item_id = fields.Many2one(
        "eh.board.item", required=True, ondelete="cascade",
        domain="[('dashboard_id', '=', dashboard_id)]")
    operator = fields.Selection(
        [("gt", "greater than"), ("lt", "less than"),
         ("gte", "at least"), ("lte", "at most")],
        required=True, default="gt")
    threshold = fields.Float(required=True)
    user_id = fields.Many2one(
        "res.users", string="Notify", default=lambda self: self.env.user)
    state = fields.Selection(
        [("armed", "Armed"), ("triggered", "Triggered")],
        default="armed", tracking=True)
    last_value = fields.Float(readonly=True)
    last_triggered_on = fields.Datetime(readonly=True)

    def _current_value(self):
        self.ensure_one()
        # Aggregate as the notified user so the alert only trips on data that user
        # is actually allowed to see. An ARCHIVED regular user has no safe identity
        # to evaluate as - the cron runs as SUPERUSER, which would bypass every
        # record rule and email database-wide figures - so skip it. An alert
        # explicitly assigned to the system user is an admin's deliberate choice.
        user = self.user_id
        if not user or (not user.active and user.id != SUPERUSER_ID):
            return None
        item = self.item_id.with_user(user)
        return item._headline_value()

    def _crossed(self, value):
        self.ensure_one()
        t = self.threshold
        return {
            "gt": value > t, "lt": value < t,
            "gte": value >= t, "lte": value <= t,
        }.get(self.operator, False)

    def _evaluate(self):
        self.ensure_one()
        value = self._current_value()
        if value is None:
            return
        self.last_value = value
        if self._crossed(value):
            if self.state == "armed":
                self.state = "triggered"
                self.last_triggered_on = fields.Datetime.now()
                self._fire(value)
        elif self.state == "triggered":
            self.state = "armed"  # recovered -> re-arm for the next crossing

    def _fire(self, value):
        self.ensure_one()
        label = dict(self._fields["operator"].selection).get(self.operator)
        body = ("Alert '%s': %s is now %s (%s %s)." % (
            self.name, self.item_id.title or self.item_id.item_type,
            value, label, self.threshold))
        partners = self.user_id.partner_id.ids if self.user_id else []
        self.message_post(body=body, partner_ids=partners)

    @api.model
    def _cron_evaluate_alerts(self):
        for alert in self.search([("active", "=", True)]):
            # A savepoint per alert rolls back only the failing one and keeps
            # every alert evaluated earlier in this run; a blanket cr.rollback()
            # would discard them all.
            try:
                with self.env.cr.savepoint():
                    alert._evaluate()
            except Exception:  # noqa: BLE001
                _logger.exception("eh_board alert %s skipped", alert.id)
        return True
