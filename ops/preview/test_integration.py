"""Run only against the isolated preview DB/API; uses temporary test identities."""
import os,sys,base64,uuid,json
from pathlib import Path
from dotenv import load_dotenv
load_dotenv('/data/replow-preview/source/api/.env')
sys.path.insert(0,'/data/replow-preview/source/api')
from sqlalchemy import text
from app.db.session import engine
from app.core.security import create_access_token,password_hasher
from app.services.media_trash import contains_url
import httpx
assert engine.url.database=='replow_preview'
run=uuid.uuid4().hex[:10];uid=900001
with engine.begin() as c:
 c.execute(text("INSERT INTO users(uid,username,email,password_hash,display_name,role,status,session_version,setup_completed,created_at,updated_at) VALUES (:uid,:name,:email,:hash,'Preview QA','user','active',0,1,NOW(),NOW())"),{'uid':uid,'name':'preview_qa_'+run,'email':run+'@example.invalid','hash':password_hasher.hash(uuid.uuid4().hex)})
client=httpx.Client(base_url='http://127.0.0.1:8814/v1',timeout=25)
with engine.connect() as c: sv=c.execute(text('SELECT session_version FROM users WHERE uid=10000')).scalar_one()
admin={'Authorization':'Bearer '+create_access_token(10000,'admin',sv)[0]}
user={'Authorization':'Bearer '+create_access_token(uid,'user')[0]}
created_articles=[];created_media=[];checks=[]
def req(method,path,who=admin,status=200,**kwargs):
 r=client.request(method,path,headers=who,**kwargs)
 assert r.status_code==status,(method,path,r.status_code,r.text[:400])
 return r.json() if r.headers.get('content-type','').startswith('application/json') else r

def check(label):checks.append(label);print('PASS',label)
try:
 req('GET','/admin/media',who={},status=401)
 req('GET','/admin/media',who=user,status=403);check('authentication and admin boundary')
 png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jG3kAAAAASUVORK5CYII=')
 media=req('POST','/account/media/upload',who=user,files={'file':('preview-test.png',png,'image/png')},data={'category':'article'})['data'];mid=media['id'];created_media.append(mid)
 assert media['storage_backend']=='local';assert 'www.preview.replow.org' in media['public_url']
 item=req('GET','/account/media',who=user)['items'];assert any(m['id']==mid for m in item)
 req('GET',f'/account/media/{mid}/references',who=admin,status=404)
 req('DELETE',f'/account/media/{mid}',who=admin,status=404);check('private media ownership and isolated upload')
 body={'title':'Preview test '+run,'slug':'preview-qa-'+run,'body_markdown':'original body','status':'published','tags':[]}
 article=req('POST','/account/articles',who=user,json=body)['data'];aid=article['id'];created_articles.append(aid)
 versions=req('GET',f'/account/articles/{aid}/versions',who=user)['items'];assert len(versions)==1
 first=versions[0]['id']
 req('GET',f'/account/articles/{aid}/versions',who=admin,status=404)
 req('GET',f'/account/articles/{aid}/versions/{first}',who=admin,status=404);check('version creation and account article ownership')
 key='qa-'+run
 draft={'version':0,'article_id':aid,'payload':{**body,'body_markdown':'UNPUBLISHED autosave'}}
 saved=req('PUT','/account/article-drafts/'+key,who=user,json=draft)['data'];assert saved['version']==1
 assert req('GET',f'/account/articles/{aid}',who=user)['data']['body_markdown']=='original body'
 assert req('GET','/account/article-drafts/'+key,who=admin)['data'] is None
 req('PUT','/account/article-drafts/'+key,who=user,json=draft,status=409)
 req('PUT','/account/article-drafts/no-access',who=admin,json=draft,status=404)
 check('autosave does not publish, private drafts and concurrent write protection')
 updated=req('PUT',f'/account/articles/{aid}',who=user,json={**body,'body_markdown':'second body','_base_token':article['revision_token']})['data']
 req('PUT',f'/account/articles/{aid}',who=user,json={**body,'_base_token':article['revision_token']},status=409)
 versions=req('GET',f'/account/articles/{aid}/versions',who=user)['items'];assert len(versions)==2
 restored=req('POST',f'/account/articles/{aid}/versions/{first}/restore',who=user,json={'_base_token':updated['revision_token']})['data']
 assert restored['body_markdown']=='original body' and restored['status']=='published'
 assert len(req('GET',f'/account/articles/{aid}/versions',who=user)['items'])==3
 check('manual snapshots, conflict detection and reversible historical restore')
 linked=req('PUT',f'/account/articles/{aid}',who=user,json={**body,'body_markdown':'![image]('+media['public_url']+')','_base_token':restored['revision_token']})['data']
 refs=req('GET',f'/account/media/{mid}/references',who=user)['data'];assert refs['total']>0
 assert all(not x['id'] and x['title']==x['type'] for x in refs['items'])
 req('DELETE',f'/account/media/{mid}',who=user,status=409)
 check('reference check blocks deletion and hides other content metadata')
 req('PUT',f'/account/articles/{aid}',who=user,json={**body,'body_markdown':'unlinked','_base_token':linked['revision_token']})
 refs=req('GET',f'/admin/media/{mid}/references',who=admin)['data'];assert any(x['type']=='文章历史版本' for x in refs['items'])
 req('DELETE',f'/admin/media/{mid}',status=409);check('historical image references stay protected')
 free=req('POST','/account/media/upload',who=user,files={'file':('free.png',png,'image/png')},data={'category':'avatar'})['data'];fid=free['id'];created_media.append(fid)
 keyfile=free['object_key'];path=Path('/data/replow-preview/media')/keyfile
 assert path.is_file()
 req('DELETE',f'/account/media/{fid}/purge',who=user,status=409)
 req('DELETE',f'/account/media/{fid}',who=user)
 assert path.is_file() and not any(x['id']==fid for x in req('GET','/account/media',who=user)['items'])
 assert any(x['id']==fid for x in req('GET','/account/media?trash=true',who=user)['items'])
 restored_media=req('POST',f'/account/media/{fid}/restore',who=user)['data'];assert restored_media['public_url']==free['public_url']
 req('DELETE',f'/account/media/{fid}',who=user)
 req('DELETE',f'/account/media/{fid}/purge',who=user)
 assert not path.exists();check('trash retains bytes, restore preserves URL and purge removes isolated file')
 status=req('GET','/admin/site/build')['data'];assert status['environment']=='preview' and status['site_url']=='https://www.preview.replow.org'
 check('real publishing status uses isolated preview state')
 assert contains_url('![x](https://a.example/i.png?x=1)','https://a.example/i.png')
 assert not contains_url('https://a.example/i.png2','https://a.example/i.png')
 assert contains_url(json.dumps({'u':'https://a.example/i.png'}),'https://a.example/i.png')
 check('URL references respect boundaries and JSON content')
finally:
 with engine.begin() as c:
  for aid in created_articles:c.execute(text('DELETE FROM articles WHERE id=:id'),{'id':aid})
  for mid in created_media:
   row=c.execute(text('SELECT object_key FROM media_objects WHERE id=:id'),{'id':mid}).scalar()
   if row:
    if isinstance(row,bytes):row=row.decode()
    path=Path('/data/replow-preview/media')/row
    if path.is_file():path.unlink()
   c.execute(text('DELETE FROM media_objects WHERE id=:id'),{'id':mid})
  c.execute(text('DELETE FROM users WHERE uid=:id'),{'id':uid})
print(json.dumps({'passed':len(checks),'checks':checks}))
