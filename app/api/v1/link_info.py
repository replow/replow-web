from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.services.public import PublicService
from app.services.link_info import fetch_metadata, origin_url
from urllib.parse import urlsplit

router = APIRouter()

@router.get("/v1/public/link-info")
def link_info(url: str = Query(max_length=2048), db: Session = Depends(get_db)):
    try:
        origin = origin_url(url)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid_url")
    host = urlsplit(origin).hostname.lower().rstrip(".")
    for friend in PublicService(db).friends():
        if urlsplit(friend.get("website_url") or "").hostname == host:
            return {"name": friend.get("name") or "外部网站", "icon": friend.get("avatar_url") or origin + "favicon.ico"}
    result = fetch_metadata(origin)
    return {"name": result.get("name") or "外部网站", "icon": result.get("icon") or origin + "favicon.ico"}
