"""Request metadata used only while issuing a first-party login session."""
from contextvars import ContextVar

request_context: ContextVar[dict] = ContextVar("replow_request", default={})
