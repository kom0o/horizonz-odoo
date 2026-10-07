"""Remote connection contracts: no network in rendering, bounded reads, safe secrets."""
import json
import socket
import sys
import types
import unittest
from datetime import timedelta
from unittest.mock import MagicMock, patch

from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tests.common import new_test_user

from ..lib import remote
from ..lib import tabular
from ..lib.registry import get_datasource


class TestRemoteHelpers(unittest.TestCase):
    def test_rejects_private_credentials_and_redirect_shaped_urls(self):
        for url in ("http://example.com/data", "https://127.0.0.1/data", "https://[::1]/data",
                    "https://169.254.169.254/latest", "https://user:secret@example.com/data",
                    "https://example.com/data?access_token=secret", "https://example.com:8443/data",
                    "https://internal.local/data", "https://example.com/\nsecret"):
            with self.subTest(url=url), self.assertRaises(remote.RemoteError) as caught:
                remote.destination(url, resolve=False)
            self.assertEqual(caught.exception.code, "unsafe_url")

    def test_rejects_mixed_public_private_dns(self):
        answers = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
                   (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443))]
        with patch.object(remote.socket, "getaddrinfo", return_value=answers), self.assertRaises(remote.RemoteError):
            remote.destination("https://example.com/data")

    def test_transport_pins_ip_and_verifies_hostname(self):
        answers = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
        sock, conn, context, response = MagicMock(), MagicMock(), MagicMock(), MagicMock()
        response.status = 200
        response.getheader.side_effect = lambda name, default=None: {"Content-Length": "2"}.get(name, default)
        response.read1.side_effect = [b"[]", b""]
        conn.getresponse.return_value = response
        with patch.object(remote.socket, "getaddrinfo", return_value=answers) as dns, \
                patch.object(remote.socket, "socket", return_value=sock), \
                patch.object(remote.ssl, "create_default_context", return_value=context), \
                patch.object(remote.http.client, "HTTPSConnection", return_value=conn):
            self.assertEqual(remote.request_bytes("https://example.com/data"), b"[]")
        sock.connect.assert_called_once_with(("93.184.216.34", 443))
        context.wrap_socket.assert_called_once_with(sock, server_hostname="example.com")
        dns.assert_called_once()

    def test_schema_and_numeric_drift_rejected(self):
        with self.assertRaises(remote.RemoteError):
            remote.table(["A B", "A-B"], [["one", "two"]])
        with self.assertRaises(remote.RemoteError):
            remote.table(["amount"], [["5"]] * 201 + [["broken"]])
        with self.assertRaises(remote.RemoteError):
            remote.table(["amount"], [[{"nested": 1}]])

    def test_rest_pagination_complete_or_rejected(self):
        config = {"url": "https://example.com/data", "path": "/data/items", "pagination": "page", "page_size": 1, "max_pages": 2}
        with patch.object(remote, "request_bytes", side_effect=[b'{"data":{"items":[{"amount":5}]}}', b'{"data":{"items":[]}}']) as request:
            parsed = remote.fetch_rest(config)
        self.assertEqual(parsed["rows"], [{"amount": 5.0}])
        self.assertIn("page=2", request.call_args[0][0])
        with patch.object(remote, "request_bytes", return_value=b'{"data":{"items":[{"amount":5}]}}'), self.assertRaises(remote.RemoteError) as caught:
            remote.fetch_rest(config)
        self.assertEqual(caught.exception.code, "page_limit")

    def test_json_path_size_and_invalid_json(self):
        self.assertEqual(remote.pointer({"a/b": {"~key": [1]}}, "/a~1b/~0key/0"), 1)
        with self.assertRaises(remote.RemoteError):
            remote.pointer({"items": []}, "$.items")
        with self.assertRaises(remote.RemoteError):
            remote.parse_json(b'{"amount":NaN}')
        with self.assertRaises(remote.RemoteError):
            remote.table(["amount"], [[1]] * (remote.MAX_ROWS + 1))

    def test_snapshot_filters_never_ignore_unknown_columns(self):
        rows = [{"team": "West", "amount": 10}, {"team": "East", "amount": 20}]
        selected = remote.filter_rows(rows, ["|", ("team", "=", "West"), ("amount", ">", 30)], {"team", "amount"})
        self.assertEqual(selected, [rows[0]])
        with self.assertRaises(remote.RemoteError):
            remote.filter_rows(rows, [("partner_id", "=", 1)], {"team", "amount"})
        with self.assertRaises(remote.RemoteError):
            remote.filter_rows(rows, [("team", "child_of", 1)], {"team", "amount"})

    def test_table_filter_prefix_logic_dates_and_empty_zero(self):
        rows = [{"team": "West", "amount": 10, "date": "2026-09-21T12:00:00"},
                {"team": "East", "amount": 20, "date": "2026-09-22T23:59:59"}]
        domain = ["&", "!", ("team", "=", "West"), "|", ("amount", "<", 0), ("amount", "=", 20),
                  ("date", ">=", "2026-09-22"), ("date", "<", "2026-09-23")]
        self.assertEqual(tabular.filter_records(rows, domain, rows[0]), [rows[1]])
        empty = tabular.filter_records(rows, [("amount", ">", 100)], rows[0])
        result = tabular.aggregate_records(empty, [], [{"key": "count", "verb": "count"}, {"key": "sum", "verb": "sum", "field": "amount"}])
        self.assertEqual(result["rows"][0]["values"], {"count": 0.0, "sum": 0.0})
        for invalid in (["|", ("team", "=", "West")], [("missing", "=", False)], [("amount", "child_of", 1)], [(["team"], "=", "West")]):
            with self.assertRaises(tabular.TabularError):
                tabular.filter_records([], invalid, rows[0])

    def test_sheets_uses_bounded_range_and_read_values(self):
        with patch.object(remote, "request_bytes", return_value=b'{"values":[["Team","Amount"],["West",12]]}') as request:
            parsed = remote.fetch_sheets("valid_sheet_id_123", "Plan!A1:B1001", {"Authorization": "Bearer protected"})
        self.assertEqual(parsed["rows"], [{"team": "West", "amount": 12.0}])
        self.assertIn("sheets.googleapis.com/v4/spreadsheets/", request.call_args[0][0])
        with patch.object(remote, "request_bytes") as request, self.assertRaises(remote.RemoteError):
            remote.fetch_sheets("valid_sheet_id_123", "Plan!A:Z", {})
        request.assert_not_called()

    def test_service_account_transport_and_readonly_scope(self):
        credential = MagicMock(token="fresh-token")
        def refresh(request):
            response = request(remote.TOKEN_URL, method="POST", body=b"assertion=protected", headers={"Content-Type": "application/x-www-form-urlencoded"})
            self.assertEqual(response.status, 200)
        credential.refresh.side_effect = refresh
        info = {"type": "service_account", "client_email": "reader@example.iam.gserviceaccount.com", "token_uri": "https://private.invalid/token"}
        google, oauth2, service_account = types.ModuleType("google"), types.ModuleType("google.oauth2"), types.ModuleType("google.oauth2.service_account")
        google.__path__, oauth2.__path__ = [], []
        google.oauth2, oauth2.service_account = oauth2, service_account
        service_account.Credentials = MagicMock()
        service_account.Credentials.from_service_account_info.return_value = credential
        make = service_account.Credentials.from_service_account_info
        with patch.dict(sys.modules, {"google": google, "google.oauth2": oauth2, "google.oauth2.service_account": service_account}), \
                patch.object(remote, "request_bytes", return_value=b'{"access_token":"fresh-token"}') as request:
            self.assertEqual(remote.service_account_token(json.dumps(info)), "fresh-token")
        self.assertEqual(make.call_args[1]["scopes"], [remote.SHEETS_SCOPE])
        self.assertEqual(make.call_args[0][0]["token_uri"], remote.TOKEN_URL)
        self.assertEqual(request.call_args[0][0], remote.TOKEN_URL)


@tagged("post_install", "-at_install", "eh_board")
class TestBoardRemote(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Source = cls.env["eh.board.datasource"]
        cls.board = cls.env["eh.board.dashboard"].create({"name": "Remote audit"})
        cls.viewer = new_test_user(cls.env, login="remote_viewer", groups="eh_board.group_board_viewer")
        cls.builder = new_test_user(cls.env, login="remote_builder", groups="eh_board.group_board_builder")

    def _source(self):
        return self.Source.create({"name": "Orders", "provider_type": "rest", "dashboard_id": self.board.id,
                                   "remote_url": "https://example.com/orders", "remote_audience_ack": True})

    def _refresh(self, source, parsed):
        with patch.object(type(source), "_fetch_remote", return_value=parsed):
            self.assertTrue(source._refresh_remote_snapshot())

    def test_failed_refresh_retains_last_snapshot_and_columns(self):
        source = self._source()
        parsed = remote.table(["Team", "Amount"], [["West", 10]])
        self._refresh(source, parsed)
        ids = source.column_ids.ids
        success = source.remote_last_success
        with patch.object(type(source), "_fetch_remote", side_effect=RuntimeError("SECRET api_token=never-show")):
            self.assertFalse(source._refresh_remote_snapshot())
        self.assertEqual(source._load_rows_cache(), parsed["rows"])
        self.assertEqual(source.column_ids.ids, ids)
        self.assertEqual(source.remote_last_success, success)
        self.assertEqual(source.remote_state, "stale")
        self.assertNotIn("SECRET", source.remote_last_error)
        self.assertGreater(source.remote_next_refresh, fields.Datetime.now())

    def test_schema_change_retains_previous_and_additions_preserve_identity(self):
        source = self._source()
        self._refresh(source, remote.table(["Team", "Amount"], [["West", 10]]))
        amount = source.column_ids.filtered(lambda c: c.name == "amount")
        self._refresh(source, remote.table(["Team", "Amount", "Region"], [["East", 20, "AU"]]))
        self.assertEqual(source.column_ids.filtered(lambda c: c.name == "amount"), amount)
        with patch.object(type(source), "_fetch_remote", return_value=remote.table(["Team"], [["North"]])):
            self.assertFalse(source._refresh_remote_snapshot())
        self.assertEqual(source.remote_error_code, "schema")
        self.assertEqual(source._load_rows_cache()[0]["amount"], 20.0)

    def test_configuration_raw_rows_and_refresh_admin_only(self):
        source = self._source()
        for user in (self.viewer, self.builder):
            with self.assertRaises(AccessError):
                source.with_user(user).action_refresh_remote()
            with self.assertRaises(AccessError):
                source.with_user(user).tabular_rows()
            with self.assertRaises(AccessError):
                self.Source.with_user(user).remote_config(self.board.id, source.id)
            with self.assertRaises(AccessError):
                source.with_user(user).write({"remote_url": "https://example.com/new"})

    def test_config_never_returns_secret_and_expired_token_does_not_fetch(self):
        source = self._source()
        credential = self.env["eh.board.credential"].create({"name": "API", "kind": "token", "secret": "NEVER-RETURN"})
        source.write({"remote_auth": "bearer", "credential_id": credential.id,
                      "remote_token_expires": fields.Datetime.now() - timedelta(hours=1)})
        config = self.Source.remote_config(self.board.id, source.id)
        self.assertNotIn("NEVER-RETURN", json.dumps(config))
        with patch.object(remote, "request_bytes") as request:
            self.assertFalse(source._refresh_remote_snapshot())
        self.assertEqual(source.remote_error_code, "expired")
        request.assert_not_called()

    def test_view_does_not_refresh_upstream(self):
        source = self._source()
        self._refresh(source, remote.table(["Team", "Amount"], [["West", 10]]))
        with patch.object(remote, "request_bytes") as request:
            self.assertEqual(source._tabular_rows()[0]["amount"], 10.0)
        request.assert_not_called()

    def test_remote_builder_and_portable_reconnect_preserve_columns(self):
        source = self._source()
        self._refresh(source, remote.table(["Team", "Amount"], [["West", 10], ["East", 20]]))
        item = self.board._create_item_from_builder({"source_id": source.id, "item_type": "bar", "title": "Amount",
            "dimension": "team", "measures": [{"field": "amount", "verb": "sum", "label": "Amount"}]})
        self.assertTrue(item.primary_column_id)
        self.assertTrue(item.measure_ids.column_id)
        self.assertFalse(item.get_payload().get("error"))
        definition = self.board._definition_payload()
        text = json.dumps(definition)
        self.assertNotIn("example.com", text)
        self.assertNotIn("credential_id", text)
        exported = next(s["source"] for s in definition["items"] if s.get("source", {}).get("requires_remote"))
        self.assertEqual(exported["provider"], "file")
        destination = self.env["eh.board.dashboard"].create({"name": "Destination"})
        placeholder = self.env["eh.board.template"]._materialise_source(destination, exported, {})
        ids = placeholder.column_ids.ids
        self.Source.remote_save_config(destination.id, {"provider": "rest", "name": "Reconnected",
            "remote_url": "https://example.com/orders", "remote_auth": "none", "remote_audience_ack": True}, placeholder.id)
        self._refresh(placeholder, remote.table(["Team", "Amount"], [["West", 40]]))
        self.assertEqual(placeholder.column_ids.ids, ids)
        self.assertEqual(placeholder.provider_type, "rest")

    def test_remote_source_filter_and_record_limit(self):
        source = self._source()
        self._refresh(source, remote.table(["Team", "Amount"], [["West", 10], ["East", 20]]))
        item = self.board._create_item_from_builder({"source_id": source.id, "item_type": "tile", "title": "Amount",
            "domain": "[('team', '=', 'East')]", "measures": [{"field": "amount", "verb": "sum", "label": "Amount"}]})
        provider = get_datasource("rest")
        spec = item._resolve_spec(no_dimension=True)
        result = provider.aggregate(source, spec)
        self.assertEqual(list(result["rows"][0]["values"].values()), [20.0])
        spec["domain"] = [("team", "=", "Missing")]
        result = provider.aggregate(source, spec)
        self.assertNotIn("error", result)
        self.assertEqual(list(result["rows"][0]["values"].values()), [0.0])
        records = provider.records(source, {"item_id": item.id, "domain": [("team", "=", "East")], "limit": 1,
                                           "fields": [{"name": "amount", "type": "float"}]})
        self.assertEqual(records["rows"][0]["cells"][0]["value"], 20.0)
        spec["domain"] = [("missing", "=", 1)]
        self.assertTrue(provider.aggregate(source, spec).get("error"))

    def test_drilled_remote_payload_preserves_freshness(self):
        source = self._source()
        self._refresh(source, remote.table(["Team", "Name", "Amount"], [["West", "First", 10], ["East", "Second", 20]]))
        item = self.board._create_item_from_builder({"source_id": source.id, "item_type": "bar", "title": "Amount",
            "dimension": "team", "measures": [{"field": "amount", "verb": "sum", "label": "Amount"}]})
        field = self.env["ir.model.fields"]._get("res.partner", "name")
        item.drill_ids = [(0, 0, {"field_id": field.id})]
        normal = item.get_payload({})
        drilled = item.get_drilled_payload([{"field": "team", "value": "East"}], {})
        self.assertFalse(drilled.get("error"))
        self.assertEqual(drilled["drill_depth"], 1)
        self.assertEqual(drilled["source_status"], normal["source_status"])
        self.assertTrue(drilled["source_status"]["last_success"])

    def test_requires_explicit_dashboard_audience(self):
        with self.assertRaises(ValidationError):
            self.Source.create({"name": "Unsafe", "provider_type": "rest", "remote_url": "https://example.com/data"})
