"""Persistent bounded reminder queue and owner-only Telegram polling adapter."""
import json, time, urllib.request, urllib.error

class RetryDelivery(Exception): pass
class PermanentDelivery(Exception): pass
class UncertainDelivery(Exception): pass

class Telegram:
    def __init__(self,token): self.token=token
    def call(self,method,payload):
        # Never log URLs: the bot credential is in the Telegram API URL.
        req=urllib.request.Request('https://api.telegram.org/bot'+self.token+'/'+method,json.dumps(payload).encode(),{'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(req,timeout=20) as r: result=json.load(r)
        except urllib.error.HTTPError as e:
            if e.code==429: raise RetryDelivery('rate_limited') from None
            if 400<=e.code<500: raise PermanentDelivery('telegram_rejected') from None
            raise UncertainDelivery('telegram_unconfirmed') from None
        except Exception: raise UncertainDelivery('network_unconfirmed') from None
        if not result.get('ok'): raise PermanentDelivery('telegram_rejected')
        return result['result']
    def send(self,r):
        return self.call('sendMessage',{'chat_id':r['user_id'],'text':f"Make a little time for {r['project_name']} 🌱\n{r['label']}\nStart when you are ready, or come back later.",'reply_markup':{'inline_keyboard':[[{'text':'Snooze 15 minutes','callback_data':'s:'+r['id']},{'text':'Skip this time','callback_data':'k:'+r['id']}]]}})['message_id']

class Scheduler:
    def __init__(self,store,sender=None): self.store=store; self.sender=sender
    def tick(self,now=None):
        now=time.time() if now is None else now
        with self.store.db() as c:
            c.execute('BEGIN IMMEDIATE')
            # A process may have died AFTER Telegram accepted delivery. Do not blindly resend.
            c.execute("UPDATE reminders SET status='uncertain',last_error='process_interrupted' WHERE status='delivering' AND lease_at<?",(now-60,))
            c.execute("UPDATE reminders SET status='expired',last_error='missed_window' WHERE status='pending' AND due_at<?",(now-3600,))
            rows=c.execute("SELECT * FROM reminders WHERE status='pending' AND due_at<=? AND next_try<=? ORDER BY due_at DESC",(now,now)).fetchall()
            # Maximum three overdue deliveries per user per wake, expire older backlog.
            counts={}; selected=[]
            for r in rows:
                counts[r['user_id']]=counts.get(r['user_id'],0)+1
                if counts[r['user_id']]>3: c.execute("UPDATE reminders SET status='expired',last_error='backlog_limit' WHERE id=?",(r['id'],)); continue
                c.execute("UPDATE reminders SET status='delivering',lease_at=?,attempts=attempts+1 WHERE id=?",(now,r['id']))
                p=c.execute('SELECT name FROM projects WHERE id=?',(r['project_id'],)).fetchone()
                selected.append({**dict(r),'project_name':p[0]})
        for r in selected:
            status='simulated' if self.sender is None else 'sent'; err=''; msg=None; retry=0
            try:
                if self.sender: msg=self.sender(r)
            except RetryDelivery:
                status='pending' if r['attempts']+1<3 else 'failed'; err='rate_limited'; retry=now+60*(2**r['attempts'])
            except PermanentDelivery: status='failed'; err='telegram_rejected'
            except Exception: status='uncertain'; err='delivery_unconfirmed'
            with self.store.db() as c: c.execute('UPDATE reminders SET status=?,last_error=?,next_try=?,message_id=? WHERE id=?',(status,err,retry,msg,r['id']))
        return len(selected)

class Bot:
    def __init__(self,store,telegram,owners,app_url): self.store=store; self.telegram=telegram; self.owners=owners; self.app_url=app_url
    def poll(self):
        with self.store.db() as c:
            row=c.execute("SELECT value FROM meta WHERE key='offset'").fetchone(); offset=int(row[0]) if row else 0
        updates=self.telegram.call('getUpdates',{'offset':offset,'timeout':0,'allowed_updates':['message','callback_query']})
        for u in updates:
            # Commit inbox receipt before outbound effects: a crash can lose a command reply,
            # but must never replay a mutation or duplicate a reply automatically.
            with self.store.db() as c:
                seen=c.execute('INSERT OR IGNORE INTO updates VALUES(?)',(u['update_id'],)).rowcount==0
                c.execute("INSERT OR REPLACE INTO meta VALUES('offset',?)",(str(u['update_id']+1),))
            if seen: continue
            try: self.handle(u)
            except Exception: pass # No credentials, updates or personal notes in logs.
    def handle(self,u):
        cb=u.get('callback_query'); m=u.get('message') or (cb or {}).get('message',{})
        source=(cb or m).get('from',{}); uid=source.get('id')
        if uid not in self.owners or m.get('chat',{}).get('type')!='private' or m['chat']['id']!=uid: return
        if cb:
            value=cb.get('data',''); action,_,rid=value.partition(':')
            if action not in ('s','k'): return
            try:
                self.store.mutate(uid,'reminders/action',{'id':rid,'action':'snooze' if action=='s' else 'skip','minutes':15})
                text='All set. We will remind you later.' if action=='s' else 'Skipped this time'
            except ValueError as e: text=str(e)
            self.telegram.call('answerCallbackQuery',{'callback_query_id':cb['id'],'text':text})
            return
        command=m.get('text','').split(' ')[0].split('@')[0]
        if command not in ('/start','/help','/today','/stop'): return
        state=self.store.state(uid)
        if command=='/stop' and state['timer']:
            self.store.mutate(uid,'timer/stop',{'timer_id':state['timer']['id']}); text='Timer stopped. Add your progress notes in the Mini App.'
        elif command=='/today': text=f"This week: {state['total_actual']:.1f} / {state['total_budget']:.1f} hours. Keep your own pace 🌱"
        else: text='Welcome to TimePocket 🌱\nMake time, notice progress, and leave room to rest.\n/today View this week · /stop Stop the timer'
        self.telegram.call('sendMessage',{'chat_id':uid,'text':text,'reply_markup':{'inline_keyboard':[[{'text':'Open TimePocket','web_app':{'url':self.app_url}}]]}})
