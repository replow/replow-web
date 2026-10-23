"""Article snapshots and private autosaves. Autosave never changes live content."""
import hashlib
import json
import re
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import text

FIELDS = ('title', 'slug', 'excerpt', 'body_markdown', 'cover_url', 'icon_url',
          'category', 'tags', 'status', 'is_pinned', 'published_at')


def snapshot(article):
    result = {key: article.get(key) for key in FIELDS}
    result['is_pinned'] = bool(result['is_pinned'])
    if isinstance(result['tags'], str):
        try:
            result['tags'] = json.loads(result['tags'])
        except ValueError:
            result['tags'] = []
    value = result['published_at']
    if hasattr(value, 'isoformat'):
        result['published_at'] = value.isoformat()
    return result


def fingerprint(article):
    # Publication dates are DB-generated and article_row supplies a display fallback.
    data = {k: v for k, v in snapshot(article).items() if k != 'published_at'}
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def record_version(db, article_id, article, actor_id, reason='save'):
    """Participates in the caller's article transaction; never commits itself."""
    digest = fingerprint(article)
    latest = db.execute(text('SELECT content_hash FROM article_versions WHERE article_id=:id '
                             'ORDER BY id DESC LIMIT 1'), {'id': article_id}).scalar()
    if latest == digest:
        return
    db.execute(text('INSERT INTO article_versions '
                    '(article_id, actor_id, reason, title, snapshot_json, content_hash, created_at) '
                    'VALUES (:id,:actor,:reason,:title,:body,:hash,:now)'), {
        'id': article_id, 'actor': actor_id, 'reason': reason,
        'title': article.get('title') or '', 'hash': digest,
        'body': json.dumps(snapshot(article), ensure_ascii=False), 'now': datetime.utcnow(),
    })
    stale = db.execute(text('SELECT id FROM article_versions WHERE article_id=:id '
                            'ORDER BY id DESC LIMIT 1000 OFFSET 50'), {'id': article_id}).scalars().all()
    for version_id in stale:
        db.execute(text('DELETE FROM article_versions WHERE id=:id'), {'id': version_id})


class ArticleHistory:
    def __init__(self, db, user):
        self.db, self.uid = db, int(user['uid'])
        self.admin = user.get('role') == 'admin'

    def article(self, article_id, lock=False):
        row = self.db.execute(text('SELECT * FROM articles WHERE id=:id' +
            ('' if self.admin else ' AND owner_id=:uid') + (' FOR UPDATE' if lock else '')),
            {'id': article_id, 'uid': self.uid}).mappings().first()
        if not row:
            raise HTTPException(404, 'article_not_found')
        return dict(row)

    def versions(self, article_id):
        self.article(article_id)
        rows = self.db.execute(text('SELECT v.id,v.title,v.reason,v.actor_id,v.created_at,'
            "COALESCE(NULLIF(u.display_name,''),u.username,'') AS actor_name "
            'FROM article_versions v LEFT JOIN users u ON u.uid=v.actor_id '
            'WHERE article_id=:id ORDER BY v.id DESC LIMIT 50'), {'id': article_id}).mappings()
        return [dict(row) for row in rows]

    def version(self, article_id, version_id):
        self.article(article_id)
        row = self.db.execute(text('SELECT id,snapshot_json,created_at,reason FROM article_versions '
            'WHERE id=:vid AND article_id=:id'), {'id': article_id, 'vid': version_id}).mappings().first()
        if not row:
            raise HTTPException(404, 'article_version_not_found')
        return {**{k: row[k] for k in ('id', 'created_at', 'reason')},
                'snapshot': json.loads(row['snapshot_json'])}

    def restore(self, article_id, version_id, base_token):
        data = self.version(article_id, version_id)['snapshot']
        current = self.article(article_id, lock=True)
        if not base_token or fingerprint(current) != base_token:
            raise HTTPException(409, 'article_changed_reload')
        # Restoring an old revision does not silently republish an unpublished post.
        data['status'] = current['status']
        data['published_at'] = current['published_at']
        if not self.admin:
            data['is_pinned'] = False
        data['_base_token'] = base_token
        from app.services.admin import AdminService
        return AdminService(self.db).update_article(article_id, data, self.uid, reason='restore')

    @staticmethod
    def key(value):
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,96}', value):
            raise HTTPException(422, 'invalid_draft_key')
        return value

    def draft(self, key):
        row = self.db.execute(text('SELECT draft_key,article_id,payload_json,version,updated_at '
            'FROM article_autosaves WHERE actor_id=:uid AND draft_key=:key'),
            {'uid': self.uid, 'key': self.key(key)}).mappings().first()
        if not row:
            return None
        if row['article_id']:
            self.article(row['article_id'])
        return {k: row[k] for k in ('draft_key', 'article_id', 'version', 'updated_at')} | {
            'payload': json.loads(row['payload_json'])}

    def save_draft(self, key, payload):
        key = self.key(key)
        article_id = payload.get('article_id')
        if article_id is not None:
            if not isinstance(article_id, int) or isinstance(article_id, bool) or article_id < 1:
                raise HTTPException(422, 'invalid_article_id')
            self.article(article_id)
        body = payload.get('payload')
        version = payload.get('version', 0)
        if not isinstance(body, dict) or not isinstance(version, int) or version < 0:
            raise HTTPException(422, 'invalid_autosave')
        body = {k: v for k, v in body.items() if k in FIELDS or k in {'tagsText', '_base_token'}}
        raw = json.dumps(body, ensure_ascii=False)
        if len(raw.encode()) > 1_000_000:
            raise HTTPException(413, 'draft_too_large')
        params = {'uid': self.uid, 'key': key, 'aid': article_id, 'body': raw,
                  'version': version, 'now': datetime.utcnow()}
        if version == 0:
            count = self.db.execute(text('SELECT COUNT(*) FROM article_autosaves WHERE actor_id=:uid'),
                                    params).scalar_one()
            if count >= 50:
                raise HTTPException(409, 'too_many_drafts')
            from sqlalchemy.exc import IntegrityError
            try:
                self.db.execute(text('INSERT INTO article_autosaves '
                    '(actor_id,draft_key,article_id,payload_json,version,updated_at) '
                    'VALUES (:uid,:key,:aid,:body,1,:now)'), params)
            except IntegrityError:
                self.db.rollback()
                raise HTTPException(409, 'draft_changed_reload') from None
        else:
            result = self.db.execute(text('UPDATE article_autosaves SET payload_json=:body,'
                'article_id=:aid,version=version+1,updated_at=:now '
                'WHERE actor_id=:uid AND draft_key=:key AND version=:version'), params)
            if not result.rowcount:
                self.db.rollback()
                raise HTTPException(409, 'draft_changed_reload')
        self.db.commit()
        return self.draft(key)

    def delete_draft(self, key):
        self.db.execute(text('DELETE FROM article_autosaves WHERE actor_id=:uid AND draft_key=:key'),
                        {'uid': self.uid, 'key': self.key(key)})
        self.db.commit()
