"""SQLite domain model. UTC timestamps, IANA zones and local Monday budgets."""
import sqlite3, time, math, uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

DEFAULTS = [('Learning',3),('Side Project',2),('Exercise',2),('Reading',1),('Writing',1),('Weekly Review',1)]

def number(value, low, high):
    n=float(value)
    if not math.isfinite(n) or not low <= n <= high: raise ValueError('Value is out of range')
    return n

def week_bounds(zone, day=None, now=None):
    tz=ZoneInfo(zone)
    d=datetime.strptime(day,'%Y-%m-%d').date() if day else datetime.fromtimestamp(time.time() if now is None else now,tz).date()
    d-=timedelta(days=d.weekday())
    start=datetime.combine(d,datetime.min.time(),tz)
    end=datetime.combine(d+timedelta(days=7),datetime.min.time(),tz)
    return d.isoformat(),start.timestamp(),end.timestamp()

class Store:
    def __init__(self,path):
        self.path=path
        with self.db() as c:
            c.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,timezone TEXT NOT NULL DEFAULT 'UTC');
            CREATE TABLE IF NOT EXISTS projects(id INTEGER PRIMARY KEY,user_id INTEGER,name TEXT,budget_hours REAL);
            CREATE TABLE IF NOT EXISTS budgets(user_id INTEGER,project_id INTEGER,week TEXT,hours REAL,PRIMARY KEY(user_id,project_id,week));
            CREATE TABLE IF NOT EXISTS logs(id TEXT PRIMARY KEY,user_id INTEGER,project_id INTEGER,started_at REAL,ended_at REAL,accomplishments TEXT DEFAULT '',blockers TEXT DEFAULT '',next_steps TEXT DEFAULT '',request_id TEXT,UNIQUE(user_id,request_id));
            CREATE UNIQUE INDEX IF NOT EXISTS one_timer ON logs(user_id) WHERE ended_at IS NULL;
            CREATE TABLE IF NOT EXISTS reminders(id TEXT PRIMARY KEY,user_id INTEGER,project_id INTEGER,label TEXT,due_at REAL,status TEXT DEFAULT 'pending',attempts INTEGER DEFAULT 0,next_try REAL DEFAULT 0,lease_at REAL,message_id INTEGER,last_error TEXT DEFAULT '',created_at REAL);
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT);
            CREATE TABLE IF NOT EXISTS updates(id INTEGER PRIMARY KEY);
            ''')
    @contextmanager
    def db(self):
        c=sqlite3.connect(self.path,timeout=10); c.row_factory=sqlite3.Row
        try:
            with c: yield c
        finally: c.close()
    def ensure(self,uid,c):
        if not c.execute('SELECT 1 FROM users WHERE id=?',(uid,)).fetchone():
            c.execute('INSERT INTO users(id) VALUES(?)',(uid,))
            c.executemany('INSERT INTO projects(user_id,name,budget_hours) VALUES(?,?,?)',[(uid,n,h) for n,h in DEFAULTS])
    def project(self,c,uid,pid):
        p=c.execute('SELECT * FROM projects WHERE id=? AND user_id=?',(pid,uid)).fetchone()
        if not p: raise ValueError('Project not found')
        return p
    def state(self,uid,week=None):
        with self.db() as c:
            self.ensure(uid,c)
            zone=c.execute('SELECT timezone FROM users WHERE id=?',(uid,)).fetchone()[0]
            w,start,end=week_bounds(zone,week)
            projects=[dict(r) for r in c.execute('SELECT id,name,budget_hours FROM projects WHERE user_id=?',(uid,))]
            logs=[dict(r) for r in c.execute('SELECT * FROM logs WHERE user_id=? AND started_at<? AND (ended_at>? OR ended_at IS NULL) ORDER BY started_at DESC',(uid,end,start))]
            for p in projects:
                c.execute('INSERT OR IGNORE INTO budgets VALUES(?,?,?,?)',(uid,p['id'],w,p['budget_hours']))
                p['budget_hours']=c.execute('SELECT hours FROM budgets WHERE user_id=? AND project_id=? AND week=?',(uid,p['id'],w)).fetchone()[0]
                p['actual_hours']=sum(max(0,min(r['ended_at'],end)-max(r['started_at'],start))/3600 for r in logs if r['project_id']==p['id'] and r['ended_at'] is not None)
            timer=c.execute('SELECT * FROM logs WHERE user_id=? AND ended_at IS NULL',(uid,)).fetchone()
            reminders=[dict(r) for r in c.execute('SELECT * FROM reminders WHERE user_id=? ORDER BY due_at DESC LIMIT 60',(uid,))]
            return dict(timezone=zone,week=w,projects=projects,logs=logs,timer=dict(timer) if timer else None,reminders=reminders,total_budget=sum(p['budget_hours'] for p in projects),total_actual=sum(p['actual_hours'] for p in projects))
    def mutate(self,uid,route,d,now=None):
        now=time.time() if now is None else now
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE'); self.ensure(uid,c)
            if route=='settings':
                zone=str(d['timezone']); ZoneInfo(zone)
                c.execute('UPDATE users SET timezone=? WHERE id=?',(zone,uid))
            elif route=='projects':
                p=self.project(c,uid,d['id']); name=str(d.get('name',p['name'])).strip()[:80]
                if not name: raise ValueError('Project name cannot be empty')
                hours=number(d['budget_hours'],0,168)
                zone=c.execute('SELECT timezone FROM users WHERE id=?',(uid,)).fetchone()[0]
                w,_,_=week_bounds(zone,d.get('week'))
                c.execute('UPDATE projects SET name=?,budget_hours=? WHERE id=?',(name,hours,p['id']))
                c.execute('INSERT OR REPLACE INTO budgets VALUES(?,?,?,?)',(uid,p['id'],w,hours))
            elif route=='timer/start':
                p=self.project(c,uid,d['project_id'])
                existing=c.execute('SELECT * FROM logs WHERE user_id=? AND ended_at IS NULL',(uid,)).fetchone()
                if existing:
                    if existing['project_id']!=p['id']: raise ValueError('Stop the current timer first')
                    return dict(existing)
                lid=str(uuid.uuid4())
                c.execute('INSERT INTO logs(id,user_id,project_id,started_at) VALUES(?,?,?,?)',(lid,uid,p['id'],now))
                return {'id':lid}
            elif route=='timer/stop':
                row=c.execute('SELECT * FROM logs WHERE id=? AND user_id=?',(d['timer_id'],uid)).fetchone()
                if not row: raise ValueError('Timer not found')
                if row['ended_at'] is None:
                    c.execute('UPDATE logs SET ended_at=?,accomplishments=?,blockers=?,next_steps=? WHERE id=?',(max(now,row['started_at']),*self.notes(d),row['id']))
            elif route=='logs':
                p=self.project(c,uid,d['project_id']); rid=str(d['request_id'])
                uuid.UUID(rid)
                old=c.execute('SELECT id FROM logs WHERE user_id=? AND request_id=?',(uid,rid)).fetchone()
                if old: return {'id':old[0]}
                start=number(d['started_at'],0,now); duration=number(d['minutes'],1,1440)*60; end=start+duration
                if end>now+1: raise ValueError('Cannot record time in the future')
                if c.execute('SELECT 1 FROM logs WHERE user_id=? AND started_at<? AND (ended_at>? OR ended_at IS NULL)',(uid,end,start)).fetchone(): raise ValueError('This time overlaps an existing entry or active timer')
                lid=str(uuid.uuid4())
                c.execute('INSERT INTO logs VALUES(?,?,?,?,?,?,?,?,?)',(lid,uid,p['id'],start,end,*self.notes(d),rid))
                return {'id':lid}
            elif route=='reminders':
                p=self.project(c,uid,d['project_id']); due=number(d['due_at'],now-60,now+366*86400)
                label=str(d.get('label','Make a little time for yourself')).strip()[:200] or 'Make a little time for yourself'
                # A rapid repeated submit for the same schedule is one reminder.
                old=c.execute("SELECT id FROM reminders WHERE user_id=? AND project_id=? AND due_at=? AND label=? AND status='pending'",(uid,p['id'],due,label)).fetchone()
                if old: return {'id':old[0]}
                rid=str(uuid.uuid4()); c.execute('INSERT INTO reminders(id,user_id,project_id,label,due_at,created_at) VALUES(?,?,?,?,?,?)',(rid,uid,p['id'],label,due,now)); return {'id':rid}
            elif route=='reminders/action':
                r=c.execute('SELECT * FROM reminders WHERE id=? AND user_id=?',(d['id'],uid)).fetchone()
                if not r: raise ValueError('Reminder not found')
                if r['status']=='delivering': raise ValueError('This reminder is being delivered. Please try again shortly.')
                if d['action']=='skip': c.execute("UPDATE reminders SET status='skipped' WHERE id=?",(r['id'],))
                elif d['action']=='snooze':
                    if r['status'] in ('skipped','expired'): raise ValueError('This reminder has ended')
                    due=now+number(d.get('minutes',15),1,1440)*60
                    c.execute("UPDATE reminders SET status='pending',due_at=?,attempts=0,next_try=0,last_error='' WHERE id=?",(due,r['id']))
                else: raise ValueError('Unknown action')
            else: raise ValueError('Unknown action')
            return {'ok':True}
    @staticmethod
    def notes(d): return tuple(str(d.get(k,''))[:2000] for k in ('accomplishments','blockers','next_steps'))
