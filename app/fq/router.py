from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import re
import secrets
import time
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials
import jwt
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, SecretStr, model_validator
from sqlalchemy.orm import Session

from app.core.security import current_user
from app.db.session import get_db
from app.repositories.sessions import SessionRepository
from app.repositories.users import UserRepository

from .client import Client, UpstreamError
from .config import Config, get_config
from .operations import settings, record, ServiceDisabled
from .store import QueueFull, Store
from .proof import GRANT_SECONDS, KEY_PATTERN, WINDOW_SECONDS, encode_secret, signing_secret, sign_proof
from .artifacts import job_catalog_ids, RETENTION_SECONDS
from .covers import prepare_book_cover, prepare_search_covers
from .previews import CoverBusy, resolve_cover, search_text


router = APIRouter(prefix="/fq", tags=["fq"])
ISSUER = "https://api.example.com/fq"
AUDIENCE = "fq-relay"


class TokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    uid: int = Field(strict=True, gt=0, le=9223372036854775807)
    key: SecretStr = Field(min_length=1, max_length=256)


class DownloadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    book_id: str = Field(pattern=r"^[0-9]{1,24}$", validation_alias=AliasChoices("book_id", "uid", "novel_uid"))
    format: Literal["txt", "epub"] = Field(default="txt", validation_alias=AliasChoices("format", "suffix"))
    refresh: bool = False
    start_chapter: int = Field(default=1, ge=1, le=999999)
    end_chapter: Optional[int] = Field(default=None, ge=1, le=999999)

    @model_validator(mode='after')
    def valid_range(self):
        if self.end_chapter is not None and self.end_chapter < self.start_chapter:
            raise ValueError('end_chapter must be at least start_chapter')
        return self


def no_store(response: Response):
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["CDN-Cache-Control"] = "no-store"
    response.headers["Cloudflare-CDN-Cache-Control"] = "no-store"


def token_secret(config):
    if len(config.jwt_secret) < 32:
        raise HTTPException(status_code=503, detail="fq_not_configured")
    return config.jwt_secret


def mint_token(user, config):
    now = int(time.time())
    claims = {"iss": ISSUER, "aud": AUDIENCE, "kind": "fq", "sub": str(user["uid"]),
              "sv": int(user.get("session_version") or 0), "sid": user.get("_session_id"),
              "iat": now, "exp": now + config.token_seconds, "jti": secrets.token_hex(16), "amr": "time-hmac-v1"}
    return jwt.encode(claims, token_secret(config), algorithm="HS256"), claims


def decode_fq_token(token, config):
    try:
        claims = jwt.decode(token, token_secret(config), algorithms=["HS256"], issuer=ISSUER, audience=AUDIENCE,
                            options={"require": ["iss", "aud", "kind", "sub", "sv", "iat", "exp", "jti"]})
        if claims.get("kind") != "fq" or claims.get("amr") != "time-hmac-v1" or not str(claims.get("sub", "")).isdigit():
            raise jwt.InvalidTokenError()
        if not isinstance(claims.get("sv"), int) or not isinstance(claims.get("jti"), str):
            raise jwt.InvalidTokenError()
        return claims
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="invalid_or_expired_fq_token", headers={"WWW-Authenticate": "Bearer"}) from None


def bearer_value(request):
    headers = request.headers.getlist("authorization")
    parts = headers[0].split() if len(headers) == 1 else []
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="fq_token_required", headers={"WWW-Authenticate": "Bearer"})
    return parts[1]



@router.post("/session")
def browser_session_token(request: Request, response: Response,
                          db: Session = Depends(get_db), config: Config = Depends(get_config)):
    """One-request FQ token exchange for the first-party www.example.com browser only.

    Does not use the Java parsing gateway for identity, and keeps the public
    signing-key /token protocol intact for existing clients.
    """
    from app.core.config import get_settings
    from app.core.security import decode_token
    from app.services.auth import AuthService
    from app.api.v1.auth import _set_session_cookie, _clear_session_cookie

    host = (request.headers.get("host") or "").lower().split(":")[0]
    origin = (request.headers.get("origin") or "").rstrip("/").lower()
    if ("https://" + host) not in {value.rstrip("/").lower() for value in get_settings().cors_origin_list} or origin != "https://" + host:
        raise HTTPException(status_code=403, detail="same_origin_required")

    no_store(response)
    cookie = request.cookies.get(get_settings().session_cookie_name)
    if not cookie:
        raise HTTPException(status_code=401, detail="not_authenticated")
    try:
        user, _, rotated_refresh, _ = AuthService(db).refresh(cookie)
    except HTTPException:
        _clear_session_cookie(response, request)
        raise
    if not user:
        _clear_session_cookie(response, request)
        raise HTTPException(status_code=401, detail="account_unavailable")
    claims = decode_token(rotated_refresh, expected_kind="refresh")
    if not claims.get("sid"):
        raise HTTPException(status_code=401, detail="active_login_session_required")
    user["_session_id"] = claims["sid"]
    bearer, jwt_claims = mint_token(user, config)
    # Return initial service metadata with the authenticated FQ token.
    with Store(config).connection() as state_db:
        service = settings(state_db)
    _set_session_cookie(response, rotated_refresh, request)
    request.state.audit_actor = {"uid": user["uid"], "username": user["username"]}
    return {"success": True, "data": {
        "uid": int(user["uid"]), "username": user["username"],
        "token": bearer, "token_type": "Bearer",
        "expires_in": config.token_seconds,
        "expires_at": datetime.fromtimestamp(jwt_claims["exp"], timezone.utc).isoformat(),
        "service": {"enabled": service["enabled"], "paused": service["paused"]},
    }}


def fq_user(request: Request, db: Session = Depends(get_db), config: Config = Depends(get_config)):
    claims = decode_fq_token(bearer_value(request), config)
    user = UserRepository(db).get_by_id(int(claims["sub"]))
    if not user or user.get("status") != "active":
        raise HTTPException(status_code=401, detail="account_unavailable")
    version = int(user.get("session_version") or 0)
    if claims["sv"] != version:
        raise HTTPException(status_code=401, detail="session_revoked")
    if claims.get("sid"):
        sessions = SessionRepository(db)
        if not sessions.active(claims["sid"], int(user["uid"]), version):
            raise HTTPException(status_code=401, detail="session_revoked")
    request.state.audit_actor = {"uid": user["uid"], "username": user["username"]}
    return user


def request_ip(request):
    return (request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            or (request.client.host if request.client else ""))


@router.post("/signing-key")
def provision_signing_key(request: Request, response: Response,
                   db: Session = Depends(get_db), config: Config = Depends(get_config)):
    token_secret(config)
    no_store(response)
    access = bearer_value(request)
    user = current_user(request, HTTPAuthorizationCredentials(scheme="Bearer", credentials=access), db)
    if not user.get("_session_id"):
        raise HTTPException(status_code=401, detail="active_login_session_required")
    store = Store(config)
    if not store.rate_limit("grant-user:" + str(user["uid"]), 30, 600):
        raise HTTPException(status_code=429, detail="too_many_signing_key_requests", headers={"Retry-After": "600"})
    grant = store.create_grant(int(user["uid"]), user.get("_session_id"), int(user.get("session_version") or 0), GRANT_SECONDS)
    return {"success": True, "data": {"uid": int(user["uid"]), "grant_id": grant["id"],
        "signing_key": encode_secret(signing_secret(token_secret(config), user, grant)),
        "algorithm": "HMAC-SHA256", "server_time": int(time.time()), "window_seconds": WINDOW_SECONDS,
        "expires_in": GRANT_SECONDS, "expires_at": grant["expires_at"]}}


@router.post("/token")
def exchange_token(payload: TokenRequest, request: Request, response: Response,
                   db: Session = Depends(get_db), config: Config = Depends(get_config)):
    token_secret(config)
    no_store(response)
    store = Store(config)
    bucket = "proof-ip:" + hashlib.sha256(request_ip(request).encode()).hexdigest()
    if not store.rate_limit(bucket, 60, 600):
        raise HTTPException(status_code=429, detail="too_many_token_requests", headers={"Retry-After": "600"})
    def invalid():
        raise HTTPException(status_code=401, detail="invalid_or_expired_fq_key")
    key = payload.key.get_secret_value()
    match = KEY_PATTERN.fullmatch(key)
    if not match:
        invalid()
    grant_id, timestamp_string, nonce, _ = match.groups()
    timestamp, now = int(timestamp_string), int(time.time())
    if abs(now - timestamp) > WINDOW_SECONDS:
        invalid()
    grant = store.get_grant(grant_id, payload.uid)
    user = UserRepository(db).get_by_id(payload.uid) if grant else None
    if not user or user.get("status") != "active":
        invalid()
    version = int(user.get("session_version") or 0)
    if grant["session_version"] != version or timestamp < grant["created_at"] - WINDOW_SECONDS or timestamp >= grant["expires_at"]:
        invalid()
    if grant["session_id"] and not SessionRepository(db).active(grant["session_id"], payload.uid, version):
        invalid()
    expected = sign_proof(signing_secret(token_secret(config), user, grant), payload.uid, grant_id, timestamp, nonce)
    if not hmac.compare_digest(key, expected):
        invalid()
    if not store.consume_nonce(grant_id, nonce, timestamp + WINDOW_SECONDS + 1):
        invalid()
    # Unsigned requests and replayed proofs must not exhaust another user's quota.
    if not store.rate_limit("proof-user:" + str(payload.uid), 60, 600):
        raise HTTPException(status_code=429, detail="too_many_token_requests", headers={"Retry-After": "600"})
    user["_session_id"] = grant["session_id"]
    request.state.audit_actor = {"uid": user["uid"], "username": user["username"]}
    token, claims = mint_token(user, config)
    return {"success": True, "data": {"token": token, "token_type": "Bearer", "expires_in": config.token_seconds,
                                        "expires_at": datetime.fromtimestamp(claims["exp"], timezone.utc).isoformat(), "uid": int(user["uid"])}}


def upstream_call(config, path, params=None, fresh=False):
    try:
        return Client(config).request(path, params, fresh=fresh)
    except UpstreamError as error:
        raise HTTPException(status_code=503 if error.reason == "upstream_busy" else 502,
                            detail=error.reason, headers={"Retry-After": "30"}) from None


@router.get("")
@router.get("/")
def relay_info(response: Response, user: dict = Depends(fq_user), config: Config = Depends(get_config)):
    no_store(response)
    return {"success": True, "data": {"service": "fq-relay", "uid": user["uid"], "formats": ["txt", "epub"],
                                        "token_expires_in": config.token_seconds, "download_mode": "queued", "concurrency": 1}}


@router.get("/search")
def search(response: Response, key: str = Query(min_length=1, max_length=100), page: int = Query(default=1, ge=1),
           size: int = Query(default=10, ge=1, le=10), defer_covers: bool = Query(default=False),
           user: dict = Depends(fq_user), config: Config = Depends(get_config)):
    no_store(response)
    result=upstream_call(config, "/api/search", {"key": key, "page": page, "size": 10})
    text = search_text(config, result)
    if not defer_covers:
        # Older cached clients still receive the cover URLs they understand.
        text['data']['books'] = prepare_search_covers(config, [dict(b) for b in result['data'].get('books', [])[:10]])
    return text


@router.get('/books/{book_id}/cover')
def book_cover(book_id: str, response: Response, user: dict = Depends(fq_user), config: Config = Depends(get_config)):
    if not re.fullmatch(r'[0-9]{1,24}', book_id):
        raise HTTPException(status_code=422, detail='invalid_book_id')
    no_store(response)
    try:
        return resolve_cover(config, book_id)
    except CoverBusy:
        raise HTTPException(status_code=503, detail='cover_busy', headers={'Retry-After': '3'}) from None
    except UpstreamError as error:
        raise HTTPException(status_code=502, detail=error.reason) from None


@router.get("/books/{book_id}")
def book(book_id: str, response: Response, user: dict = Depends(fq_user), config: Config = Depends(get_config)):
    if not re.fullmatch(r"[0-9]{1,24}", book_id):
        raise HTTPException(status_code=422, detail="invalid_book_id")
    no_store(response)
    result=upstream_call(config, "/api/book/" + book_id)
    result['data']=prepare_book_cover(config,result['data'])
    return result


@router.post("")
@router.post("/")
@router.post("/download")
@router.post("/jobs")
def create_download(payload: DownloadRequest, user: dict = Depends(fq_user), config: Config = Depends(get_config)):
    store = Store(config)
    try:
        job = store.enqueue(int(user["uid"]), payload.book_id, payload.format, payload.refresh, payload.start_chapter, payload.end_chapter)
    except ServiceDisabled:
        raise HTTPException(status_code=503, detail="download_service_disabled") from None
    except QueueFull:
        raise HTTPException(status_code=429, detail="download_queue_full", headers={"Retry-After": "30"}) from None
    result = store.get(job["id"], int(user["uid"]))
    return JSONResponse(status_code=202, content={"success": True, "data": result},
                        headers={"Cache-Control": "private, no-store", "Retry-After": "3"})


@router.get("/jobs")
def list_jobs(response: Response, user: dict = Depends(fq_user), config: Config = Depends(get_config)):
    no_store(response)
    return {"success": True, "data": Store(config).list(int(user["uid"]))}


@router.get("/jobs/{job_id}")
def job_status(job_id: str, response: Response, user: dict = Depends(fq_user), config: Config = Depends(get_config)):
    no_store(response)
    row = Store(config).get(job_id, int(user["uid"]))
    if row is None:
        raise HTTPException(status_code=404, detail="job_not_found")
    return {"success": True, "data": row}


@router.get('/books/{book_id}/toc')
def chapter_directory(book_id: str, response: Response, user: dict = Depends(fq_user), config: Config = Depends(get_config)):
    if not re.fullmatch(r'[0-9]{1,24}',book_id):raise HTTPException(status_code=422,detail='invalid_book_id')
    no_store(response)
    data=upstream_call(config,'/api/toc/'+book_id)['data']
    entries=[{'id':str(x['item_id']),'title':str(x.get('title') or ''),'index':i+1} for i,x in enumerate(data.get('item_data_list',[]))]
    return {'success':True,'data':{'book_id':book_id,'total_chapters':len(entries),'chapters':entries}}


@router.get('/history')
def download_history(response: Response, page: int=Query(default=1,ge=1), size: int=Query(default=20,ge=1,le=50),
                     user: dict=Depends(fq_user), config: Config=Depends(get_config)):
    no_store(response)
    store=Store(config);data=store.history(int(user['uid']),page,size)
    legacy={x['book_id'] for x in data['items'] if not x['cover_url'].startswith(config.public_base+'/covers/')}
    for book_id in legacy:
        try:
            detail=upstream_call(config,'/api/book/'+book_id)['data'];detail=prepare_book_cover(config,detail)
            with store.connection() as db:
                db.execute('UPDATE jobs SET author=?,cover_url=? WHERE book_id=? AND user_id=?',
                    (str(detail.get('author') or ''),str(detail.get('coverUrl') or ''),book_id,int(user['uid'])))
            for item in data['items']:
                if item['book_id']==book_id:
                    item['author']=str(detail.get('author') or item['author']);item['cover_url']=str(detail.get('coverUrl') or '')
        except HTTPException:pass
    return {'success':True,'data':data}


def owned_job(store,job_id,user):
    row=store.raw_job(job_id,int(user['uid']))
    if row is None:raise HTTPException(status_code=404,detail='job_not_found')
    return row


@router.post('/jobs/{job_id}/reuse')
def reuse_download(job_id: str, response: Response, user: dict=Depends(fq_user),config: Config=Depends(get_config)):
    no_store(response);store=Store(config);row=owned_job(store,job_id,user)
    result=store.get(job_id,int(user['uid']))
    if result['file_available']:
        with store.connection() as db:record(db,'original_reused',row)
        return {'success':True,'data':result}
    try:
        job=store.enqueue(int(user['uid']),row['book_id'],row['format'],False,row['start_chapter'],row['end_chapter'],job_id)
    except ServiceDisabled:
        raise HTTPException(status_code=503, detail="download_service_disabled") from None
    except QueueFull:raise HTTPException(status_code=429,detail='download_queue_full') from None
    return JSONResponse(status_code=202,content={'success':True,'data':store.get(job['id'],int(user['uid']))},headers={'Cache-Control':'no-store'})


@router.get('/jobs/{job_id}/updates')
def check_updates(job_id: str,response: Response,user: dict=Depends(fq_user),config: Config=Depends(get_config)):
    no_store(response);store=Store(config);row=owned_job(store,job_id,user)
    data=upstream_call(config,'/api/toc/'+row['book_id'],fresh=True)['data'];entries=data.get('item_data_list',[])
    ids=[str(x['item_id']) for x in entries];old=job_catalog_ids(store,row)
    old_ids=set(old)
    added=sum(x not in old_ids for x in ids)
    with store.connection() as db:record(db,'updates_checked',row,details={'new_chapters':added,'has_updates':ids!=old})
    return {'success':True,'data':{'book_id':row['book_id'],'previous_total_chapters':len(old),
        'current_total_chapters':len(ids),'new_chapters':added,'has_updates':ids!=old,
        'latest_chapter_title':entries[-1].get('title','') if entries else ''}}


@router.post('/jobs/{job_id}/update')
def update_download(job_id: str,response: Response,user: dict=Depends(fq_user),config: Config=Depends(get_config)):
    no_store(response);store=Store(config);row=owned_job(store,job_id,user)
    try:job=store.enqueue(int(user['uid']),row['book_id'],row['format'],True,row['start_chapter'],None,job_id)
    except ServiceDisabled:
        raise HTTPException(status_code=503, detail="download_service_disabled") from None
    except QueueFull:raise HTTPException(status_code=429,detail='download_queue_full') from None
    return JSONResponse(status_code=202,content={'success':True,'data':store.get(job['id'],int(user['uid']))},headers={'Cache-Control':'no-store'})


@router.get("/settings")
def public_service_settings(response: Response, user: dict=Depends(fq_user), config: Config=Depends(get_config)):
    no_store(response)
    store=Store(config)
    with store.connection() as db:values=settings(db)
    return {"success":True,"data":{"enabled":values["enabled"],"paused":values["paused"],"retention_days":31}}
