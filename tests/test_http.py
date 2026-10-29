import socket
import ssl
import subprocess
import threading

from mm.env import parse_env_file, settings_from_env
from mm.http import (
    _HTTP1Response,
    api_url,
    build_opener,
    build_ssl_context,
    http_failure,
    proxy_url,
    rate_limit_exhausted,
    ssl_mode,
)


def test_api_url_keeps_a_subdirectory():
    url = api_url("https://mm.example.com/subdir/", "/users/me", {"include_deleted": "true", "skip": None})
    assert url == "https://mm.example.com/subdir/api/v4/users/me?include_deleted=true"


def test_proxy_and_tls_switches():
    assert proxy_url("127.0.0.1:8080") == "http://127.0.0.1:8080"
    assert proxy_url("http://127.0.0.1:8080") == "http://127.0.0.1:8080"
    assert proxy_url("  ") is None
    assert ssl_mode(None) == ("default", None)
    assert ssl_mode("false") == ("unverified", None)
    assert ssl_mode("/tmp/corp.pem") == ("cafile", "/tmp/corp.pem")


def test_rate_limit_and_status():
    assert rate_limit_exhausted("0") is True
    assert rate_limit_exhausted("1") is False
    assert rate_limit_exhausted(None) is False
    assert rate_limit_exhausted("soon") is False
    assert http_failure(200) is None
    assert "429" in http_failure(429)
    assert "auth" in http_failure(401)
    assert http_failure(404) == "HTTP 404"
    assert http_failure(503) == "HTTP 503"


def test_ssl_context_refuses_http2_when_the_server_offers_it(tmp_path):
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "1",
            "-nodes",
            "-subj",
            "/CN=localhost",
        ],
        check=True,
        capture_output=True,
    )
    server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.load_cert_chain(cert, key)
    server.set_alpn_protocols(["h2", "http/1.1"])
    client = build_ssl_context(("unverified", None))
    assert _negotiated_alpn(client, server) == "http/1.1"


def _negotiated_alpn(client_ctx, server_ctx) -> str | None:
    client_in, client_out = ssl.MemoryBIO(), ssl.MemoryBIO()
    server_in, server_out = ssl.MemoryBIO(), ssl.MemoryBIO()
    client = client_ctx.wrap_bio(client_in, client_out, server_hostname="localhost")
    server = server_ctx.wrap_bio(server_in, server_out, server_side=True)
    client_done = server_done = False
    for _ in range(30):
        if not client_done:
            try:
                client.do_handshake()
                client_done = True
            except ssl.SSLWantReadError:
                pass
        if not server_done:
            try:
                server.do_handshake()
                server_done = True
            except ssl.SSLWantReadError:
                pass
        if client_out.pending:
            server_in.write(client_out.read())
        if server_out.pending:
            client_in.write(server_out.read())
        if client_done and server_done:
            return client.selected_alpn_protocol()
    raise AssertionError("TLS handshake did not finish")


def test_http2_status_line_is_read_as_a_normal_body():
    left, right = socket.socketpair()
    try:
        right.sendall(
            b"HTTP/2 200 OK\r\nContent-Length: 5\r\nConnection: close\r\n\r\nhello"
        )
        right.close()
        response = _HTTP1Response(left)
        response.begin()
        assert response.status == 200
        assert response.read() == b"hello"
    finally:
        left.close()
        right.close()


def test_opener_reads_a_tls_response_labeled_http2(tmp_path):
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "1",
            "-nodes",
            "-subj",
            "/CN=localhost",
        ],
        check=True,
        capture_output=True,
    )
    server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_ctx.load_cert_chain(cert, key)
    server_ctx.set_alpn_protocols(["h2", "http/1.1"])

    listening = socket.socket()
    listening.bind(("127.0.0.1", 0))
    listening.listen(1)
    port = listening.getsockname()[1]
    ready = threading.Event()
    errors: list[BaseException] = []

    def serve():
        ready.set()
        try:
            conn, _ = listening.accept()
            tls = server_ctx.wrap_socket(conn, server_side=True)
            _recv_until(tls, b"\r\n\r\n")
            tls.sendall(
                b"HTTP/2 200 OK\r\nContent-Length: 5\r\nConnection: close\r\n\r\nhello"
            )
            tls.close()
        except BaseException as exc:
            errors.append(exc)
        finally:
            listening.close()

    thread = threading.Thread(target=serve)
    thread.start()
    ready.wait(2)
    opener = build_opener(None, build_ssl_context(("unverified", None)))
    try:
        response = opener.open(f"https://127.0.0.1:{port}/files/abc", timeout=5)
        assert response.read() == b"hello"
    finally:
        thread.join(5)
    assert errors == []


def _recv_until(sock, marker: bytes) -> bytes:
    data = b""
    while marker not in data:
        chunk = sock.recv(4096)
        if not chunk:
            break
        data += chunk
    return data


def test_env_file_ignores_comments_and_strips_quotes():
    values = parse_env_file(
        """
# comment
MMAUTHTOKEN="token"
MMHOST=https://mm.example.com/subdir/
PROXY=127.0.0.1:8080
EMPTY=
"""
    )
    assert values["MMAUTHTOKEN"] == "token"
    assert values["MMHOST"].endswith("/subdir/")
    assert "EMPTY" not in values or values["EMPTY"] == ""
    settings = settings_from_env(values)
    assert settings.token == "token"
    assert settings.proxy == "127.0.0.1:8080"
    assert settings.user_agent == "forgotten-vegetables/0.1"
