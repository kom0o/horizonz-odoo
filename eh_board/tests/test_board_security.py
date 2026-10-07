# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Per-dashboard access control.

Proves the record rules the audit demanded: a plain Viewer sees only what they
own, what is shared with them, or what is published; a Builder/Admin is never
locked out of a board they must maintain.
"""
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "eh_board")
class TestBoardSecurity(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Users = cls.env["res.users"]
        cls.viewer = Users.create({
            "name": "Board Viewer", "login": "eh_board_viewer",
            "groups_id": [(6, 0, [cls.env.ref("eh_board.group_board_viewer").id])]})
        cls.builder = Users.create({
            "name": "Board Builder", "login": "eh_board_builder",
            "groups_id": [(6, 0, [cls.env.ref("eh_board.group_board_builder").id])]})
        Dash = cls.env["eh.board.dashboard"]
        cls.draft = Dash.create({"name": "Someone's draft", "state": "draft"})
        cls.published = Dash.create({"name": "Published", "state": "published"})
        cls.shared = Dash.create({
            "name": "Shared draft", "state": "draft",
            "shared_user_ids": [(6, 0, [cls.viewer.id])]})
        cls.all_ids = (cls.draft + cls.published + cls.shared).ids
        # A minimal item on the draft board so snapshot / alert (item_id NOT NULL)
        # can be created against a board the Viewer cannot open.
        cls.source = cls.env["eh.board.datasource"].create({
            "name": "P", "provider_type": "orm",
            "model_id": cls.env.ref("base.model_res_partner").id})
        cls.draft_item = cls.env["eh.board.item"].create({
            "dashboard_id": cls.draft.id, "item_type": "tile",
            "datasource_id": cls.source.id})

    def _visible_to(self, user):
        return self.env["eh.board.dashboard"].with_user(user).search(
            [("id", "in", self.all_ids)]).ids

    def test_viewer_cannot_see_others_draft(self):
        vis = self._visible_to(self.viewer)
        self.assertNotIn(self.draft.id, vis, "a draft must not leak to every viewer")

    def test_viewer_sees_published(self):
        self.assertIn(self.published.id, self._visible_to(self.viewer))

    def test_viewer_sees_shared_draft(self):
        self.assertIn(self.shared.id, self._visible_to(self.viewer))

    def test_builder_not_locked_out(self):
        # A Builder maintains every board, including drafts they do not own.
        self.assertIn(self.draft.id, self._visible_to(self.builder))

    def test_viewer_settings_do_not_enumerate_internal_users(self):
        settings = self.shared.with_user(self.viewer).get_settings()
        self.assertFalse(settings["can_edit"])
        self.assertEqual(settings["users"], [])

    def test_viewer_alerts_do_not_enumerate_internal_users(self):
        alerts = self.shared.with_user(self.viewer).get_alerts()
        self.assertFalse(alerts["can_edit"])
        self.assertEqual(alerts["users"], [])

    def test_group_restricted_hidden_from_non_members(self):
        # A published board restricted to a group the viewer is not in is hidden.
        restricted = self.env["eh.board.dashboard"].create({
            "name": "Restricted", "state": "published",
            "group_ids": [(6, 0, [self.env.ref("base.group_system").id])]})
        vis = self.env["eh.board.dashboard"].with_user(self.viewer).search(
            [("id", "=", restricted.id)]).ids
        self.assertNotIn(restricted.id, vis)

    def test_snapshot_not_leaked_to_viewer(self):
        # Snapshots store OWNER-scoped totals, so a Viewer (whose record rules may
        # be narrower) must never read them: snapshot read is builder-only now.
        from odoo.exceptions import AccessError
        snap = self.env["eh.board.snapshot"].create({
            "dashboard_id": self.draft.id, "item_id": self.draft_item.id,
            "label": "Secret KPI", "value": 999.0})
        leaked = True
        try:
            self.env["eh.board.snapshot"].with_user(self.viewer).search(
                [("id", "=", snap.id)])
        except AccessError:
            leaked = False
        self.assertFalse(leaked, "a Viewer could read snapshot history")

    def test_alert_not_leaked_to_viewer(self):
        # last_value / threshold of an unopenable board's alert must not leak.
        alert = self.env["eh.board.alert"].create({
            "name": "Secret alert", "dashboard_id": self.draft.id, "item_id": self.draft_item.id,
            "threshold": 100.0, "last_value": 999.0})
        vis = self.env["eh.board.alert"].with_user(self.viewer).search(
            [("id", "=", alert.id)]).ids
        self.assertNotIn(alert.id, vis, "alert (last_value) of an unopenable board leaked")

    def test_sql_results_admin_only(self):
        # A non-admin must not receive SQL-source data (a raw cursor bypasses
        # field-level ACLs, so the provider itself gates on the admin group).
        from ..lib.registry import get_datasource
        src = self.env["eh.board.datasource"].with_user(self.env.ref("base.user_root")).create({
            "name": "SQL src", "provider_type": "sql",
            "sql_query": "SELECT name, id FROM res_country"})
        res = get_datasource("sql").aggregate(src.with_user(self.viewer), {"limit": 5})
        self.assertTrue(res.get("error"), "viewer received SQL results")
        self.assertIn("admin", res["error"].lower())

    def test_sql_source_editor_is_not_offered_to_non_admin(self):
        """Builders may use a board but must never receive its SQL text."""
        from odoo.exceptions import AccessError
        source = self.env["eh.board.datasource"].create({
            "name": "Owned SQL", "provider_type": "sql",
            "dashboard_id": self.draft.id, "sql_query": "SELECT 1 AS value",
        })
        dashboard = self.draft.with_user(self.builder)
        metadata = dashboard.get_builder_meta()
        descriptor = next(item for item in metadata["sources"] if item["id"] == source.id)
        self.assertFalse(descriptor["editable"])
        with self.assertRaises(AccessError):
            _ = source.with_user(self.builder).sql_query
        with self.assertRaises(AccessError):
            dashboard.get_builder_source(source.id)
