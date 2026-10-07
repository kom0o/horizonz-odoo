# -*- encoding: utf-8 -*-
"""Make existing weekly dispatcher evaluate new per-board schedules hourly."""

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    cron = env.ref("eh_board.cron_send_digests", raise_if_not_found=False)
    if cron:
        cron.write({"interval_number": 1, "interval_type": "hours"})
