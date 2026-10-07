"""Scorecard truth, explicit targets, context, isolation and atomic editing."""
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "eh_board")
class TestBoardScorecard(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.board = cls.env["eh.board.dashboard"].create({"name": "Scorecard fixture"})
        cls.owner = cls.env.ref("base.user_admin")
        cls.today = fields.Date.to_string(fields.Date.context_today(cls.board))
        cls.options = {"date_range": {"start": cls.today, "end": cls.today}}
        cls.partners = cls.env["res.partner"].create([
            {"name": "Score A", "color": 10, "country_id": cls.env.ref("base.au").id},
            {"name": "Score B", "color": 20, "country_id": cls.env.ref("base.au").id},
            {"name": "Score C", "color": 90, "country_id": cls.env.ref("base.us").id},
        ])
        cls.source = cls.env["eh.board.datasource"].create({
            "name": "Score partners", "provider_type": "orm", "dashboard_id": cls.board.id,
            "model_id": cls.env["ir.model"]._get("res.partner").id,
            "domain": repr([("id", "in", cls.partners.ids)]),
        })
        cls.measure = cls.env["eh.board.measure"].create({
            "name": "Average", "datasource_id": cls.source.id, "aggregate": "avg",
            "field_id": cls.env["ir.model.fields"]._get("res.partner", "color").id,
        })
        cls.item = cls.env["eh.board.item"].create({
            "title": "Full average", "dashboard_id": cls.board.id, "datasource_id": cls.source.id,
            "item_type": "bar", "primary_dimension_id": cls.env["ir.model.fields"]._get("res.partner", "country_id").id,
            "measure_ids": [(6, 0, cls.measure.ids)], "record_limit": 1,
            "date_filter_field_id": cls.env["ir.model.fields"]._get("res.partner", "create_date").id,
        })
        cls.count_measure = cls.measure.copy({"name": "Count", "aggregate": "count", "field_id": False})
        cls.count_item = cls.item.copy({"title": "Count", "measure_ids": [(6, 0, cls.count_measure.ids)]})
        cls.Node = cls.env["eh.board.scorecard.node"]

    def metric(self, key="metric", **values):
        return {"key": key, "parent_key": "", "kind": "metric", "name": "Progress",
                "item_id": self.item.id, "owner_id": self.owner.id,
                "date_from": self.today, "date_to": self.today, "weight": 1,
                "direction": "higher", "baseline": 0, "target": 100,
                "target_upper": 0, "baseline_upper": 0, "note": "Agreed by the owner", **values}

    def group(self, key="group", **values):
        return self.metric(key, kind="group", item_id=False, **values)

    def save(self, rows):
        return self.board.save_scorecard(rows, self.board._scorecard_revision(), self.options)

    def test_weighted_scores_use_full_scope_average_not_top_group(self):
        result = self.save([self.group(), self.metric("avg", parent_key="group", weight=3),
                            self.metric("count", parent_key="group", item_id=self.count_item.id, target=4)])
        group, average, count = result["results"]
        self.assertEqual(average["actual"], 40)
        self.assertEqual(average["score"], 40)
        self.assertEqual(count["score"], 75)
        self.assertEqual(group["score"], 48.75)
        self.assertIsNone(group["actual"])

    def test_direction_zero_targets_and_range_math(self):
        self.save([self.metric(direction="lower", baseline=100, target=0)])
        node = self.board.scorecard_node_ids
        self.assertEqual(node._normalized_score(0), 100)
        self.assertEqual(node._normalized_score(40), 60)
        self.assertEqual(node._normalized_score(-5), 100)
        self.assertEqual(node._normalized_score(200), 0)
        node.write({"direction": "range", "baseline": 0, "target": 20,
                    "target_upper": 30, "baseline_upper": 50})
        for actual, score in ((0, 0), (10, 50), (20, 100), (25, 100), (30, 100), (40, 50), (50, 0)):
            self.assertEqual(node._normalized_score(actual), score)
        self.assertIsNone(node._normalized_score(None))

    def test_current_filters_and_drill_are_applied(self):
        self.save([self.metric()])
        selected = dict(self.options, filters=[{"field": "country_id", "model": "res.partner",
                         "relation": "res.country", "values": [self.env.ref("base.au").id]}])
        self.assertEqual(self.board.get_scorecard(selected)["results"][0]["actual"], 15)
        field = self.env["ir.model.fields"]._get("res.partner", "is_company")
        self.item.drill_ids = [(0, 0, {"field_id": field.id})]
        path = [{"field": "country_id", "value": self.env.ref("base.au").id, "label": "Australia"}]
        drilled = dict(self.options, drill_paths={str(self.item.id): path})
        self.assertEqual(self.board.get_scorecard(drilled)["results"][0]["actual"], 15)

    def test_period_mismatch_does_not_score_other_dates(self):
        self.save([self.metric()])
        result = self.board.get_scorecard({})["results"][0]
        self.assertEqual(result["status"], "period")
        self.assertIsNone(result["score"])

    def test_missing_and_blocked_child_block_group_not_zero_or_reweight(self):
        self.save([self.group(), self.metric(parent_key="group")])
        with patch.object(type(self.item), "_headline_value", return_value=None):
            results = self.board.get_scorecard(self.options)["results"]
        self.assertTrue(all(row["score"] is None for row in results))
        self.item.unlink()
        results = self.board.get_scorecard(self.options)["results"]
        self.assertTrue(all(row["score"] is None for row in results))

    def test_explicit_zero_actual_is_not_missing(self):
        self.save([self.metric(direction="lower", baseline=100, target=0)])
        with patch.object(type(self.item), "_headline_value", return_value=0):
            result = self.board.get_scorecard(self.options)["results"][0]
        self.assertEqual(result["actual"], 0)
        self.assertEqual(result["score"], 100)

    def test_preview_rolls_back_and_stale_revision_cannot_overwrite(self):
        before = self.board._scorecard_revision()
        preview = self.board.preview_scorecard([self.metric()], before, self.options)
        self.assertEqual(preview["results"][0]["key"], "metric")
        self.assertEqual(preview["results"][0]["actual"], 40)
        self.assertFalse(self.board.scorecard_node_ids)
        self.assertEqual(self.board._scorecard_revision(), before)
        self.save([self.metric()])
        with self.assertRaises(UserError):
            self.board.save_scorecard([], before, self.options)
        self.assertEqual(len(self.board.scorecard_node_ids), 1)

    def test_invalid_graph_and_cross_board_replacement_are_atomic(self):
        self.save([self.metric()])
        revision = self.board._scorecard_revision()
        foreign = self.env["eh.board.dashboard"].create({"name": "Other board"})
        item = self.item.copy({"dashboard_id": foreign.id})
        cases = [
            [self.group("one", parent_key="two"), self.group("two", parent_key="one")],
            [self.metric(item_id=item.id)],
            [self.metric(weight=0)],
            [self.metric(target=0, baseline=0)],
            [self.metric(baseline=float("nan"))],
            [self.metric(date_from="2026-12-31", date_to="2026-01-01")],
            [self.group(), self.metric(parent_key="group", date_to="2027-01-01")],
        ]
        for rows in cases:
            with self.assertRaises(UserError):
                self.board.save_scorecard(rows, revision, self.options)
            self.assertEqual(self.board._scorecard_revision(), revision)

    def test_direct_orm_guards_cycle_depth_and_target_presence(self):
        values = {key: value for key, value in self.group().items() if key not in ("key", "parent_key")}
        values["dashboard_id"] = self.board.id
        root = self.Node.create(values)
        parent = root
        for _index in range(4):
            parent = self.Node.create(dict(values, parent_id=parent.id))
        with self.assertRaises(ValidationError):
            self.Node.create(dict(values, parent_id=parent.id))
        with self.assertRaises(ValidationError):
            root.write({"parent_id": parent.id})
        metric = dict(values, kind="metric", item_id=self.item.id)
        metric.pop("target")
        with self.assertRaises(ValidationError):
            self.Node.create(metric)
        self.assertFalse(root.parent_id)

    def test_formula_and_stale_remote_cannot_award_false_zero_target_success(self):
        self.save([self.metric(direction="lower", baseline=100, target=0)])
        original = type(self.board)._analysis_payload
        def stale(board, item, options):
            payload = original(board, item, options)
            payload["source_status"] = {"state": "stale"}
            return payload
        with patch.object(type(self.board), "_analysis_payload", stale):
            self.assertIsNone(self.board.get_scorecard(self.options)["results"][0]["score"])
        self.measure.write({"aggregate": "formula", "field_id": False, "formula": "1 / 0"})
        result = self.board.get_scorecard(self.options)["results"][0]
        self.assertIsNone(result["score"])

    def _viewer(self, suffix="viewer", company=None):
        User = self.env["res.users"].with_context(no_reset_password=True)
        company = company or self.env.company
        groups = "group_ids" if "group_ids" in User._fields else "groups_id"
        return User.create({"name": "Score " + suffix, "login": "score_" + suffix,
            "company_id": company.id, "company_ids": [(6, 0, company.ids)],
            groups: [(6, 0, [self.env.ref("base.group_user").id, self.env.ref("eh_board.group_board_viewer").id])]})

    def test_viewer_readonly_and_revocation_closes_config_and_rpc(self):
        self.save([self.metric()])
        user = self._viewer()
        self.board.shared_user_ids = [(4, user.id)]
        board = self.board.with_user(user)
        result = board.get_scorecard(self.options)
        self.assertFalse(result["can_edit"])
        self.assertEqual(result["results"][0]["actual"], 40)
        with self.assertRaises(AccessError):
            board.save_scorecard([], result["revision"], self.options)
        with self.assertRaises(AccessError):
            self.board.scorecard_node_ids.with_user(user).write({"target": 200})
        self.board.shared_user_ids = [(5, 0, 0)]
        with self.assertRaises(AccessError):
            board.get_scorecard(self.options)
        with self.assertRaises(AccessError):
            self.board.scorecard_node_ids.with_user(user).read(["target"])

    def test_other_company_cannot_read_or_change_scorecard(self):
        self.save([self.metric()])
        company = self.env["res.company"].create({"name": "Other score company"})
        user = self._viewer("other_company", company)
        self.board.state = "published"
        with self.assertRaises(AccessError):
            self.board.with_user(user).with_context(allowed_company_ids=company.ids).get_scorecard()
        nodes = self.Node.with_user(user).with_context(allowed_company_ids=company.ids).search([])
        self.assertNotIn(self.board.scorecard_node_ids.id, nodes.ids)

    def test_restricted_measure_blocks_actual_and_parent_without_error_details(self):
        self.save([self.group(), self.metric(parent_key="group")])
        user = self._viewer("restricted")
        self.board.shared_user_ids = [(4, user.id)]
        with patch.object(self.env["res.partner"]._fields["color"], "groups", "base.group_system"):
            result = self.board.with_user(user).get_scorecard(self.options)
        self.assertTrue(all(row["score"] is None for row in result["results"]))
        self.assertNotIn("res.partner", str(result["results"]))
        self.assertNotIn("90", str(result["results"]))
