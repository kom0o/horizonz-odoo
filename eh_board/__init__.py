# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
# Import the pure-Python engine first so the item-type and datasource
# registries are populated before any model resolves its selections.
from . import lib
from . import datasources
from . import items
from . import models
from . import controllers


def post_init_hook(cr_or_env, registry=None):
    env = cr_or_env
    if registry is not None:
        from odoo import api, SUPERUSER_ID
        env = api.Environment(cr_or_env, SUPERUSER_ID, {})
    env["eh.board.template"].sudo()._seed_predefined()
    _seed_demo(env)


def _seed_demo(env):
    """Ship a live welcome board so a fresh install is not a blank canvas.

    Guarded to run once; wrapped so a quirk in the host data never blocks the
    install. Uses only fields present on every Odoo (res.partner).
    """
    Dashboard = env["eh.board.dashboard"].sudo()
    if Dashboard.search_count([]):
        return
    try:
      # Scope any failure to a savepoint so a demo-seed quirk rolls back ONLY the
      # demo records, never the module's own install work on the shared cursor.
      with env.cr.savepoint():
        Field = env["ir.model.fields"]
        Item = env["eh.board.item"]
        partner_model = env["ir.model"]._get("res.partner")
        is_company = Field._get("res.partner", "is_company")
        country = Field._get("res.partner", "country_id")
        create_date = Field._get("res.partner", "create_date")
        source = env["eh.board.datasource"].create({
            "name": "Contacts", "provider_type": "orm", "model_id": partner_model.id})
        count = env["eh.board.measure"].create({
            "name": "Contacts", "datasource_id": source.id, "aggregate": "count"})
        target = env["eh.board.measure"].create({
            "name": "Contacts", "datasource_id": source.id, "aggregate": "count",
            "target_value": 12})
        dash = Dashboard.create({
            "name": "Welcome to Dashboard Builder", "state": "published"})
        source.dashboard_id = dash
        base = {"dashboard_id": dash.id, "datasource_id": source.id,
                "measure_ids": [(6, 0, count.ids)]}

        heading = Item.create({
            "dashboard_id": dash.id, "item_type": "richtext",
            "content": "<h2>Welcome to Dashboard Builder</h2>"
                       "<p>A live BI workspace, not a chart builder. Switch to "
                       "<b>Edit</b> to drag, resize and add widgets - every number "
                       "is grouped in the database and respects your access rules.</p>"})
        t_total = Item.create(dict(base, item_type="tile", title="Total contacts",
                                   accent="mint", tile_style="solid", icon="fa-users"))
        t_comp = Item.create(dict(base, item_type="tile", title="Companies",
                                  accent="blue", tile_style="soft", icon="fa-building",
                                  domain="[('is_company', '=', True)]"))
        t_ind = Item.create(dict(base, item_type="tile", title="Individuals",
                                 accent="violet", tile_style="soft", icon="fa-user",
                                 domain="[('is_company', '=', False)]"))
        t_month = Item.create(dict(base, item_type="kpi", title="Recent",
                                   accent="amber", tile_style="solid", icon="fa-calendar",
                                   conditional_rules=[
                                       {"op": "gte", "v1": 30, "v2": 0, "color": "#12b886", "style": "text"},
                                       {"op": "lt", "v1": 30, "v2": 0, "color": "#e8590c", "style": "text"}]))
        gauge = Item.create({
            "dashboard_id": dash.id, "item_type": "gauge", "title": "Progress to target",
            "datasource_id": source.id, "measure_ids": [(6, 0, target.ids)],
            "accent": "teal"})
        bar = Item.create(dict(base, item_type="bar", title="Companies vs individuals",
                               accent="blue", primary_dimension_id=is_company.id,
                               click_action="drill",
                               drill_ids=[(0, 0, {"field_id": country.id, "sequence": 10})]))
        pie = Item.create(dict(base, item_type="doughnut", title="Contacts by country",
                               accent="violet", primary_dimension_id=country.id))
        line = Item.create(dict(base, item_type="area", title="New contacts over time",
                                accent="mint", primary_dimension_id=create_date.id,
                                date_granularity="month"))
        listw = Item.create(dict(base, item_type="list", title="Contacts by country",
                                 primary_dimension_id=country.id,
                                 conditional_rules=[
                                     {"op": "gt", "v1": 0, "v2": 0, "color": "#2a78d6", "style": "bar"}]))
        funnel = Item.create(dict(base, item_type="funnel", title="Contacts funnel by country",
                                  accent="rose", primary_dimension_id=country.id))
        radar = Item.create(dict(base, item_type="radar", title="Shape by country",
                                 accent="indigo", primary_dimension_id=country.id))
        pivot = Item.create(dict(base, item_type="pivot",
                                 title="Contacts: type x country",
                                 primary_dimension_id=is_company.id,
                                 secondary_dimension_id=country.id))
        polar = Item.create(dict(base, item_type="polar", title="Countries (polar)",
                                 accent="teal", primary_dimension_id=country.id))
        heatmap = Item.create(dict(base, item_type="heatmap", title="Type x country heat",
                                   primary_dimension_id=is_company.id,
                                   secondary_dimension_id=country.id))
        bullet = Item.create({
            "dashboard_id": dash.id, "item_type": "bullet", "title": "Progress to target",
            "datasource_id": source.id, "measure_ids": [(6, 0, target.ids)], "accent": "amber"})
        hbar = Item.create(dict(base, item_type="hbar", title="Contacts by country (bars)",
                                accent="teal", primary_dimension_id=country.id))
        stacked = Item.create(dict(base, item_type="column", title="Type stacked by country",
                                   accent="violet", primary_dimension_id=is_company.id,
                                   secondary_dimension_id=country.id))
        radial = Item.create(dict(base, item_type="radial", title="Countries (radial)",
                                  accent="blue", primary_dimension_id=country.id))
        pyramid = Item.create(dict(base, item_type="pyramid", title="Countries (pyramid)",
                                   accent="rose", primary_dimension_id=country.id))
        scatter = Item.create(dict(base, item_type="scatter", title="Countries (scatter)",
                                   accent="amber", primary_dimension_id=country.id))
        slicer = Item.create(dict(base, item_type="slicer", title="Filter by country",
                                  primary_dimension_id=country.id))
        decomp = Item.create(dict(base, item_type="decomp", title="Contacts breakdown",
                                  accent="blue", primary_dimension_id=country.id,
                                  drill_ids=[(0, 0, {"field_id": is_company.id, "sequence": 10})]))

        grid = {
            str(heading.id): {"x": 0, "y": 0, "w": 12, "h": 2},
            str(t_total.id): {"x": 0, "y": 2, "w": 3, "h": 4},
            str(t_comp.id): {"x": 3, "y": 2, "w": 3, "h": 4},
            str(t_ind.id): {"x": 6, "y": 2, "w": 3, "h": 4},
            str(t_month.id): {"x": 9, "y": 2, "w": 3, "h": 4},
            str(bar.id): {"x": 0, "y": 6, "w": 6, "h": 7},
            str(pie.id): {"x": 6, "y": 6, "w": 3, "h": 7},
            str(gauge.id): {"x": 9, "y": 6, "w": 3, "h": 7},
            str(line.id): {"x": 0, "y": 13, "w": 8, "h": 6},
            str(listw.id): {"x": 8, "y": 13, "w": 4, "h": 6},
            str(funnel.id): {"x": 0, "y": 19, "w": 4, "h": 7},
            str(radar.id): {"x": 4, "y": 19, "w": 4, "h": 7},
            str(polar.id): {"x": 8, "y": 19, "w": 4, "h": 7},
            str(bullet.id): {"x": 0, "y": 26, "w": 4, "h": 3},
            str(heatmap.id): {"x": 4, "y": 26, "w": 8, "h": 7},
            str(hbar.id): {"x": 0, "y": 33, "w": 6, "h": 7},
            str(stacked.id): {"x": 6, "y": 33, "w": 6, "h": 7},
            str(radial.id): {"x": 0, "y": 40, "w": 4, "h": 7},
            str(pyramid.id): {"x": 4, "y": 40, "w": 4, "h": 7},
            str(scatter.id): {"x": 8, "y": 40, "w": 4, "h": 7},
            str(slicer.id): {"x": 0, "y": 47, "w": 12, "h": 3},
            str(decomp.id): {"x": 0, "y": 50, "w": 12, "h": 7},
            str(pivot.id): {"x": 0, "y": 57, "w": 12, "h": 7},
        }
        env["eh.board.layout.version"].create({
            "dashboard_id": dash.id, "name": "Default",
            "is_active": True, "is_default": True, "grid": grid})
        # A global field filter: pick a country and the whole board re-scopes.
        env["eh.board.filter"].create({
            "dashboard_id": dash.id, "name": "Country",
            "filter_type": "field", "field_id": country.id})
    except Exception:  # noqa: BLE001 - demo seed must never block install
        # The savepoint already rolled back just the demo records; do NOT touch
        # the outer cursor (a bare rollback here would undo the module install).
        import logging
        logging.getLogger(__name__).exception("eh_board demo seed skipped")
