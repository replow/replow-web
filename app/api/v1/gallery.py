from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.services.gallery import GalleryService

router = APIRouter(prefix="/public", tags=["gallery"])


@router.get("/albums")
def albums(db: Session = Depends(get_db)):
    return {"items": GalleryService(db).albums(public=True)}


@router.get("/albums/{album_id}")
def album(album_id: int, db: Session = Depends(get_db)):
    return {"data": GalleryService(db).album(album_id, public=True)}
