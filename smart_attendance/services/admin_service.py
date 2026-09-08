import json
import re
from smart_attendance.database.db import connect
from smart_attendance.utils.security import actor, audit, student_scope, hash_password

DEFAULTS={'institution':'SmartAttend AI','late_minutes':10,'minimum_percentage':75.,'good_percentage':85.,'presence_ratio':.75,'observation_gap_seconds':90,'lbph_distance':55.,'embedding_similarity':.45,'liveness_required':True,'camera_index':0,'email_enabled':False}

def settings(token):
    with connect() as db:
        actor(db,token)
        return DEFAULTS | {r['key']:json.loads(r['value']) for r in db.execute('SELECT * FROM settings')}

def save_settings(token,values):
    clean=DEFAULTS|values
    limits={'late_minutes':(0,60),'minimum_percentage':(1,100),'good_percentage':(1,100),'presence_ratio':(.1,1),'observation_gap_seconds':(1,300),'lbph_distance':(1,100),'embedding_similarity':(.1,1),'camera_index':(0,5)}
    for key,(low,high) in limits.items():
        if not low<=float(clean[key])<=high: raise ValueError(f'Invalid {key}.')
    if clean['good_percentage']<clean['minimum_percentage']: raise ValueError('Good threshold must exceed the minimum.')
    if not 1<=len(clean['institution'])<=120: raise ValueError('Institution name is required (maximum 120 characters).')
    with connect() as db:
        u=actor(db,token,['ADMIN'])
        for key in DEFAULTS:
            db.execute('INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,json.dumps(clean[key])))
        audit(db,u,'SETTINGS CHANGED')

def catalogue(token):
    with connect() as db:
        u=actor(db,token)
        result={name:[dict(r) for r in db.execute('SELECT * FROM '+name)] for name in ('departments','sections','subjects')}
        if u['role']=='ADMIN':
            result['faculty']=[dict(r) for r in db.execute('SELECT * FROM faculty')]
            result['users']=[dict(r) for r in db.execute('SELECT id,username,role,department_id,student_id,active FROM users')]
        else:
            result['faculty']=[]; result['users']=[]
        return result

def students(token):
    with connect() as db:
        u=actor(db,token)
        query='SELECT s.*,d.name department,c.name section FROM students s JOIN departments d ON d.id=s.department_id JOIN sections c ON c.id=s.section_id'
        params=[]
        if u['role']=='STUDENT': query+=' WHERE s.id=?'; params=[u['student_id']]
        elif u['role']=='HOD': query+=' WHERE s.department_id=?'; params=[u['department_id']]
        elif u['role']=='FACULTY':
            query+=' WHERE EXISTS(SELECT 1 FROM timetables t JOIN faculty f ON f.id=t.faculty_id WHERE t.department_id=s.department_id AND t.section_id=s.section_id AND t.semester=s.semester AND t.active=1 AND f.user_id=?)'; params=[u['id']]
        return [dict(r) for r in db.execute(query,params)]

def save_student(token,roll,name,department_id,section_id,semester=1,email='',student_id=None,active=True):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,32}',roll): raise ValueError('Roll number must use letters, numbers, underscores or hyphens (maximum 32).')
    if not name.strip() or len(name)>100: raise ValueError('Student name is required (maximum 100 characters).')
    if not 1<=int(semester)<=12: raise ValueError('Semester must be from 1 to 12.')
    if email and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email): raise ValueError('Invalid email address.')
    with connect() as db:
        u=actor(db,token,['ADMIN'])
        created=student_id is None
        if student_id:
            db.execute('UPDATE students SET roll=?,name=?,department_id=?,section_id=?,semester=?,email=?,active=? WHERE id=?',
                       (roll,name.strip(),department_id,section_id,int(semester),email,int(active),student_id))
        else:
            student_id=db.execute('INSERT INTO students(roll,name,department_id,section_id,semester,email) VALUES (?,?,?,?,?,?)',
                       (roll,name.strip(),department_id,section_id,int(semester),email)).lastrowid
        audit(db,u,'STUDENT CREATED' if created else 'STUDENT UPDATED',student_id)
        return student_id

def create_user(token,username,password,role,department_id=None,student_id=None,faculty_id=None):
    if not re.fullmatch(r'[A-Za-z0-9_.@-]{3,80}',username): raise ValueError('Invalid username.')
    if role not in ('ADMIN','FACULTY','HOD','STUDENT'): raise ValueError('Invalid role.')
    if role in ('FACULTY','HOD') and not department_id: raise ValueError('Department is required.')
    if role=='STUDENT' and not student_id: raise ValueError('Link a registered student.')
    hashed=hash_password(password)
    with connect() as db:
        u=actor(db,token,['ADMIN'])
        uid=db.execute('INSERT INTO users(username,password_hash,role,department_id,student_id) VALUES (?,?,?,?,?)',
                       (username,hashed,role,department_id,student_id if role=='STUDENT' else None)).lastrowid
        if role=='FACULTY':
            if faculty_id:
                linked=db.execute('SELECT * FROM faculty WHERE id=? AND department_id=?',(faculty_id,department_id)).fetchone()
                if not linked or linked['user_id'] is not None: raise ValueError('Select an unlinked faculty profile in this department.')
                db.execute('UPDATE faculty SET user_id=? WHERE id=?',(uid,faculty_id))
            else:
                db.execute('INSERT INTO faculty(user_id,name,department_id) VALUES (?,?,?)',(uid,username,department_id))
        audit(db,u,'USER CREATED',uid,{'role':role})

def add_catalogue(token,kind,name,code=''):
    if not name.strip(): raise ValueError('Name is required.')
    with connect() as db:
        u=actor(db,token,['ADMIN'])
        if kind=='subjects': db.execute('INSERT INTO subjects(code,name) VALUES (?,?)',(code.strip(),name.strip()))
        elif kind in ('departments','sections'): db.execute('INSERT INTO '+kind+'(name) VALUES (?)',(name.strip(),))
        else: raise ValueError('Invalid catalogue.')
        audit(db,u,'CATALOGUE CREATED',kind)
