# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Credential vault.

The secret is restricted to the Dashboard Administrator group at the field
level, so a Builder or Viewer can reference a credential by name but can never
read its value; and it is never placed in a dashboard's JSON export. External
data providers must reference a vaulted credential rather than carrying a secret
inline - the gate the audit required before any external provider ships.
"""
from odoo import fields, models


class EhBoardCredential(models.Model):
    _name = "eh.board.credential"
    _description = "Dashboard Credential"
    _order = "name"

    name = fields.Char(required=True)
    kind = fields.Selection(
        [("api_key", "API key"), ("basic", "Username / password"), ("token", "Bearer token")],
        default="api_key", required=True)
    username = fields.Char()
    # Field-level group restriction: only Dashboard Administrators may read or
    # write the secret. It is deliberately never returned to the OWL client and
    # never serialised into a template or JSON export.
    secret = fields.Char(groups="eh_board.group_board_admin")
    note = fields.Char()
