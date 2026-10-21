from fastapi import HTTPException


def validate_sensitive_edit(payload, existing):
    old = existing or {}
    uid_changed = payload.get("uid") not in (None, "") and str(payload["uid"]) != str(old.get("uid", ""))
    if uid_changed and payload.get("allow_uid_override") is not True:
        raise HTTPException(422, "uid_override_confirmation_required")
    sensitive = uid_changed or bool(payload.get("password") or payload.get("generate_password") or payload.get("clear_password"))
    for key in ("role", "status"):
        if key in payload and str(payload[key]) != str(old.get(key, "user" if key == "role" else "active")):
            sensitive = True
    # Initial passwords are part of normal account creation; privileged/manual IDs still require confirmation.
    if existing is None:
        sensitive = uid_changed or payload.get("role") == "admin"
    if sensitive and payload.get("confirm_sensitive") is not True:
        raise HTTPException(422, "sensitive_confirmation_required")
