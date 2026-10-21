"""Discussion integration tests with connection-local temporary tables only."""
import sys, os, io, re, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.chdir(Path(__file__).resolve().parents[1])
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session
from PIL import Image
from app.main import app
from app.db.session import engine, get_db
from app.core.security import create_access_token
from app.services.media_storage import MediaStorageService

TABLES = ["users","articles","comments","comment_image_uploads","media_objects"]
class DiscussionTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.connection=engine.connect()
  cls.transaction=cls.connection.begin()
  cls.db=Session(bind=cls.connection,expire_on_commit=False,join_transaction_mode="create_savepoint")
  cls.media_before=set(cls.db.execute(text("SELECT id FROM media_objects")).scalars())
  app.dependency_overrides[get_db]=lambda:cls.db
  cls.client=TestClient(app,base_url="https://www.example.com")
  for uid in [99000001,99000002]:
   cls.db.execute(text("""INSERT INTO users(uid,username,email,password_hash,display_name,role,status)
    VALUES (:uid,:name,:email,'!password-unset!',:name,'user','active')"""),
    {"uid":uid,"name":"comment_fixture_"+str(uid),"email":str(uid)+"@example.invalid"})
  cls.db.execute(text("""INSERT INTO articles(id,slug,title,body_markdown,status)
   VALUES (99000001,'comment-fixture','Fixture article','test','published'),
          (99000002,'draft-fixture','Draft article','secret','draft'),
          (99000003,'other-fixture','Other article','test','published')"""))
  cls.db.commit()
  cls.a={"Authorization":"Bearer "+create_access_token(99000001,"user")[0]}
  cls.b={"Authorization":"Bearer "+create_access_token(99000002,"user")[0]}
 @classmethod
 def tearDownClass(cls):
  cls.client.close(); app.dependency_overrides.clear();cls.db.close()
  cls.transaction.rollback()
  cls.connection.close()
 def setUp(self):
  self.db.rollback()
  self.db.execute(text("DELETE FROM comments WHERE article_id IN (99000001,99000002,99000003)"));self.db.execute(text("DELETE FROM comment_image_uploads WHERE user_id IN (99000001,99000002)"));self.db.commit()
 def post(self,headers,body="**Hello**",parent=None,article=99000001):
  return self.client.post("/v1/account/comments",headers=headers,json={"article_id":article,"parent_id":parent,"body_markdown":body})
 def test_anonymous_and_validation(self):
  self.assertEqual(self.post({}).status_code,401)
  self.assertEqual(self.client.post("/v1/account/comments/images",files={"file":("x.png",b"x","image/png")}).status_code,401)
  self.assertEqual(self.post(self.a," ").status_code,422)
  self.assertEqual(self.post(self.a,article=99000002).status_code,404)
  self.assertEqual(self.post(self.a,parent=999).status_code,422)
 def test_reply_notifications_and_ownership(self):
  root=self.post(self.a,"**Markdown**\n![image](https://example.invalid/x.png)")
  self.assertEqual(root.status_code,201,root.text);rid=root.json()["data"]["id"]
  reply=self.post(self.b,"Reply fixture",rid)
  self.assertEqual(reply.status_code,201,reply.text);cid=reply.json()["data"]["id"]
  notice=self.client.get("/v1/account/notifications",headers=self.a)
  self.assertEqual(notice.status_code,200,notice.text)
  n=next(n for n in notice.json()["items"] if n["id"]=="reply:"+str(cid))
  self.assertIn("/post/comment-fixture/#comment-"+str(cid),n["href"])
  own=self.client.get("/v1/account/notifications",headers=self.b).json()["items"]
  self.assertFalse(any(n["type"]=="comment_reply" for n in own))
  self.assertEqual(self.client.put("/v1/account/comments/"+str(rid),headers=self.b,json={"body_markdown":"stolen"}).status_code,404)
  self.assertEqual(self.client.delete("/v1/account/comments/"+str(rid),headers=self.b).status_code,404)
  self.assertEqual(self.post(self.a).status_code,429)
 def test_visibility_and_cross_article(self):
  root=self.post(self.a);rid=root.json()["data"]["id"]
  self.assertEqual(self.post(self.b,parent=rid,article=99000003).status_code,422)
  self.db.execute(text("UPDATE comments SET status='hidden' WHERE id=:id"),{"id":rid});self.db.commit()
  self.assertEqual(self.client.get("/v1/public/comments?article_id=99000001").json()["total"],0)
  self.assertEqual(self.client.get("/v1/public/articles/99000001/discussion").json()["total"],0)
  self.assertEqual(self.client.get("/v1/public/articles/99000002/discussion").status_code,404)
  self.assertEqual(self.post(self.b,parent=rid).status_code,422)
 def test_images_invalid_size_and_quota(self):
  for name,data,kind,status in [("x.svg",b"<svg onload=alert(1)>","image/svg+xml",415),("fake.png",b"not an image","image/png",415),("big.png",b"x"*(5*1024*1024+1),"image/png",413)]:
   r=self.client.post("/v1/account/comments/images",headers=self.a,files={"file":(name,data,kind)})
   self.assertEqual(r.status_code,status,r.text)
  self.assertEqual(self.post(self.a,"\n".join("![x](https://example.invalid/x.png)" for _ in range(7))).status_code,422)
 def test_real_image_storage_roundtrip(self):
  data=io.BytesIO();Image.new("RGB",(4,4),"#abc").save(data,"PNG")
  r=self.client.post("/v1/account/comments/images",headers=self.a,files={"file":("fixture.png",data.getvalue(),"image/png")})
  self.assertEqual(r.status_code,201,r.text);self.assertTrue(r.json()["data"]["url"].startswith("https://"))
  media=[mid for mid in self.db.execute(text("SELECT id FROM media_objects")).scalars() if mid not in self.media_before]
  self.assertEqual(len(media),1)
  for mid in media:MediaStorageService(self.db).delete(mid)
  self.db.execute(text("INSERT INTO comment_image_uploads(user_id) VALUES "+",".join("(99000001)" for _ in range(30))));self.db.commit()
  r=self.client.post("/v1/account/comments/images",headers=self.a,files={"file":("fixture.png",data.getvalue(),"image/png")})
  self.assertEqual(r.status_code,429,r.text)
if __name__=="__main__":unittest.main(verbosity=2)
