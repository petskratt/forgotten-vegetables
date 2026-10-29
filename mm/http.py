from __future__ import annotations

import http.client
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from mm.errors import Halt

DEFAULT_USER_AGENT = "forgotten-vegetables/0.1"


def api_url(host: str, path: str, query: dict | None = None) -> str:
    base = host.strip().rstrip("/") + "/api/v4"
    if not path.startswith("/"):
        path = "/" + path
    url = base + path
    if query:
        pairs = []
        for key, value in query.items():
            if value is None:
                continue
            pairs.append((key, value))
        if pairs:
            url += "?" + urllib.parse.urlencode(pairs)
    return url


def proxy_url(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if "://" not in text:
        return "http://" + text
    return text


def ssl_mode(value: str | None) -> tuple[str, str | None]:
    if value is None or value.strip() == "":
        return ("default", None)
    text = value.strip()
    if text.lower() in ("1", "true", "yes"):
        return ("default", None)
    if text.lower() in ("0", "false", "no"):
        return ("unverified", None)
    return ("cafile", text)


def rate_limit_exhausted(header_value: str | None) -> bool:
    if header_value is None or str(header_value).strip() == "":
        return False
    try:
        return int(str(header_value).strip()) <= 0
    except ValueError:
        return False


def http_failure(status: int) -> str | None:
    if 200 <= status < 300:
        return None
    if status == 429:
        return "HTTP 429, rate limited"
    if status in (401, 403):
        return f"HTTP {status}, auth rejected"
    return f"HTTP {status}"


def build_headers(token: str, csrf: str, user_agent: str) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "X-Requested-With": "XMLHttpRequest",
        "User-Agent": user_agent or DEFAULT_USER_AGENT,
        "Cookie": f"MMAUTHTOKEN={token}",
    }
    if csrf:
        headers["X-CSRF-Token"] = csrf
    return headers


def build_ssl_context(mode: tuple[str, str | None]) -> ssl.SSLContext:
    kind, extra = mode
    if kind == "unverified":
        context = ssl._create_unverified_context()
    elif kind == "cafile":
        context = ssl.create_default_context(cafile=extra)
    else:
        context = ssl.create_default_context()
    # Prefer a real HTTP/1.1 connection. urllib cannot read h2 frames.
    context.set_alpn_protocols(["http/1.1"])
    return context


class _HTTP1Response(http.client.HTTPResponse):
    """Accept a textual ``HTTP/2`` status line.

    urllib only allows ``HTTP/1.x``. Some file servers still write
    ``HTTP/2 200`` while keeping HTTP/1.1 framing (headers, then body).
    A real HTTP/2 session is binary and never produces that status line.
    """

    def _read_status(self):
        version, status, reason = super()._read_status()
        if version in ("HTTP/2", "HTTP/2.0"):
            version = "HTTP/1.1"
        return version, status, reason


class _HTTP1Connection(http.client.HTTPConnection):
    response_class = _HTTP1Response


class _HTTPS1Connection(http.client.HTTPSConnection):
    response_class = _HTTP1Response


class _HTTP1Handler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_HTTP1Connection, req)


class _HTTPS1Handler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_HTTPS1Connection, req, context=self._context)


def build_opener(proxy: str | None, context: ssl.SSLContext) -> urllib.request.OpenerDirector:
    handlers: list = [_HTTP1Handler(), _HTTPS1Handler(context=context)]
    resolved = proxy_url(proxy)
    if resolved:
        handlers.append(urllib.request.ProxyHandler({"http": resolved, "https": resolved}))
    return urllib.request.build_opener(*handlers)


class Client:
    """One request at a time. A bad status or an empty rate window stops the run.

    A response that reports zero remaining calls is still returned. The next
    request raises Halt before it is sent, so the caller can checkpoint the
    data it already has.
    """

    def __init__(self, settings, delay_seconds: float, opener=None):
        self.host = settings.host
        self.delay = max(0.0, float(delay_seconds))
        self.headers = build_headers(settings.token, settings.csrf, settings.user_agent)
        self.expected_user_id = settings.user_id
        self.halted = False
        self._remaining = None
        if opener is not None:
            self.opener = opener
        else:
            context = build_ssl_context(ssl_mode(settings.ssl_verify))
            self.opener = build_opener(settings.proxy, context)

    def get_json(self, path: str, query: dict | None = None):
        response = self._open("GET", path, query=query, timeout=60)
        try:
            payload = response.read()
        finally:
            response.close()
            self._finish()
        try:
            return json.loads(payload.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise Halt(f"Expected JSON from GET {path}") from exc

    def post_json(self, path: str, body):
        response = self._open("POST", path, body=body, timeout=60)
        try:
            payload = response.read()
        finally:
            response.close()
            self._finish()
        try:
            return json.loads(payload.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise Halt(f"Expected JSON from POST {path}") from exc

    def download(self, path: str, dest: Path) -> None:
        response = self._open("GET", path, timeout=300)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        try:
            with tmp.open("wb") as handle:
                while True:
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
            tmp.replace(dest)
        except Exception:
            if tmp.exists():
                tmp.unlink()
            raise
        finally:
            response.close()
            self._finish()

    def _open(self, method: str, path: str, query=None, body=None, timeout: int = 60):
        if self.halted:
            raise Halt("Rate limit window is exhausted. Run the same command to continue.")
        url = api_url(self.host, path, query)
        data = None
        headers = dict(self.headers)
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            response = self.opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            snippet = exc.read()[:300].decode("utf-8", errors="replace").strip().replace("\n", " ")
            reason = http_failure(exc.code) or f"HTTP {exc.code}"
            detail = f"{reason} for {method} {path}"
            if snippet:
                detail += f": {snippet}"
            raise Halt(detail) from exc
        except urllib.error.URLError as exc:
            raise Halt(f"Network error for {method} {path}: {exc.reason}") from exc
        except http.client.UnknownProtocol as exc:
            raise Halt(
                f"Server replied {exc} for {method} {path}. "
                "Run the same command to continue."
            ) from exc
        except http.client.HTTPException as exc:
            raise Halt(f"Network error for {method} {path}: {exc}") from exc
        except TimeoutError as exc:
            raise Halt(f"Timed out for {method} {path}") from exc
        except OSError as exc:
            raise Halt(f"Network error for {method} {path}: {exc}") from exc

        status = getattr(response, "status", None) or response.getcode()
        self._remaining = response.headers.get("X-Ratelimit-Remaining")
        failure = http_failure(status)
        if failure:
            response.close()
            raise Halt(f"{failure} for {method} {path}")
        return response

    def _finish(self) -> None:
        if rate_limit_exhausted(self._remaining):
            self.halted = True
        if self.delay:
            time.sleep(self.delay)
