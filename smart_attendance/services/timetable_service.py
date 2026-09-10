from datetime import datetime,date,timedelta,time
from smart_attendance.database.db import connect
from smart_attendance.utils.security import actor,audit
from smart_attendance.utils.time_utils import system_now


def list_timetable(token):
    with connect() as db:
        u=actor(db,token)
        sql='''SELECT t.*,d.name department,c.name section,s.name subject,s.code subject_code,f.name faculty
        FROM timetables t JOIN departments d ON d.id=t.department_id JOIN sections c ON c.id=t.section_id
        JOIN subjects s ON s.id=t.subject_id JOIN faculty f ON f.id=t.faculty_id WHERE t.active=1'''
        args=[]
        if u['role']=='HOD': sql+=' AND t.department_id=?'; args=[u['department_id']]
        elif u['role']=='FACULTY': sql+=' AND f.user_id=?'; args=[u['id']]
        elif u['role']=='STUDENT':
            sql+=' AND EXISTS(SELECT 1 FROM students st WHERE st.id=? AND st.department_id=t.department_id AND st.section_id=t.section_id AND st.semester=t.semester)'; args=[u['student_id']]
        return [dict(r) for r in db.execute(sql,args)]


def save_timetable(token,department_id,section_id,semester,subject_id,faculty_id,weekday,start_time,end_time,classroom,period,valid_from,valid_to):
    start=time.fromisoformat(start_time); end=time.fromisoformat(end_time)
    if start>=end: raise ValueError('Class end must be after its start.')
    if not 0<=int(weekday)<=6 or not 1<=int(semester)<=12: raise ValueError('Invalid day or semester.')
    if date.fromisoformat(valid_from)>date.fromisoformat(valid_to): raise ValueError('Invalid effective date range.')
    if not period.strip(): raise ValueError('Period is required.')
    with connect() as db:
        u=actor(db,token,['ADMIN'])
        overlap=db.execute('''SELECT 1 FROM timetables WHERE active=1 AND weekday=? AND valid_from<=? AND valid_to>=?
            AND start_time<? AND end_time>? AND ((department_id=? AND section_id=? AND semester=?) OR faculty_id=?)''',
            (weekday,valid_to,valid_from,end_time,start_time,department_id,section_id,semester,faculty_id)).fetchone()
        if overlap: raise ValueError('This time overlaps an existing class or faculty assignment.')
        db.execute('''INSERT INTO timetables(department_id,section_id,semester,subject_id,faculty_id,weekday,start_time,end_time,classroom,period,valid_from,valid_to)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',(department_id,section_id,semester,subject_id,faculty_id,weekday,start_time,end_time,classroom,period,valid_from,valid_to))
        audit(db,u,'TIMETABLE MODIFIED',period)


def deactivate(token,timetable_id):
    with connect() as db:
        u=actor(db,token,['ADMIN']); db.execute('UPDATE timetables SET active=0 WHERE id=?',(timetable_id,)); audit(db,u,'TIMETABLE MODIFIED',timetable_id)


def materialize(db,day):
    """Snapshot the eligible roster. Never invent historical enrolment from CSVs."""
    daystr=day.isoformat()
    for t in db.execute('SELECT * FROM timetables WHERE active=1 AND weekday=? AND valid_from<=? AND valid_to>=?',(day.weekday(),daystr,daystr)).fetchall():
        db.execute('''INSERT OR IGNORE INTO class_sessions(timetable_id,date,period,department_id,section_id,subject_id,faculty_id,semester,starts_at,ends_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)''',(t['id'],daystr,t['period'],t['department_id'],t['section_id'],t['subject_id'],t['faculty_id'],t['semester'],daystr+'T'+t['start_time'],daystr+'T'+t['end_time']))
        session=db.execute('SELECT * FROM class_sessions WHERE date=? AND period=? AND department_id=? AND section_id=?',
            (daystr,t['period'],t['department_id'],t['section_id'])).fetchone()
        if session['finalized'] or session['source']=='legacy': continue
        for student in db.execute('SELECT id FROM students WHERE active=1 AND department_id=? AND section_id=? AND semester=? AND substr(enrolled_at,1,10)<=?',
                                 (t['department_id'],t['section_id'],t['semester'],daystr)).fetchall():
            db.execute("INSERT OR IGNORE INTO attendance(session_id,student_id,status) VALUES (?,?,'INCOMPLETE')",(session['id'],student['id']))


def current_classes(token,now=None):
    now=now or system_now()
    tables=list_timetable(token)
    return [t for t in tables if t['weekday']==now.weekday() and t['valid_from']<=now.date().isoformat()<=t['valid_to'] and t['start_time']<=now.time().isoformat()<t['end_time']]
