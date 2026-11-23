"""Serve the studio behind a loopback tunnel from an HTTPS reverse proxy."""
import argparse
import re

import uvicorn
from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .app import app
from .studio import APP_REVISION


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-host", required=True, help="Public DNS name or IPv4 address")
    parser.add_argument("--port", type=int, default=8000, help="Local loopback port (default: 8000)")
    args = parser.parse_args(argv)
    host = args.public_host.lower()
    label = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    if len(host) > 253 or not re.fullmatch(rf"{label}(?:\.{label})*", host):
        parser.error("--public-host requires a single hostname without a scheme or port")

    trusted = next(m for m in app.user_middleware if m.cls is TrustedHostMiddleware)
    trusted.kwargs["allowed_hosts"] = [*trusted.kwargs["allowed_hosts"], host]

    async def public_site(scope, receive, send):
        if scope["type"] != "http":
            return await app(scope, receive, send)
        # The edge redirects HTTP to HTTPS and forwards the original Host over the tunnel.
        if Headers(scope=scope).get("host", "").lower() in (host, host + ":443"):
            scope = {**scope, "scheme": "https"}

        async def send_response(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                if APP_REVISION:
                    headers["X-BioAgent-Revision"] = APP_REVISION
                if scope["path"] in ("/", "/static/studio.js", "/static/studio.css"):
                    headers["Cache-Control"] = "no-cache"
            await send(message)

        await app(scope, receive, send_response)

    uvicorn.run(public_site, host="127.0.0.1", port=args.port, proxy_headers=False)


if __name__ == "__main__":
    main()
