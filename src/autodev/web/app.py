from __future__ import annotations

import asyncio
import ipaddress
import json
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse

from autodev.config import AutoDevConfig
from autodev.web.models import StartRun
from autodev.web.service import RunService


def create_app(repositories=None, config=None, factory=None, port=8000):
    """Only explicitly registered repositories are accessible; no browser path API."""
    service = RunService(repositories or [Path.cwd()], config or AutoDevConfig(), factory)
    session, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    origins = {
        f"http://{host}:{number}"
        for host in ("localhost", "127.0.0.1", "[::1]")
        for number in (port, 5173)
    }

    @asynccontextmanager
    async def lifespan(app):
        await service.initialize()
        yield
        await service.shutdown()

    app = FastAPI(
        title="AutoDev local dashboard",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.service = service

    @app.middleware("http")
    async def local_security(request: Request, call_next):
        try:
            local = request.client and ipaddress.ip_address(request.client.host).is_loopback
        except ValueError:
            local = False
        host = request.url.hostname
        origin = request.headers.get("origin")
        if (
            not local
            or host not in {"127.0.0.1", "localhost", "::1"}
            or (origin and origin not in origins)
            or request.headers.get("sec-fetch-site") == "cross-site"
        ):
            return JSONResponse({"detail": "Local dashboard access only"}, status_code=403)
        bootstrap = request.url.path in {"/api/session", "/api/health"}
        if not bootstrap and not secrets.compare_digest(
            request.cookies.get("autodev_session", "").encode(), session.encode()
        ):
            return JSONResponse({"detail": "Open a dashboard session first"}, status_code=401)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if not secrets.compare_digest(
                request.headers.get("x-autodev-csrf", "").encode(), csrf.encode()
            ):
                return JSONResponse({"detail": "Invalid dashboard request token"}, status_code=403)
            length = request.headers.get("content-length", "")
            if not length.isdigit() or int(length) > 40_000:
                return JSONResponse(
                    {"detail": "Request body too large or missing length"}, status_code=413
                )
            if "application/json" not in request.headers.get("content-type", ""):
                return JSONResponse({"detail": "JSON input required"}, status_code=415)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request, error):
        return JSONResponse(
            {"detail": [{"loc": item["loc"], "msg": item["msg"]} for item in error.errors()]},
            status_code=422,
        )

    def record(key):
        if key not in service.records:
            raise HTTPException(404, "Unknown run")
        return service.records[key]

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "version": "0.3.0"}

    @app.get("/api/session")
    async def bootstrap():
        response = JSONResponse({"csrf": csrf})
        response.set_cookie("autodev_session", session, httponly=True, samesite="strict")
        return response

    @app.get("/api/projects")
    async def projects():
        return await service.projects()

    @app.get("/api/settings")
    async def settings():
        return {
            "provider": "codex_cli",
            "authentication": "Existing ChatGPT login",
            "sandbox": "Docker: no network, non-root, read-only, resource limited",
            "max_concurrency": 2,
            "max_corrections": 3,
            "max_tasks": 8,
            "docker_image": service.config.sandbox.docker_image,
            "merging": "No merge or push endpoint; integration branches are retained",
            "cancellation": "Waits for bounded sandbox cleanup before stopping",
        }

    @app.get("/api/runs")
    async def runs():
        return [
            {key: value for key, value in item.items() if key not in {"report", "events"}}
            for item in sorted(
                service.records.values(), key=lambda item: item["started_at"], reverse=True
            )[:200]
        ]

    @app.post("/api/runs", status_code=202)
    async def start(request: StartRun):
        try:
            return await service.start(request)
        except KeyError:
            raise HTTPException(404, "Unknown registered repository") from None
        except RuntimeError as error:
            raise HTTPException(409, str(error)) from None
        except (OSError, ValueError):
            raise HTTPException(400, "Repository or workflow storage unavailable") from None

    @app.get("/api/runs/{key}")
    async def detail(key: str):
        return record(key)

    @app.post("/api/runs/{key}/cancel")
    async def cancel(key: str):
        record(key)
        return await service.cancel(key)

    @app.get("/api/runs/{key}/report")
    async def report(key: str):
        value = record(key)
        if value.get("report") is None:
            raise HTTPException(409, "Report not available yet")
        return JSONResponse(
            value["report"],
            headers={
                "Content-Disposition": f'attachment; filename="autodev-{value["run_id"]}.json"'
            },
        )

    @app.get("/api/runs/{key}/files")
    async def files(key: str):
        record(key)
        return service.files(key)

    @app.get("/api/runs/{key}/files/{identifier}", response_class=PlainTextResponse)
    async def file(key: str, identifier: str):
        record(key)
        try:
            return service.read_file(key, identifier)
        except (KeyError, ValueError, OSError, UnicodeError):
            raise HTTPException(404, "Generated file unavailable") from None

    @app.get("/api/events")
    async def events(request: Request):
        async def stream():
            revision = -1
            while not await request.is_disconnected():
                if revision != service.revision:
                    revision = service.revision
                    yield f"data: {json.dumps({'revision': revision})}\n\n"
                else:
                    yield ": keepalive\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(
            stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"}
        )

    return app
