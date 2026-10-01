import unittest,tempfile,threading,json,urllib.request,urllib.error
from http.server import ThreadingHTTPServer
from pathlib import Path
from server import App,make_handler

class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=str(Path(self.tmp.name)/'demo.sqlite3')
        self.app=App(db=self.path);self.server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(self.app));self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.base='http://127.0.0.1:'+str(self.server.server_port)
    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()
    def req(self,path,data=None,headers=None):
        req=urllib.request.Request(self.base+path,json.dumps(data).encode() if data is not None else None,headers or {'X-Demo-Mode':'1','Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(req) as r:return r.status,json.load(r)
        except urllib.error.HTTPError as e:return e.code,json.load(e)
    def test_api_flow(self):
        code,state=self.req('/api/state');self.assertEqual(code,200);self.assertEqual(state['total_budget'],10)
        p=state['projects'][0]['id'];_,timer=self.req('/api/timer/start',{'project_id':p})
        self.assertEqual(self.req('/api/timer/stop',{'timer_id':timer['id']})[0],200)
        self.assertEqual(self.req('/api/demo/remind',{})[0],200)
        _,state=self.req('/api/state');self.assertEqual(state['reminders'][0]['status'],'simulated')
    def test_auth_required_and_input(self):
        self.assertEqual(self.req('/api/state',headers={'Authorization':'tma forged'})[0],401)
        self.assertEqual(self.req('/api/state?week=bad')[0],400)
        self.assertEqual(self.req('/api/settings',{'timezone':'../etc/passwd'})[0],400)
        self.assertEqual(self.req('/api/logs',[])[0],400)
    def test_mode_guard(self):
        with self.assertRaises(ValueError):App('production',self.path,'token',{1},'https://example.com')
        with self.assertRaises(ValueError):App('production',str(Path(self.tmp.name)/'prod.sqlite3'))

class ProductionApiTests(unittest.TestCase):
    def test_verified_identity_overrides_client_identity(self):
        import time,hmac,hashlib
        from urllib.parse import urlencode
        with tempfile.TemporaryDirectory() as directory:
            token='unit-test-token'; app=App('production',str(Path(directory)/'prod.sqlite3'),token,{123},'https://example.com')
            server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(app)); thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                data={'auth_date':str(int(time.time())),'user':json.dumps({'id':123})}
                secret=hmac.new(b'WebAppData',token.encode(),hashlib.sha256).digest()
                data['hash']=hmac.new(secret,'\n'.join(f'{k}={v}' for k,v in sorted(data.items())).encode(),hashlib.sha256).hexdigest()
                req=urllib.request.Request(f'http://127.0.0.1:{server.server_port}/api/state?userId=999',headers={'Authorization':'tma '+urlencode(data)})
                with urllib.request.urlopen(req) as r:state=json.load(r)
                self.assertEqual(state['mode'],'production')
                with app.store.db() as c:self.assertEqual([r[0] for r in c.execute('SELECT id FROM users')],[123])
                for path in ('/api/state','/api/demo/remind'):
                    req=urllib.request.Request(f'http://127.0.0.1:{server.server_port}'+path,b'{}' if 'remind' in path else None,{'X-Demo-Mode':'1','Content-Type':'application/json'})
                    with self.assertRaises(urllib.error.HTTPError) as ctx:urllib.request.urlopen(req)
                    self.assertEqual(ctx.exception.code,401)
            finally:server.shutdown();server.server_close();thread.join()
