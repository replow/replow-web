"""Recoverable media removal with references checked before every deletion."""
import html
import json
import re
from datetime import datetime
from urllib.parse import unquote

from fastapi import HTTPException
from sqlalchemy import text


def contains_url(value, url):
    """Match URLs with query/fragment suffixes, including JSON-escaped Markdown."""
    raw = html.unescape(str(value or '')).replace('\\/', '/')
    raw, url = unquote(raw), unquote(url)
    return bool(re.search(re.escape(url) + r'(?=$|[\s\"\'<>\)\]\}?#])', raw))


class MediaTrash:
    def __init__(self, db, uid=None):
        self.db, self.uid = db, uid

    def item(self, media_id, lock=False):
        row = self.db.execute(text('SELECT * FROM media_objects WHERE id=:id' +
            (' AND uploader_id=:uid' if self.uid is not None else '') +
            (' FOR UPDATE' if lock else '')), {'id': media_id, 'uid': self.uid}).mappings().first()
        if not row:
            raise HTTPException(404, 'media_not_found')
        return dict(row)

    def references(self, media_id):
        item = self.item(media_id)
        url = str(item['public_url'] or '')
        refs = []
        # Use trusted table/column constants, never identifiers supplied by a caller.
        sources = [
            ('articles', 'id', 'title', ('body_markdown', 'cover_url', 'icon_url'), '文章'),
            ('users', 'uid', 'display_name', ('avatar_url',), '用户头像'),
            ('friend_links', 'id', 'name', ('avatar_url',), '友情链接'),
            ('friend_link_applications', 'id', 'site_name', ('avatar_url',), '友链申请'),
            ('photo_albums', 'id', 'title', ('cover_url',), '相册封面'),
            ('dynamics', 'id', 'content', ('content', 'images'), '动态'),
            ('comments', 'id', 'user_name_snapshot', ('body_markdown', 'user_avatar_snapshot'), '评论'),
            ('songs', 'id', 'title', ('audio_url', 'cover_url'), '音乐'),
            ('site_settings', 'setting_key', 'setting_key', ('setting_value',), '站点设置'),
        ]
        for table, pk, title, columns, label in sources:
            # Return titles only to administrators. Account users see only reference counts/types.
            select = list(dict.fromkeys((pk, title, *columns)))
            where = ' OR '.join(f'INSTR({c}, :url)>0' for c in columns)
            # Escaped JSON URLs are checked too; fetch candidates by the URL basename when needed.
            leaf = url.rsplit('/', 1)[-1].split('?')[0]
            where += ' OR ' + ' OR '.join(f'INSTR({c}, :leaf)>0' for c in columns)
            rows = self.db.execute(text(f"SELECT {','.join(select)} FROM {table} WHERE {where}"),
                                   {'url': url, 'leaf': leaf or url}).mappings()
            for row in rows:
                if url and any(contains_url(row[c], url) for c in columns):
                    refs.append({'type': label, 'id': str(row[pk]) if self.uid is None else '',
                                 'title': str(row[title] or label)[:120] if self.uid is None else label})
        albums = self.db.execute(text('SELECT a.id,a.title FROM album_photos p '
            'JOIN photo_albums a ON a.id=p.album_id WHERE p.media_id=:id'), {'id': media_id}).mappings()
        for row in albums:
            refs.append({'type': '相册图片', 'id': str(row['id']) if self.uid is None else '',
                         'title': row['title'] if self.uid is None else '相册图片'})
        # Private versions/drafts still need the original file for faithful recovery.
        for table, pk, column, label in [('article_versions','id','snapshot_json','文章历史版本'),
                                         ('article_autosaves','draft_key','payload_json','自动保存草稿')]:
            rows = self.db.execute(text(f'SELECT {pk},{column} FROM {table} WHERE '
                f'INSTR({column},:leaf)>0'), {'leaf': url.rsplit('/', 1)[-1]}).mappings()
            for row in rows:
                if url and contains_url(row[column], url):
                    refs.append({'type': label, 'id': '', 'title': label})
        settings = self.db.execute(text('SELECT namespace,setting_key,setting_value FROM settings '
            'WHERE is_secret=0 AND INSTR(setting_value,:leaf)>0'),
            {'leaf': url.rsplit('/', 1)[-1]}).mappings()
        for row in settings:
            if url and contains_url(row['setting_value'], url):
                refs.append({'type': '站点配置', 'id': '', 'title': '站点配置'})
        return {'total': len(refs), 'items': refs[:100]}

    def list(self, limit, offset, trashed=False):
        where = 'm.deleted_at IS NOT NULL' if trashed else 'm.deleted_at IS NULL'
        if self.uid is not None:
            where += ' AND m.uploader_id=:uid'
        params = {'uid': self.uid, 'limit': limit, 'offset': offset}
        total = self.db.execute(text(f'SELECT COUNT(*) FROM media_objects m WHERE {where}'), params).scalar_one()
        rows = self.db.execute(text('SELECT m.*,COALESCE(NULLIF(u.display_name,\'\'),u.username) AS uploader_name '
            'FROM media_objects m LEFT JOIN users u ON u.uid=m.uploader_id '
            f'WHERE {where} ORDER BY m.id DESC LIMIT :limit OFFSET :offset'), params).mappings()
        return [dict(row) for row in rows], total

    def trash(self, media_id, actor_id):
        item = self.item(media_id, lock=True)
        if item['deleted_at']:
            return True
        if self.references(media_id)['total']:
            raise HTTPException(409, 'media_in_use')
        self.db.execute(text('UPDATE media_objects SET deleted_at=:now,deleted_by=:uid WHERE id=:id'),
                        {'now': datetime.utcnow(), 'uid': actor_id, 'id': media_id})
        self.db.commit()
        return True

    def restore(self, media_id):
        self.item(media_id, lock=True)
        self.db.execute(text('UPDATE media_objects SET deleted_at=NULL,deleted_by=NULL WHERE id=:id'),
                        {'id': media_id})
        self.db.commit()
        return self.item(media_id)

    def purge(self, media_id):
        item = self.item(media_id, lock=True)
        if not item['deleted_at']:
            raise HTTPException(409, 'media_must_be_trashed_first')
        if self.references(media_id)['total']:
            raise HTTPException(409, 'media_in_use')
        from app.services.media_storage import MediaStorageService
        return MediaStorageService(self.db).purge(media_id, actor_id=self.uid)
