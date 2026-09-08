import hashlib
import hmac
import secrets
import time
import re
from smart_attendance.database.db import connect

class AccessDenied(PermissionError):
    pass

def hash_password(password):
    if len(password) < 12 or len(password) > 256:
        raise ValueError('Use a password between 12 and 256 characters.')
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),600000).hex()
    return f'pbkdf2_sha256$600000${salt}${digest}'

def verify_password(password, encoded):
    try:
        algorithm, rounds, salt, expected = encoded.split('$')
        actual = hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),int(rounds)).hex()
        return algorithm == 'pbkdf2_sha256' and hmac.compare_digest(actual,expected)
    except (ValueError,TypeError):
        return False

def audit(db, actor, action, target='', metadata=None):
    import json
    safe = {k:v for k,v in (metadata or {}).items() if not any(word in k.lower() for word in ('password','secret','token','embedding','credential'))}
    db.execute('INSERT INTO audit_logs(user_id,role,action,target,metadata) VALUES (?,?,?,?,?)',
               (actor['id'] if actor else None,actor['role'] if actor else None,action,str(target),json.dumps(safe)))

def setup_admin(username,password):
    if not re.fullmatch(r'[A-Za-z0-9_.@-]{3,80}',username): raise ValueError('Use a valid username (3–80 characters).')
    hashed = hash_password(password)
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT 1 FROM users LIMIT 1').fetchone(): raise AccessDenied('Initial setup is already complete.')
        db.execute("INSERT INTO users(username,password_hash,role) VALUES (?,?,'ADMIN')",(username,hashed))
        audit(db,None,'ADMIN INITIALIZED')

def has_users():
    with connect() as db:
        return bool(db.execute('SELECT 1 FROM users LIMIT 1').fetchone())

def login(username,password):
    now=time.time(); token=None
    with connect() as db:
        attempts=db.execute('SELECT * FROM login_attempts WHERE username=?',(username,)).fetchone()
        if attempts and attempts['blocked_until']>now: raise AccessDenied('Too many attempts. Try again in 15 minutes.')
        user=db.execute('SELECT * FROM users WHERE username=? AND active=1',(username,)).fetchone()
        if not user or not verify_password(password,user['password_hash']):
            failures=(attempts['failures'] if attempts else 0)+1
            db.execute('INSERT INTO login_attempts(username,failures,blocked_until) VALUES (?,?,?) ON CONFLICT(username) DO UPDATE SET failures=excluded.failures,blocked_until=excluded.blocked_until',
                       (username,failures,now+900 if failures>=5 else 0))
            audit(db,None,'FAILED LOGIN')
        else:
            token=secrets.token_urlsafe(32)
            db.execute('INSERT INTO auth_sessions VALUES (?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),user['id'],now+8*3600))
            db.execute('DELETE FROM login_attempts WHERE username=?',(username,))
            audit(db,user,'LOGIN')
    if token is None: raise AccessDenied('Invalid username or password.')
    return token

def actor(db,token,roles=None):
    if not token: raise AccessDenied('Please sign in.')
    user=db.execute('SELECT u.* FROM users u JOIN auth_sessions a ON a.user_id=u.id WHERE a.token_hash=? AND a.expires_at>? AND u.active=1',
                    (hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()
    if user is None: raise AccessDenied('Session expired. Please sign in again.')
    if roles and user['role'] not in roles: raise AccessDenied('Your role cannot perform this operation.')
    return user

def current_user(token):
    with connect() as db:
        u=actor(db,token)
        return {k:u[k] for k in ('id','username','role','department_id','student_id')}

def logout(token):
    with connect() as db:
        try:
            user=actor(db,token) if token else None
        except AccessDenied:
            user=None
        if user:
            audit(db,user,'LOGOUT')
        db.execute('DELETE FROM auth_sessions WHERE token_hash=?',(hashlib.sha256(token.encode()).hexdigest(),))

def student_scope(db,u,student_id):
    student=db.execute('SELECT * FROM students WHERE id=?',(student_id,)).fetchone()
    if student is None: raise ValueError('Student not found.')
    if u['role']=='ADMIN': return student
    if u['role']=='STUDENT' and u['student_id']==student_id: return student
    if u['role']=='HOD' and u['department_id']==student['department_id']: return student
    if u['role']=='FACULTY' and db.execute('SELECT 1 FROM timetables t JOIN faculty f ON f.id=t.faculty_id WHERE f.user_id=? AND t.department_id=? AND t.section_id=? AND t.semester=? AND t.active=1',
        (u['id'],student['department_id'],student['section_id'],student['semester'])).fetchone(): return student
    raise AccessDenied('This student is outside your access scope.')

def session_scope(db,u,session_id):
    row=db.execute('SELECT * FROM class_sessions WHERE id=?',(session_id,)).fetchone()
    if row is None: raise ValueError('Class session not found.')
    if u['role']=='ADMIN': return row
    if u['role']=='HOD' and row['department_id']==u['department_id']: return row
    if u['role']=='FACULTY' and db.execute('SELECT 1 FROM faculty WHERE id=? AND user_id=?',(row['faculty_id'],u['id'])).fetchone(): return row
    raise AccessDenied('This class is outside your access scope.')
