"""Add versioned business packs without replacing saved user dashboards."""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env["eh.board.template"]._seed_predefined()
