from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.api.audit_route import AuditRoute
from app.core.security import require_admin
from app.db.session import get_db
from app.repositories.audit import AuditRepository
from app.services.gallery import GalleryService

router = APIRouter(prefix="/admin", tags=["admin tools"], route_class=AuditRoute,
                   dependencies=[Depends(require_admin)])


@router.get("/audit-logs")
def audit_logs(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
               search: str = Query("", max_length=100), outcome: str = "",
               db: Session = Depends(get_db)):
    return AuditRepository(db).list(limit, offset, search.strip(), outcome)


@router.get("/albums")
def albums(db: Session = Depends(get_db)):
    return {"items": GalleryService(db).albums()}


@router.get("/albums/{album_id}")
def album(album_id: int, db: Session = Depends(get_db)):
    return {"data": GalleryService(db).album(album_id)}


@router.post("/albums")
def create_album(payload: dict, db: Session = Depends(get_db)):
    return {"data": GalleryService(db).save(payload)}


@router.put("/albums/{album_id}")
def update_album(album_id: int, payload: dict, db: Session = Depends(get_db)):
    return {"data": GalleryService(db).save(payload, album_id)}


@router.put("/albums/{album_id}/photos")
def update_photos(album_id: int, payload: dict, db: Session = Depends(get_db)):
    return {"data": GalleryService(db).save_photos(album_id, payload.get("photos"))}


@router.delete("/albums/{album_id}")
def delete_album(album_id: int, db: Session = Depends(get_db)):
    GalleryService(db).delete(album_id)
    return {"success": True}
