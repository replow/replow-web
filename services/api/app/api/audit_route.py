import logging
import json
from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool
from app.db.session import SessionLocal
from app.core.request_context import request_context
from app.repositories.audit import AuditRepository, payload_fields

logger = logging.getLogger(__name__)


class AuditRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request):
            if request.method in {"GET", "HEAD", "OPTIONS"}:
                return await original(request)
            payload = {}
            if request.headers.get("content-type", "").startswith("application/json"):
                try:
                    payload = await request.json()
                except (ValueError, UnicodeError):
                    pass
            status = 500
            response = None
            try:
                response = await original(request)
                status = response.status_code
                return response
            except HTTPException as error:
                status = error.status_code
                raise
            except RequestValidationError:
                status = 422
                raise
            finally:
                actor = getattr(request.state, "audit_actor", None)
                changes = getattr(request.state, "audit_changes", payload_fields(payload))
                path = request.url.path.split("/admin/", 1)[-1]
                parts = path.split("/")
                target = next((part for part in parts[1:] if part.isdigit()), parts[-1] if len(parts)>1 else "")
                if request.method == "POST" and status < 400 and response is not None:
                    try:
                        data = json.loads(response.body).get("data", {})
                        if isinstance(data, dict):
                            target = str(data.get("uid") or data.get("id") or target)
                    except (ValueError, AttributeError):
                        pass
                target = getattr(request.state, "audit_target", target)
                metadata = request_context.get()
                def record():
                    with SessionLocal() as db:
                        AuditRepository(db).record(actor, request.method, parts[0], target,
                                                   changes, status, metadata.get("ip", ""))
                # Never mask an already-completed content write with a log-storage error.
                try:
                    await run_in_threadpool(record)
                except Exception:
                    logger.exception("Admin audit persistence failed")
        return handler
