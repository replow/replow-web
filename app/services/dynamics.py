import json
from datetime import datetime, timezone
from urllib.parse import urlsplit
from fastapi import HTTPException
from sqlalchemy import text

MAX_IMAGES = 9

def normalize_images(value):
    if not isinstance(value, list) or len(value) > MAX_IMAGES:
        raise HTTPException(422, "dynamic_invalid_images")
    result = []
    for item in value:
        if isinstance(item, str):
            item = {"src": item}
        if not isinstance(item, dict):
            raise HTTPException(422, "dynamic_invalid_image")
        src = str(item.get("src") or "").strip()
        alt = str(item.get("alt") or "").strip()
        try:
            url = urlsplit(src)
            valid = url.scheme in {"http", "https"} and url.hostname and not url.username and not url.password
        except ValueError:
            valid = False
        if not valid or len(src) > 2048 or len(alt) > 200 or any(c.isspace() for c in src):
            raise HTTPException(422, "dynamic_invalid_image")
        result.append({"src": src, "alt": alt})
    return result

def utc_date(value):
    if isinstance(value, datetime):
        date = value
    elif isinstance(value, str):
        try:
            date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(422, "dynamic_invalid_date")
        if not date.tzinfo:
            raise HTTPException(422, "dynamic_date_timezone_required")
    else:
        raise HTTPException(422, "dynamic_invalid_date")
    date = date.astimezone(timezone.utc) if date.tzinfo else date.replace(tzinfo=timezone.utc)
    if not 1970 <= date.year <= 9998:
        raise HTTPException(422, "dynamic_invalid_date")
    return date.replace(tzinfo=None)

def serialize(row, public=False):
    result = dict(row)
    result["images"] = json.loads(result["images"]) if isinstance(result["images"], str) else result["images"]
    result["pinned"] = bool(result["pinned"])
    result["is_published"] = bool(result["is_published"])
    result["published"] = int(result["published_at"].replace(tzinfo=timezone.utc).timestamp()*1000)
    for key in ("published_at", "created_at", "updated_at"):
        result[key] = result[key].isoformat(timespec="seconds")+"Z"
    if public:
        return {key:result[key] for key in ("id","content","images","location","pinned","published","published_at")}
    return result

class DynamicsService:
    def __init__(self, db):
        self.db = db

    def listing(self, limit=20, offset=0, search="", state="", public=False):
        conditions, values = [], {"limit":limit,"offset":offset,"now":datetime.utcnow()}
        if public:
            conditions.extend(["is_published=1","published_at<=:now"])
        elif state in ("published", "draft"):
            conditions.append("is_published=:published")
            values["published"] = state == "published"
        if search:
            conditions.append("(content LIKE :search OR location LIKE :search)")
            values["search"] = "%"+search+"%"
        where = (" WHERE "+" AND ".join(conditions)) if conditions else ""
        total = int(self.db.execute(text("SELECT COUNT(*) FROM dynamics"+where),values).scalar_one())
        rows = self.db.execute(text("SELECT * FROM dynamics"+where+
            " ORDER BY pinned DESC,published_at DESC,id DESC LIMIT :limit OFFSET :offset"), values).mappings()
        return {"items":[serialize(row,public) for row in rows],"total":total}

    def get(self, dynamic_id, public=False):
        row = self.db.execute(text("SELECT * FROM dynamics WHERE id=:id"+
            (" AND is_published=1 AND published_at<=:now" if public else "")),
            {"id":dynamic_id,"now":datetime.utcnow()}).mappings().first()
        if not row:
            raise HTTPException(404,"dynamic_not_found")
        return serialize(row,public)

    def save(self, payload, dynamic_id=None):
        data = self.get(dynamic_id) if dynamic_id else {
            "content":"","images":[],"location":"","pinned":False,"is_published":False,
            "published_at":datetime.utcnow()}
        data.update({k:v for k,v in payload.items() if k in {
            "content","images","location","pinned","is_published","published_at"}})
        content = str(data["content"] or "").strip()
        location = str(data["location"] or "").strip()
        images = normalize_images(data["images"])
        if len(content)>20000 or len(location)>160 or (not content and not images):
            raise HTTPException(422,"dynamic_invalid_content")
        if not isinstance(data["pinned"],bool) or not isinstance(data["is_published"],bool):
            raise HTTPException(422,"dynamic_invalid_status")
        values = {"id":dynamic_id,"content":content,"images":json.dumps(images,ensure_ascii=False),
            "location":location,"pinned":data["pinned"],"is_published":data["is_published"],
            "published_at":utc_date(data["published_at"]),"now":datetime.utcnow()}
        if dynamic_id:
            self.db.execute(text("UPDATE dynamics SET content=:content,images=:images,location=:location,"
                "pinned=:pinned,is_published=:is_published,published_at=:published_at,updated_at=:now WHERE id=:id"),values)
        else:
            result=self.db.execute(text("INSERT INTO dynamics "
                "(content,images,location,pinned,is_published,published_at,created_at,updated_at) "
                "VALUES (:content,:images,:location,:pinned,:is_published,:published_at,:now,:now)"),values)
            dynamic_id=int(result.lastrowid)
        self.db.commit()
        return self.get(dynamic_id)

    def delete(self, dynamic_id):
        self.get(dynamic_id)
        self.db.execute(text("DELETE FROM dynamics WHERE id=:id"),{"id":dynamic_id})
        self.db.commit()
