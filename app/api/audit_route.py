import logging
import json
from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool
from app.db.session import SessionLocal
from app.core.request_context import request_context
from app.repositories.audit import AuditRepository, payload_fields
from app.core.audit_details import sanitize, operation, target_name

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
            elif request.headers.get("content-type", "").startswith("multipart/form-data"):
                try:
                    form = await request.form()
                    payload = {key: ({"filename": value.filename, "content_type": value.content_type,
                                      "size": value.size} if hasattr(value, "filename") else value)
                               for key, value in form.multi_items()}
                except (ValueError, UnicodeError):
                    pass
            path = request.url.path.split("/admin/", 1)[-1].split("/account/", 1)[-1]
            parts = path.split("/")
            resource = parts[0]
            target = next((p for p in parts[1:] if p.isdigit()), "")
            snapshot_name = ""
            if target:
                try:
                    with SessionLocal() as db:
                        snapshot_name = target_name(db, resource, target)
                except Exception:
                    logger.warning("Audit target snapshot unavailable")
            details = {"path": request.url.path, "method": request.method,
                       "operation": operation(request.method, resource, request.url.path),
                       "query": sanitize(dict(request.query_params)), "payload": sanitize(payload),
                       "user_agent": request.headers.get("user-agent", "")[:512]}
            status = 500
            response = None
            try:
                response = await original(request)
                status = response.status_code
                return response
            except HTTPException as error:
                status = error.status_code
                details["error"] = sanitize(error.detail)
                raise
            except RequestValidationError:
                status = 422
                details["error"] = "请求参数校验失败"
                raise
            finally:
                actor = getattr(request.state, "audit_actor", None)
                changes = getattr(request.state, "audit_changes", payload_fields(payload))
                if request.method == "POST" and status < 400 and response is not None:
                    try:
                        data = json.loads(response.body).get("data", {})
                        if isinstance(data, dict):
                            target = str(data.get("uid") or data.get("id") or target)
                    except (ValueError, AttributeError):
                        pass
                target = getattr(request.state, "audit_target", target)
                details["actor"] = actor
                details["result"] = "成功" if status < 400 else "失败"
                metadata = request_context.get()
                def record():
                    with SessionLocal() as db:
                        AuditRepository(db).record(actor, request.method, parts[0], target,
                                                   changes, status, metadata.get("ip", ""), details,
                                                   snapshot_name or target_name(db, resource, target))
                # Never mask an already-completed content write with a log-storage error.
                try:
                    await run_in_threadpool(record)
                except Exception:
                    logger.exception("Admin audit persistence failed")
        return handler
