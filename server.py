#!/usr/bin/env python3
"""No-dependency local demo and Telegram Mini App server."""
import os, json, time, threading, mimetypes
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from zoneinfo import ZoneInfoNotFoundError
from store import Store
from worker import Scheduler, Telegram, Bot
from auth import validate_init_data

ROOT=Path(__file__).parent

def load_env():
    path=ROOT/'.env'
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip() and not line.lstrip().startswith('#') and '=' in line:
                k,v=line.split('=',1); os.environ.setdefault(k.strip(),v.strip().strip('\"').strip("'"))

class App:
    def __init__(self,mode='demo',db=None,token='',owners=None,app_url=''):
        if mode not in ('demo','production'): raise ValueError('APP_MODE must be demo or production')
        self.mode=mode; self.token=token; self.owners=owners or set()
        if mode=='production' and (not token or not self.owners or not app_url.startswith('https://')): raise ValueError('Production needs token, owner IDs and HTTPS APP_URL')
        # App mode is recorded in DB. Switching mode can never reveal existing data.
        self.store=Store(db or str(ROOT/(mode+'.sqlite3')))
        with self.store.db() as c:
            r=c.execute("SELECT value FROM meta WHERE key='mode'").fetchone()
            if r and r[0]!=mode: raise ValueError('Database belongs to another mode')
            c.execute("INSERT OR IGNORE INTO meta VALUES('mode',?)",(mode,))
        tg=Telegram(token) if mode=='production' else None
        self.scheduler=Scheduler(self.store,tg.send if tg else None)
        self.bot=Bot(self.store,tg,self.owners,app_url) if tg else None
    def user(self,headers):
        if self.mode=='demo':
            if headers.get('X-Demo-Mode')!='1': raise ValueError('Please use the demo entry point')
            return -1
        raw=headers.get('Authorization','')
        if not raw.startswith('tma '): raise ValueError('Please open the Mini App from Telegram')
        return validate_init_data(raw[4:],self.token,self.owners)
    def loop(self,stop):
        while not stop.is_set():
            try:
                self.scheduler.tick()
                if self.bot: self.bot.poll()
            except Exception: print('Worker retrying after an operational error',flush=True)
            stop.wait(3)

def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def respond(self,status,body,kind='application/json; charset=utf-8'):
            b=json.dumps(body,ensure_ascii=False).encode() if isinstance(body,(dict,list)) else body
            self.send_response(status); self.send_header('Content-Type',kind); self.send_header('Content-Length',str(len(b)))
            self.send_header('Cache-Control','no-store'); self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' https://telegram.org; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors https://web.telegram.org https://*.telegram.org")
            self.end_headers(); self.wfile.write(b)
        def do_GET(self):
            p=urlparse(self.path)
            if p.path=='/api/config': return self.respond(200,{'mode':app.mode})
            if p.path=='/telegram-sdk.js':
                if app.mode=='demo': return self.respond(200,b'/* Demo has no Telegram SDK or external calls. */','text/javascript')
                self.send_response(302); self.send_header('Location','https://telegram.org/js/telegram-web-app.js'); self.end_headers(); return
            if p.path=='/api/state':
                try: uid=app.user(self.headers)
                except ValueError: return self.respond(401,{'error':'Authentication failed. Please reopen the Mini App.'})
                try: return self.respond(200,{'mode':app.mode,**app.store.state(uid,parse_qs(p.query).get('week',[None])[0])})
                except (ValueError,ZoneInfoNotFoundError): return self.respond(400,{'error':'Invalid date or time zone'})
            files={'/':'index.html','/app.js':'app.js','/style.css':'style.css','/static/app.js':'app.js','/static/style.css':'style.css'}
            if p.path not in files: return self.respond(404,{'error':'Not found'})
            f=ROOT/'static'/files[p.path]
            if not f.exists(): return self.respond(503,{'error':'UI building'})
            return self.respond(200,f.read_bytes(),(mimetypes.guess_type(str(f))[0] or 'application/octet-stream')+'; charset=utf-8')
        def do_POST(self):
            try: uid=app.user(self.headers)
            except ValueError: return self.respond(401,{'error':'Authentication failed. Please reopen the Mini App.'})
            if not self.headers.get('Content-Type','').startswith('application/json'): return self.respond(415,{'error':'JSON content is required'})
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=16384: raise ValueError('The request is empty or too large')
                d=json.loads(self.rfile.read(size))
                if not isinstance(d,dict): raise ValueError('Invalid request format')
                route=urlparse(self.path).path.removeprefix('/api/')
                if route=='demo/remind' and app.mode=='demo':
                    p=app.store.state(uid)['projects'][0]
                    result=app.store.mutate(uid,'reminders',{'project_id':p['id'],'label':'Demo: simulated reminder only. No Telegram message was sent.','due_at':time.time()})
                    app.scheduler.tick()
                else: result=app.store.mutate(uid,route,d)
                self.respond(200,result)
            except (ValueError,KeyError,TypeError,OverflowError,ZoneInfoNotFoundError): self.respond(400,{'error':'Check your input. Time entries cannot overlap or be in the future, and records must belong to your account.'})
            except Exception: self.respond(500,{'error':'Unable to save right now. Please try again.'})
    return Handler

def main():
    load_env(); mode=os.getenv('APP_MODE','demo')
    app=App(mode,os.getenv('DB_PATH'),os.getenv('TELEGRAM_BOT_TOKEN',''),{int(x) for x in os.getenv('TELEGRAM_OWNER_IDS','').split(',') if x.strip()},os.getenv('APP_URL',''))
    stop=threading.Event(); threading.Thread(target=app.loop,args=(stop,),daemon=True).start()
    host=os.getenv('HOST','127.0.0.1'); port=int(os.getenv('PORT','8787'))
    server=ThreadingHTTPServer((host,port),make_handler(app))
    print(f'TimePocket {mode} listening on http://{host}:{port} (local development, not permanent hosting)',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: stop.set(); server.server_close()
if __name__=='__main__': main()
