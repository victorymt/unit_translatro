"""Small dependency-free HTTP adapter for the conversion domain.

For production deployments the same handlers can be moved behind FastAPI, but
this module makes the first web integration usable with only the Python stdlib.
"""

from __future__ import annotations

import json
import mimetypes
import os
import sysconfig
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from converter_core import (
    ConversionValidationError,
    calculate_conversion,
)
from converter_io import request_from_mapping, result_to_dict
from app_config import Settings, load_settings
from pricing_catalog import PricingCatalog, load_pricing_catalog


MAX_BODY_BYTES = 256 * 1024
API_SCHEMA_VERSION = "1"

def _static_root() -> Path:
    local_root = Path(__file__).with_name("web")
    if local_root.is_dir():
        return local_root
    data_root = Path(sysconfig.get_path("data") or sysconfig.get_config_var("prefix"))
    return data_root / "web"


STATIC_ROOT = _static_root()

REQUEST_FIELDS = frozenset(
    {
        "mode",
        "value",
        "multiplier",
        "fen",
        "token_cost",
        "balance_per_yuan",
        "ratio",
        "usage",
        "chatgpt_profile",
        "prices",
        "usd_cny_rate",
        "exchange_rate",
        "comparison_profiles",
        "profiles",
    }
)


def _json_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class ConversionHandler(BaseHTTPRequestHandler):
    server_version = "unit-translator/1.0"
    allowed_origins: frozenset[str] = frozenset()
    pricing_catalog: PricingCatalog = load_pricing_catalog()
    settings: Settings = Settings()

    @property
    def request_path(self) -> str:
        return urlsplit(self.path).path

    def _cors_origin(self) -> str | None:
        origin = self.headers.get("Origin")
        if origin and origin in self.allowed_origins:
            return origin
        return None

    def _with_schema(self, payload: object) -> object:
        if isinstance(payload, dict):
            return {"schema_version": API_SCHEMA_VERSION, **payload}
        return payload

    def _send_json(self, status: int, payload: object) -> None:
        body = _json_bytes(self._with_schema(payload))
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        cors_origin = self._cors_origin()
        if cors_origin:
            self.send_header("Access-Control-Allow-Origin", cors_origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        cors_origin = self._cors_origin()
        if cors_origin:
            self.send_header("Access-Control-Allow-Origin", cors_origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self, path: str) -> bool:
        if path == "/":
            relative = Path("index.html")
            root = STATIC_ROOT
        elif path.startswith("/assets/"):
            relative = Path(unquote(path.removeprefix("/assets/")))
            root = STATIC_ROOT / "assets"
        else:
            return False
        if relative.is_absolute() or ".." in relative.parts:
            self._send_json(404, {"error": {"code": "not_found", "message": "资源不存在"}})
            return True
        target = (root / relative).resolve()
        try:
            target.relative_to(root.resolve())
        except ValueError:
            self._send_json(404, {"error": {"code": "not_found", "message": "资源不存在"}})
            return True
        if not target.is_file():
            self._send_json(404, {"error": {"code": "not_found", "message": "资源不存在"}})
            return True
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}:
            content_type = f"{content_type}; charset=utf-8"
        self._send_bytes(200, target.read_bytes(), content_type)
        return True

    def do_OPTIONS(self) -> None:  # noqa: N802
        if self._cors_origin() is None and self.headers.get("Origin"):
            self._send_json(403, {"error": {"code": "cors_forbidden", "message": "跨域来源未被允许"}})
            return
        self.send_response(204)
        cors_origin = self._cors_origin()
        if cors_origin:
            self.send_header("Access-Control-Allow-Origin", cors_origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = self.request_path
        if path in {"/health", "/api/v1/health"}:
            self._send_json(200, {"status": "ok", "service": "unit-translator"})
            return
        if path in {"/api/v1/profiles", "/v1/profiles"}:
            query = urlsplit(self.path).query
            as_of = next(
                (item.split("=", 1)[1] for item in query.split("&") if item.startswith("as_of=")),
                None,
            )
            catalog = self.pricing_catalog.to_dict(as_of=unquote(as_of) if as_of else None)
            self._send_json(200, {"catalog_version": catalog["version"], "profiles": catalog["profiles"]})
            return
        if self._serve_static(path):
            return
        self._send_json(404, {"error": {"code": "not_found", "message": "资源不存在"}})

    def do_POST(self) -> None:  # noqa: N802
        path = self.request_path
        if path not in {"/api/v1/convert", "/v1/convert", "/api/v1/compare", "/v1/compare"}:
            self._send_json(404, {"error": {"code": "not_found", "message": "资源不存在"}})
            return
        if self.headers.get("Content-Length") is None:
            self._send_json(400, {"error": {"code": "missing_content_length", "message": "请求体缺少 Content-Length"}})
            return
        try:
            length = int(self.headers["Content-Length"])
        except ValueError:
            self._send_json(400, {"error": {"code": "invalid_content_length", "message": "Content-Length 无效"}})
            return
        if length < 0:
            self._send_json(400, {"error": {"code": "invalid_content_length", "message": "Content-Length 不能为负数"}})
            return
        if length > MAX_BODY_BYTES:
            self._send_json(413, {"error": {"code": "body_too_large", "message": "请求体过大"}})
            return
        try:
            raw_body = self.rfile.read(length)
            if len(raw_body) != length:
                raise ValueError("请求体长度与 Content-Length 不一致")
            payload = json.loads(raw_body)
            if not isinstance(payload, dict):
                raise ValueError("请求体必须是 JSON 对象")
            unknown = sorted(set(payload) - REQUEST_FIELDS)
            if unknown:
                raise ConversionValidationError(
                    unknown[0], "unknown_field", f"不支持的字段: {unknown[0]}"
                )
            if "value" not in payload and not any(
                name in payload for name in ("multiplier", "fen", "token_cost")
            ):
                raise ConversionValidationError("value", "missing_field", "缺少 value")
            if "usage" in payload and payload["usage"] == {}:
                raise ConversionValidationError("usage", "empty_usage", "usage 不能为空")
            request_payload = self.settings.apply_defaults(payload)
            result = calculate_conversion(request_from_mapping(request_payload))
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


def _configured_origins() -> frozenset[str]:
    raw = os.environ.get("UNIT_TRANSLATOR_CORS_ORIGINS", "")
    return frozenset(item.strip() for item in raw.split(",") if item.strip())


def create_server(
    host: str = "127.0.0.1",
    port: int = 8787,
    *,
    cors_origins: set[str] | frozenset[str] | None = None,
    settings: Settings | None = None,
    settings_path: str | Path | None = None,
    pricing_catalog: PricingCatalog | None = None,
    pricing_catalog_path: str | Path | None = None,
) -> ThreadingHTTPServer:
    origins = frozenset(cors_origins) if cors_origins is not None else _configured_origins()
    configured_settings = settings
    if configured_settings is None and settings_path is not None:
        configured_settings = load_settings(settings_path)
    catalog = pricing_catalog or (
        configured_settings.as_catalog()
        if configured_settings is not None
        else load_pricing_catalog(pricing_catalog_path)
    )
    configured_settings = configured_settings or Settings(
        comparison_profiles=catalog.profiles,
        version=catalog.version,
    )

    class ConfiguredConversionHandler(ConversionHandler):
        allowed_origins = origins
        pricing_catalog = catalog
        settings = configured_settings

    return ThreadingHTTPServer((host, port), ConfiguredConversionHandler)


def run_server(
    host: str = "127.0.0.1",
    port: int = 8787,
    *,
    settings: Settings | None = None,
    settings_path: str | Path | None = None,
) -> None:
    server = create_server(host, port, settings=settings, settings_path=settings_path)
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
