# Deployment

`unit-translator` includes a dependency-free HTTP server for local use, internal tools, and integration tests. It should not be exposed directly to the public internet. Put it behind a maintained reverse proxy that terminates TLS and owns authentication, rate limiting, request logging, and connection limits.

## Service

Create a dedicated unprivileged account and install the wheel in its own virtual environment. A minimal systemd unit is:

```ini
[Unit]
Description=Unit Translator
After=network.target

[Service]
Type=simple
User=unit-translator
Group=unit-translator
WorkingDirectory=/opt/unit-translator
ExecStart=/opt/unit-translator/.venv/bin/unit-translator --serve --config /etc/unit-translator/settings.toml --host 127.0.0.1 --port 8787
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true

[Install]
WantedBy=multi-user.target
```

Keep the process bound to `127.0.0.1`. The application returns CSP, frame, MIME sniffing, referrer, permissions, and cache-control headers, but the proxy remains responsible for transport and access policy.

## Reverse Proxy

Example Nginx location:

```nginx
limit_req_zone $binary_remote_addr zone=unit_translator:10m rate=10r/s;

server {
    listen 443 ssl http2;
    server_name calculator.example.com;

    # Configure ssl_certificate, ssl_certificate_key, and your authentication policy.

    location / {
        limit_req zone=unit_translator burst=20 nodelay;
        client_max_body_size 256k;
        proxy_connect_timeout 3s;
        proxy_read_timeout 15s;
        proxy_pass http://127.0.0.1:8787;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Do not enable CORS unless a separate browser origin must call the API. When needed, set `UNIT_TRANSLATOR_CORS_ORIGINS` to an exact comma-separated allowlist. Wildcard origins are intentionally unsupported.

## Operations

- Probe `GET /api/v1/health`; expect HTTP 200, `schema_version: "1"`, and `status: "ok"`.
- Keep `/api/v1/profiles` and the configured price version under change control.
- Back up the settings and price catalog rather than transient application state; the service itself is stateless.
- Roll back by installing the previous wheel and restarting the service.
- Treat public authentication and authorization as mandatory proxy responsibilities. The built-in server does not manage users or credentials.
