import unittest,tempfile,time
from pathlib import Path
from store import Store
from worker import Scheduler,RetryDelivery,UncertainDelivery,Bot

class QueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.s=Store(str(Path(self.tmp.name)/'test.sqlite3'));self.uid=1;self.p=self.s.state(1)['projects'][0]['id'];self.now=time.time()
    def tearDown(self): self.tmp.cleanup()
    def add(self,offset=0,label='test'):
        return self.s.mutate(1,'reminders',{'project_id':self.p,'label':label,'due_at':self.now+offset},now=self.now)['id']
    def row(self,rid):
        with self.s.db() as c:return dict(c.execute('SELECT * FROM reminders WHERE id=?',(rid,)).fetchone())
    def test_restart_dedup(self):
        rid=self.add(); calls=[]
        Scheduler(self.s,lambda r:calls.append(r['id']) or 55).tick(self.now)
        Scheduler(Store(self.s.path),lambda r:calls.append(r['id']) or 55).tick(self.now+1)
        self.assertEqual(calls,[rid]);self.assertEqual(self.row(rid)['status'],'sent')
    def test_safe_retry_bounded(self):
        rid=self.add()
        def fail(r):raise RetryDelivery()
        w=Scheduler(self.s,fail)
        w.tick(self.now);w.tick(self.now+1);self.assertEqual(self.row(rid)['attempts'],1)
        w.tick(self.now+61);w.tick(self.now+182)
        self.assertEqual(self.row(rid)['status'],'failed');self.assertEqual(self.row(rid)['attempts'],3)
    def test_ambiguous_never_resends(self):
        rid=self.add();calls=[]
        def fail(r):calls.append(r['id']);raise UncertainDelivery()
        w=Scheduler(self.s,fail);w.tick(self.now);w.tick(self.now+120)
        self.assertEqual(len(calls),1);self.assertEqual(self.row(rid)['status'],'uncertain')
    def test_crash_lease_is_uncertain(self):
        rid=self.add()
        with self.s.db() as c:c.execute("UPDATE reminders SET status='delivering',lease_at=? WHERE id=?",(self.now-70,rid))
        self.assertEqual(Scheduler(self.s).tick(self.now),0);self.assertEqual(self.row(rid)['status'],'uncertain')
    def test_missed_and_backlog_bound(self):
        ids=[self.add(-i,'reminder '+str(i)) for i in range(5)]
        old=self.add(0,'old')
        with self.s.db() as c:c.execute('UPDATE reminders SET due_at=? WHERE id=?',(self.now-4000,old))
        self.assertEqual(Scheduler(self.s).tick(self.now),3)
        self.assertEqual(self.row(old)['status'],'expired')
        self.assertEqual(sum(self.row(r)['status']=='expired' for r in ids),2)
    def test_bot_owner_only(self):
        class Fake:
            def __init__(self):self.calls=[]
            def call(self,*args):self.calls.append(args)
        t=Fake(); b=Bot(self.s,t,{1},'https://example.com')
        b.handle({'message':{'from':{'id':2},'chat':{'id':2,'type':'private'},'text':'/start'}})
        b.handle({'message':{'from':{'id':1},'chat':{'id':1,'type':'group'},'text':'/start'}})
        self.assertEqual(t.calls,[])
        b.handle({'message':{'from':{'id':1},'chat':{'id':1,'type':'private'},'text':'/start'}})
        self.assertEqual(t.calls[0][0],'sendMessage')

    def test_bot_update_replay_is_deduplicated(self):
        update={'update_id':20,'message':{'from':{'id':1},'chat':{'id':1,'type':'private'},'text':'/start'}}
        class Fake:
            def __init__(self):self.sent=[]
            def call(self,method,payload):
                if method=='getUpdates':return [update]
                self.sent.append(payload);return {'message_id':1}
        t=Fake();Bot(self.s,t,{1},'https://example.com').poll();Bot(Store(self.s.path),t,{1},'https://example.com').poll()
        self.assertEqual(len(t.sent),1)
