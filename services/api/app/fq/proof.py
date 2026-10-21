"""Time-limited HMAC proof; database password hashes never leave the server."""
import base64
import hashlib
import hmac
import json
import re

WINDOW_SECONDS = 60
GRANT_SECONDS = 900
KEY_PATTERN = re.compile(r"v1\.([a-f0-9]{32})\.([0-9]{10,12})\.([a-f0-9]{32})\.([a-f0-9]{64})")


def signing_secret(server_secret, user, grant):
    # Separate purpose and bind to the current password, username and session.
    context = ["fq-proof-secret:v1", int(user["uid"]), user["username"],
               str(user.get("password_hash") or ""), int(user.get("session_version") or 0),
               grant["id"], grant["session_id"], grant["expires_at"]]
    message = json.dumps(context, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hmac.new(server_secret.encode("utf-8"), message, hashlib.sha256).digest()


def encode_secret(secret):
    return base64.urlsafe_b64encode(secret).decode("ascii").rstrip("=")


def proof_message(uid, grant_id, timestamp, nonce):
    return f"fq-token:v1\n{int(uid)}\n{grant_id}\n{int(timestamp)}\n{nonce}".encode("utf-8")


def sign_proof(secret, uid, grant_id, timestamp, nonce):
    signature = hmac.new(secret, proof_message(uid, grant_id, timestamp, nonce), hashlib.sha256).hexdigest()
    return f"v1.{grant_id}.{int(timestamp)}.{nonce}.{signature}"
