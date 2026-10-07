"""Bounded HTTPS/JSON ingestion. No Odoo imports, redirects, proxies or code eval."""
import http.client
import ipaddress
import json
import math
import re
import socket
import ssl
import time
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from . import tabular

MAX_BYTES = 8 * 1024 * 1024
MAX_ROWS = 10000
MAX_COLS = 60
MAX_PAGES = 10
MAX_SECONDS = 45
TOKEN_URL = "https://oauth2.googleapis.com/token"
SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"


def filter_rows(rows, domain, columns):
    """Compatibility seam shared with uploaded table filters."""
    try:
        return tabular.filter_records(rows, domain, columns)
    except tabular.TabularError:
        raise RemoteError("filter") from None


class RemoteError(Exception):
    """Only stable codes may cross into logs or user-visible diagnostics."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def destination(url, resolve=True):
    """Validate all DNS answers; return pinned addresses to prevent rebinding."""
    try:
        p = urlsplit(url)
        host = (p.hostname or "").encode("idna").decode("ascii").lower()
        if (not isinstance(url, str) or len(url) > 2048 or any(ord(c) < 33 for c in url)
                or p.scheme != "https" or not host or p.username or p.password
                or p.fragment or p.port not in (None, 443) or "\\" in url):
            raise ValueError()
        if not re.fullmatch(r"[a-z0-9.:-]+", host):
            raise ValueError()
        forbidden = {"token", "access_token", "api_key", "apikey", "key", "secret", "password", "authorization"}
        if any(k.lower() in forbidden for k, _v in parse_qsl(p.query)):
            raise ValueError()
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            literal = None
        if literal and not literal.is_global:
            raise ValueError()
        if not literal and ("." not in host or host.endswith((".localhost", ".local", ".internal", ".test", ".invalid"))):
            raise ValueError()
        addresses = []
        if resolve:
            for family, _kind, _proto, _canon, sockaddr in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM):
                ip = ipaddress.ip_address(sockaddr[0])
                mapped = getattr(ip, "ipv4_mapped", None)
                if not ip.is_global or (mapped and not mapped.is_global):
                    raise ValueError()
                if (family, str(ip)) not in addresses:
                    addresses.append((family, str(ip)))
            if not addresses:
                raise ValueError()
        return host, (p.path or "/") + (("?" + p.query) if p.query else ""), addresses
    except (ValueError, TypeError, UnicodeError, AttributeError, OSError):
        raise RemoteError("unsafe_url") from None


def request_bytes(url, headers=None, method="GET", body=None, deadline=None):
    """TLS uses original hostname, socket uses validated literal IP. No redirects."""
    deadline = deadline or (time.monotonic() + MAX_SECONDS)
    if time.monotonic() >= deadline:
        raise RemoteError("timeout")
    host, path, addresses = destination(url)
    if method != "GET" and not (method == "POST" and url == TOKEN_URL):
        raise RemoteError("unsafe_url")
    family, address = addresses[0]
    timeout = max(0.1, min(8, deadline - time.monotonic()))
    conn = http.client.HTTPSConnection(host, timeout=timeout, context=ssl.create_default_context())
    raw_socket = None
    try:
        # Bypass a second DNS lookup, HTTP_PROXY and HTTPS_PROXY entirely.
        raw_socket = socket.socket(family, socket.SOCK_STREAM)
        raw_socket.settimeout(timeout)
        raw_socket.connect((address, 443))
        conn.sock = ssl.create_default_context().wrap_socket(raw_socket, server_hostname=host)
        raw_socket = None
        request_headers = {"Accept": "application/json", "Accept-Encoding": "identity"}
        request_headers.update(headers or {})
        conn.request(method, path, body=body, headers=request_headers)
        response = conn.getresponse()
        if 300 <= response.status < 400:
            raise RemoteError("redirect")
        if response.status in (401, 403):
            raise RemoteError("authentication")
        if response.status == 429 or response.status >= 500:
            raise RemoteError("temporary")
        if not 200 <= response.status < 300:
            raise RemoteError("http_error")
        if response.getheader("Content-Encoding", "identity").lower() not in ("", "identity"):
            raise RemoteError("size")
        length = response.getheader("Content-Length")
        if length and (not length.isdigit() or int(length) > MAX_BYTES):
            raise RemoteError("size")
        data = bytearray()
        while True:
            if time.monotonic() >= deadline:
                raise RemoteError("timeout")
            # read1 returns after one underlying read; read(n) could block
            # indefinitely when a server trickles bytes below the socket timeout.
            chunk = response.read1(min(65536, MAX_BYTES + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > MAX_BYTES:
                raise RemoteError("size")
        return bytes(data)
    except RemoteError:
        raise
    except (OSError, ssl.SSLError, http.client.HTTPException, ValueError):
        raise RemoteError("connection") from None
    finally:
        conn.close()
        if raw_socket is not None:
            raw_socket.close()


def parse_json(raw):
    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError()
        return number
    try:
        return json.loads(raw.decode("utf-8"), parse_float=finite_float,
                          parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError, RecursionError):
        raise RemoteError("json") from None


def pointer(value, path):
    """RFC 6901 JSON pointer: explicit path, no recursive query language."""
    if not path:
        return value
    if not isinstance(path, str) or not path.startswith("/") or len(path) > 512 or path.count("/") > 12:
        raise RemoteError("path")
    try:
        for key in path[1:].split("/"):
            key = key.replace("~1", "/").replace("~0", "~")
            value = value[int(key)] if isinstance(value, list) else value[key]
        return value
    except (TypeError, ValueError, KeyError, IndexError):
        raise RemoteError("path") from None


def _cell(value):
    if isinstance(value, (dict, list)):
        raise RemoteError("schema")
    text = "" if value is None else str(value)
    if len(text) > 32768:
        raise RemoteError("size")
    return text


def table(headers, rows):
    if not headers or len(headers) > MAX_COLS or len(rows) > MAX_ROWS:
        raise RemoteError("size")
    if any(not isinstance(h, str) or not h.strip() or len(h) > 255 for h in headers):
        raise RemoteError("schema")
    # Reject ambiguous headers rather than silently changing key identities.
    base_slugs = [tabular._slug(h, set()) for h in headers]
    if len(set(base_slugs)) != len(base_slugs):
        raise RemoteError("schema")
    if any(len(row) > len(headers) for row in rows):
        raise RemoteError("schema")
    raw = [[_cell(c) for c in row] for row in rows]
    parsed = tabular._finish(headers, raw)
    # Inference samples 200 cells. Reject later incompatible data, never silently null it.
    for row in raw:
        for i, column in enumerate(parsed["columns"]):
            value = row[i] if i < len(row) else ""
            if value.strip() and tabular._coerce(value, column["dtype"], column.get("date_format")) is None:
                raise RemoteError("schema")
    return parsed


def fetch_rest(config, headers=None):
    deadline = time.monotonic() + MAX_SECONDS
    url = config["url"]
    page_size = int(config.get("page_size") or 500)
    pages = int(config.get("max_pages") or 5)
    paginated = config.get("pagination") == "page"
    if not 1 <= page_size <= 1000 or not 1 <= pages <= MAX_PAGES:
        raise RemoteError("size")
    rows, byte_count = [], 0
    for page in range(1, (pages if paginated else 1) + 1):
        target = url
        if paginated:
            parts = urlsplit(url)
            query = dict(parse_qsl(parts.query, keep_blank_values=True))
            for name in (config.get("page_param") or "page", config.get("size_param") or "limit"):
                if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,39}", name):
                    raise RemoteError("path")
            query[config.get("page_param") or "page"] = str(page)
            query[config.get("size_param") or "limit"] = str(page_size)
            target = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))
        raw = request_bytes(target, headers, deadline=deadline)
        byte_count += len(raw)
        if byte_count > MAX_BYTES:
            raise RemoteError("size")
        batch = pointer(parse_json(raw), config.get("path") or "")
        if not isinstance(batch, list) or any(not isinstance(row, dict) for row in batch):
            raise RemoteError("schema")
        rows.extend(batch)
        if len(rows) > MAX_ROWS:
            raise RemoteError("size")
        if not paginated or len(batch) < page_size:
            break
        if page == pages:
            raise RemoteError("page_limit")
    if not rows:
        return {"columns": [], "rows": [], "row_count": 0, "truncated": False}
    keys = sorted(set().union(*(r.keys() for r in rows)))
    return table(keys, [[row.get(key) for key in keys] for row in rows])


def fetch_sheets(sheet_id, sheet_range, headers):
    if not re.fullmatch(r"[A-Za-z0-9_-]{10,200}", sheet_id or ""):
        raise RemoteError("sheet_range")
    # Require finite A1 bounds, including header. Never request an entire sheet.
    match = re.fullmatch(r"(?:'[^']{1,100}'|[^'!:]{1,100})!([A-Z]{1,3})([1-9][0-9]*):([A-Z]{1,3})([1-9][0-9]*)", sheet_range or "")
    if not match:
        raise RemoteError("sheet_range")
    def col(s):
        n = 0
        for char in s:
            n = n * 26 + ord(char) - 64
        return n
    if not (0 <= int(match[4]) - int(match[2]) <= MAX_ROWS
            and 0 <= col(match[3]) - col(match[1]) < MAX_COLS):
        raise RemoteError("sheet_range")
    url = "https://sheets.googleapis.com/v4/spreadsheets/%s/values/%s?majorDimension=ROWS&valueRenderOption=UNFORMATTED_VALUE&dateTimeRenderOption=FORMATTED_STRING" % (sheet_id, quote(sheet_range, safe=""))
    result = parse_json(request_bytes(url, headers))
    values = result.get("values", []) if isinstance(result, dict) else []
    if not values or any(not isinstance(row, list) for row in values):
        raise RemoteError("schema")
    return table(values[0], values[1:])


def service_account_token(secret):
    """google-auth signs and refreshes tokens; bounded transport contacts Google only."""
    try:
        from google.oauth2 import service_account
    except ImportError:
        raise RemoteError("google_auth_missing") from None
    try:
        if not isinstance(secret, str) or len(secret) > 20000:
            raise ValueError()
        info = json.loads(secret)
        if (not isinstance(info, dict) or info.get("type") != "service_account"
                or not info.get("client_email") or len(secret) > 20000):
            raise ValueError()
        info["token_uri"] = TOKEN_URL
        credentials = service_account.Credentials.from_service_account_info(info, scopes=[SHEETS_SCOPE])
        class Response:
            status = 200
            headers = {"content-type": "application/json"}
            def __init__(self, data):
                self.data = data
        def request(url, method="GET", body=None, headers=None, **_kwargs):
            if url != TOKEN_URL or method != "POST":
                raise RemoteError("authentication")
            return Response(request_bytes(url, headers, method, body))
        credentials.refresh(request)
        if not credentials.token:
            raise ValueError()
        return credentials.token
    except RemoteError:
        raise
    except Exception:
        # Never echo JWTs, private keys, provider bodies, or library exception text.
        raise RemoteError("authentication") from None
