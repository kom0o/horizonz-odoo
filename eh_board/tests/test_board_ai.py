# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Tests for the optional bring-your-own-key LLM layer.

The guarantee under test: the offline insight list is ALWAYS returned; the LLM
is a strictly-additive rewrite that degrades silently, sends only verified
facts, and never fires when unconfigured.
"""
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "eh_board")
class TestBoardAI(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Dashboard = cls.env["eh.board.dashboard"]
        cls.Datasource = cls.env["eh.board.datasource"]
        cls.Measure = cls.env["eh.board.measure"]
        cls.Item = cls.env["eh.board.item"]
        cls.ICP = cls.env["ir.config_parameter"].sudo()
        cls.AI = cls.env["eh.board.ai"]

        partner_model = cls.env["ir.model"]._get("res.partner")
        cls.partners = cls.env["res.partner"].create([
            {"name": "ACME Pty", "company_type": "company"},
            {"name": "Globex Pty", "company_type": "company"},
            {"name": "Alice", "company_type": "person"},
        ])
        cls.source = cls.Datasource.create({
            "name": "Partners",
            "provider_type": "orm",
            "model_id": partner_model.id,
            "domain": "[('id', 'in', %s)]" % cls.partners.ids,
        })
        cls.measure = cls.Measure.create({
            "name": "Records", "datasource_id": cls.source.id, "aggregate": "count"})
        cls.dashboard = cls.Dashboard.create({"name": "AI board"})
        # is_company is a STORED boolean; a computed field (company_type) would
        # be rejected by the aggregation guard and produce no insight to narrate.
        field = cls.env["ir.model.fields"]._get("res.partner", "is_company")
        cls.Item.create({
            "dashboard_id": cls.dashboard.id,
            "item_type": "bar",
            "title": "By type",
            "datasource_id": cls.source.id,
            "measure_ids": [(6, 0, cls.measure.ids)],
            "primary_dimension_id": field.id,
        })

    def _reset_ai(self):
        for key in ("provider", "model", "base_url", "credential", "word_cap"):
            self.ICP.set_param("eh_board.ai_%s" % key, "")

    # -- default: off --------------------------------------------------------
    def test_ai_off_by_default(self):
        self._reset_ai()
        self.assertFalse(self.AI.ai_available())
        res = self.dashboard.get_ai_insights()
        self.assertEqual(res["source"], "offline")
        # The offline insights match get_insights exactly - nothing was lost.
        self.assertEqual(res["insights"], self.dashboard.get_insights())
        self.assertFalse(res["narrative"])

    def test_ai_unavailable_without_credential(self):
        self._reset_ai()
        self.ICP.set_param("eh_board.ai_provider", "openai")
        self.ICP.set_param("eh_board.ai_model", "gpt-4o-mini")
        # No credential vaulted yet -> still unavailable, no button, no call.
        self.assertFalse(self.AI.ai_available())

    def _configure_ai(self, provider="openai"):
        cred = self.env["eh.board.credential"].create({
            "name": "AI Key", "kind": "api_key", "secret": "sk-test-123"})
        self.ICP.set_param("eh_board.ai_provider", provider)
        self.ICP.set_param("eh_board.ai_model", "test-model")
        self.ICP.set_param("eh_board.ai_credential", cred.name)
        return cred

    # -- configured + success -----------------------------------------------
    def test_ai_narrative_on_success(self):
        self._reset_ai()
        self._configure_ai("openai")
        self.assertTrue(self.AI.ai_available())

        sent = {}

        class _Resp:
            status_code = 200

            def json(self):
                return {"choices": [{"message": {"content": "Companies lead."}}]}

        def _fake_post(url, headers=None, data=None, timeout=None, allow_redirects=None):
            sent["url"] = url
            sent["data"] = data
            sent["allow_redirects"] = allow_redirects
            return _Resp()

        with patch("requests.post", _fake_post):
            res = self.dashboard.get_ai_insights()
        self.assertEqual(res["source"], "llm")
        self.assertEqual(res["narrative"], "Companies lead.")
        # Privacy: the payload must carry only verified facts, never DB creds,
        # the database name, raw record ids, or SQL.
        self.assertNotIn("psycopg2", sent["data"])
        self.assertNotIn("SELECT", sent["data"].upper())
        self.assertNotIn(self.env.cr.dbname, sent["data"])

    def test_ai_anthropic_shape(self):
        self._reset_ai()
        self._configure_ai("anthropic")

        class _Resp:
            status_code = 200

            def json(self):
                return {"content": [{"type": "text", "text": "Two companies, one person."}]}

        with patch("requests.post", lambda *a, **k: _Resp()):
            text = self.AI._narrate(["By type: 2 companies vs 1 person"])
        self.assertEqual(text, "Two companies, one person.")

    # -- configured + failure degrades --------------------------------------
    def test_ai_falls_back_on_http_error(self):
        self._reset_ai()
        self._configure_ai("openai")

        class _Resp:
            status_code = 500

            def json(self):
                return {}

        with patch("requests.post", lambda *a, **k: _Resp()):
            res = self.dashboard.get_ai_insights()
        self.assertEqual(res["source"], "offline")
        self.assertFalse(res["narrative"])
        self.assertEqual(res["insights"], self.dashboard.get_insights())

    def test_ai_falls_back_on_exception(self):
        self._reset_ai()
        self._configure_ai("openai")

        def _boom(*a, **k):
            raise TimeoutError("slow")

        with patch("requests.post", _boom):
            res = self.dashboard.get_ai_insights()
        self.assertEqual(res["source"], "offline")

    def test_ai_falls_back_on_garbage(self):
        self._reset_ai()
        self._configure_ai("openai")

        class _Resp:
            status_code = 200

            def json(self):
                return {"unexpected": True}

        with patch("requests.post", lambda *a, **k: _Resp()):
            res = self.dashboard.get_ai_insights()
        self.assertEqual(res["source"], "offline")
