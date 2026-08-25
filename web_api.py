"""Small dependency-free HTTP adapter for the conversion domain.

For production deployments the same handlers can be moved behind FastAPI, but
this module makes the first web integration usable with only the Python stdlib.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from converter_core import (
    ConversionValidationError,
    DEEPSEEK_PRICE_PROFILES,
    calculate_conversion,
)
from converter_io import request_from_mapping, result_to_dict


MAX_BODY_BYTES = 256 * 1024


def _json_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class ConversionHandler(BaseHTTPRequestHandler):
    server_version = "unit-translator/1.0"

    def _send_json(self, status: int, payload: object) -> None:
        body = _json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if self.path in {"/health", "/api/v1/health"}:
            self._send_json(200, {"status": "ok", "service": "unit-translator"})
            return
        if self.path in {"/api/v1/profiles", "/v1/profiles"}:
            self._send_json(200, {"profiles": [profile.to_dict() for profile in DEEPSEEK_PRICE_PROFILES]})
            return
        self._send_json(404, {"error": {"code": "not_found", "message": "资源不存在"}})

    def do_POST(self) -> None:  # noqa: N802
        if self.path not in {"/api/v1/convert", "/v1/convert", "/api/v1/compare", "/v1/compare"}:
            self._send_json(404, {"error": {"code": "not_found", "message": "资源不存在"}})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(400, {"error": {"code": "invalid_content_length", "message": "Content-Length 无效"}})
            return
        if length > MAX_BODY_BYTES:
            self._send_json(413, {"error": {"code": "body_too_large", "message": "请求体过大"}})
            return
        try:
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("请求体必须是 JSON 对象")
            result = calculate_conversion(request_from_mapping(payload))
        except ConversionValidationError as exc:
            self._send_json(
                422,
                {"error": {"code": exc.code, "field": exc.field, "message": str(exc)}},
            )
            return
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            self._send_json(422, {"error": {"code": "invalid_request", "message": str(exc)}})
            return
        self._send_json(200, result_to_dict(result))

    def log_message(self, format: str, *args: Any) -> None:
        # Keep library use quiet; applications can supply their own server logger.
        return


def create_server(host: str = "127.0.0.1", port: int = 8787) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), ConversionHandler)


def run_server(host: str = "127.0.0.1", port: int = 8787) -> None:
    server = create_server(host, port)
    print(f"unit-translator web API listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="启动 unit-translator Web API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    options = parser.parse_args()
    run_server(options.host, options.port)
