#!/usr/bin/env python3
"""Consume only preview publish requests; atomic activation and rollback."""
import datetime as dt,fcntl,json,os,pathlib,subprocess,sys,shutil
BASE=pathlib.Path('/data/replow-preview'); STATE=BASE/'build-state'; SOURCE=BASE/'source/www'
def now():return dt.datetime.now(dt.timezone.utc).isoformat()
def update(**values):
 try:data=json.loads((STATE/'status.json').read_text())
 except (OSError,ValueError):data={}
 data.update(values);tmp=STATE/'status.tmp';tmp.write_text(json.dumps(data));tmp.replace(STATE/'status.json');return data

def isolate(root):
 replacements={'https://www.replow.org':'https://www.preview.replow.org','https://account.replow.org':'https://account.preview.replow.org','https://admin.replow.org':'https://admin.preview.replow.org','https://api.4z.ink':'https://www.preview.replow.org'}
 for p in root.rglob('*'):
  if p.is_file() and p.suffix in ('.html','.js','.json','.xml','.css'):
   s=p.read_text()
   for old,new in replacements.items():s=s.replace(old,new)
   if p.suffix=='.html':s=s.replace('</head>','<meta name="robots" content="noindex,nofollow"></head>')
   p.write_text(s)

def main():
 STATE.mkdir(exist_ok=True)
 with (STATE/'worker.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  request=STATE/'request'
  if not request.exists():return
  request.unlink();started=now();version='preview-'+dt.datetime.now().strftime('%Y%m%d-%H%M%S')
  previous=(BASE/'www').resolve();switched=False
  try:
   update(status='building',stage='正在构建预览内容',started_at=started,content_cutoff_at=started,finished_at='',version=version,error='',run_url='')
   env=os.environ.copy();env.update(API_BASE_URL='http://127.0.0.1:8814',REPLOW_RELEASE='v'+dt.datetime.now().strftime('%y.%m.%d')+'-u'+dt.datetime.now().strftime('%H%M%S'),NODE_OPTIONS='--max-old-space-size=1400',PATH='/data/replow-next/bin:'+env.get('PATH',''),BIOME_MAX_THREADS='1',HUSKY='0')
   with (STATE/'build.log').open('w') as log:
    for command in [['/data/replow-next/bin/pnpm','check'],['/data/replow-next/bin/pnpm','build']]:
     subprocess.run(command,cwd=SOURCE,env=env,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=1800)
   isolate(SOURCE/'dist');dest=BASE/'releases'/version/'dist';dest.parent.mkdir()
   shutil.copytree(SOURCE/'dist',dest)
   for f in ('index.html','reading/index.html','fanqie/index.html','pagefind/pagefind.js'):assert (dest/f).is_file(),f
   update(status='deploying',stage='正在验证预览部署')
   link=BASE/'www.next';link.symlink_to(dest);link.replace(BASE/'www');switched=True
   subprocess.run(['curl','--noproxy','*','-fsS','--max-time','15','--resolve','www.preview.replow.org:443:127.0.0.1','https://www.preview.replow.org/','-o','/dev/null'],check=True,capture_output=True)
   data=update(status='success',stage='预览发布完成',finished_at=now(),error='')
   tmp=STATE/'deployed.tmp';tmp.write_text(json.dumps(data));tmp.replace(STATE/'deployed.json')
  except Exception:
   if switched:
    link=BASE/'www.rollback';link.symlink_to(previous);link.replace(BASE/'www')
   update(status='failed',stage='预览发布失败',finished_at=now(),error='构建或验证失败，保留上次可用预览；可重试。')
   raise
if __name__=='__main__':main()
