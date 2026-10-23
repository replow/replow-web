"""Authenticated content-management additions shared by admin and account."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.core.security import current_user, require_admin
from app.db.session import get_db
from app.services.article_history import ArticleHistory
from app.services.media_trash import MediaTrash
from app.api.audit_route import AuditRoute


def make_router(prefix, dependency):
    router = APIRouter(prefix=prefix, tags=['content-tools'], route_class=AuditRoute)

    @router.get('/media/{media_id}/references')
    def references(media_id: int, user=Depends(dependency), db: Session=Depends(get_db)):
        return {'data': MediaTrash(db, None if prefix == '/admin' else int(user['uid'])).references(media_id)}

    @router.post('/media/{media_id}/restore')
    def restore_media(media_id: int, user=Depends(dependency), db: Session=Depends(get_db)):
        return {'data': MediaTrash(db, None if prefix == '/admin' else int(user['uid'])).restore(media_id)}

    @router.delete('/media/{media_id}/purge')
    def purge_media(media_id: int, user=Depends(dependency), db: Session=Depends(get_db)):
        from app.services.media_storage import MediaError
        from fastapi import HTTPException
        try:
            return {'success': MediaTrash(db, None if prefix == '/admin' else int(user['uid'])).purge(media_id)}
        except MediaError as error:
            raise HTTPException(error.status_code, error.detail) from error

    @router.get('/articles/{article_id}/versions')
    def versions(article_id: int, user=Depends(dependency), db: Session=Depends(get_db)):
        return {'items': ArticleHistory(db, user if prefix == '/admin' else {**user, 'role': 'user'}).versions(article_id)}

    @router.get('/articles/{article_id}/versions/{version_id}')
    def version(article_id: int, version_id: int, user=Depends(dependency), db: Session=Depends(get_db)):
        return {'data': ArticleHistory(db, user if prefix == '/admin' else {**user, 'role': 'user'}).version(article_id, version_id)}

    @router.post('/articles/{article_id}/versions/{version_id}/restore')
    def restore_article(article_id: int, version_id: int, payload: dict,
                        user=Depends(dependency), db: Session=Depends(get_db)):
        return {'data': ArticleHistory(db, user if prefix == '/admin' else {**user, 'role': 'user'}).restore(article_id, version_id, payload.get('_base_token'))}

    @router.get('/article-drafts/{key}')
    def draft(key: str, user=Depends(dependency), db: Session=Depends(get_db)):
        return {'data': ArticleHistory(db, user if prefix == '/admin' else {**user, 'role': 'user'}).draft(key)}

    @router.put('/article-drafts/{key}')
    def save_draft(key: str, payload: dict, user=Depends(dependency), db: Session=Depends(get_db)):
        return {'data': ArticleHistory(db, user if prefix == '/admin' else {**user, 'role': 'user'}).save_draft(key, payload)}

    @router.delete('/article-drafts/{key}')
    def delete_draft(key: str, user=Depends(dependency), db: Session=Depends(get_db)):
        ArticleHistory(db, user if prefix == '/admin' else {**user, 'role': 'user'}).delete_draft(key)
        return {'success': True}

    return router


admin_router = make_router('/admin', require_admin)
account_router = make_router('/account', current_user)
