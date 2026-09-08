"""Idempotent legacy import: original files remain untouched."""
import csv
import hashlib
import logging
from pathlib import Path
from .db import ROOT, connect, initialize

log = logging.getLogger(__name__)

def import_legacy(base=None):
    initialize()
    base = Path(base or ROOT / 'dataset' / 'college_faces')
    counts = {'students': 0, 'attendance': 0, 'skipped': 0}
    with connect() as db:
        for path in sorted(base.glob('*/*/students.csv')):
            dept, section = path.parts[-3:-1]
            db.execute('INSERT OR IGNORE INTO departments(name) VALUES (?)', (dept,))
            db.execute('INSERT OR IGNORE INTO sections(name) VALUES (?)', (section,))
            did = db.execute('SELECT id FROM departments WHERE name=?',(dept,)).fetchone()[0]
            sid = db.execute('SELECT id FROM sections WHERE name=?',(section,)).fetchone()[0]
            with path.open(encoding='utf-8-sig',newline='') as handle:
                for row in csv.DictReader(handle):
                    roll = str(row.get('roll_number','')).strip()
                    if not roll or not row.get('name'):
                        counts['skipped'] += 1; continue
                    before = db.total_changes
                    try:
                        semester = int(row.get('semester') or 1)
                    except (TypeError, ValueError):
                        semester = 1
                    semester = min(12, max(1, semester))
                    db.execute('INSERT OR IGNORE INTO students(roll,name,department_id,section_id,semester,email) VALUES (?,?,?,?,?,?)',
                               (roll,row['name'],did,sid,semester,row.get('email','') or ''))
                    if row.get('semester'):
                        db.execute(
                            'UPDATE students SET semester=? WHERE roll=? AND department_id=? AND section_id=?',
                            (semester,roll,did,sid),
                        )
                    counts['students'] += db.total_changes-before
                    student = db.execute('SELECT id FROM students WHERE roll=? AND department_id=? AND section_id=?',(roll,did,sid)).fetchone()[0]
                    model = path.parent / 'trainer.yml'
                    if model.exists() and roll.isdigit():
                        db.execute("INSERT OR IGNORE INTO face_profiles(student_id,provider,model_path,label) VALUES (?,?,?,?)",
                                   (student,'lbph',str(model.resolve()),int(roll)))
        for path in sorted((base/'reports').glob('*_attendance.csv')):
            dept = path.name.split('_')[0]
            with path.open(encoding='utf-8-sig',newline='') as handle:
                for row in csv.DictReader(handle):
                    digest = str(path.resolve()) + ':' + hashlib.sha256(repr(sorted(row.items())).encode()).hexdigest()
                    if db.execute('SELECT 1 FROM imports WHERE source=?',(digest,)).fetchone(): continue
                    student = db.execute('SELECT s.* FROM students s JOIN departments d ON d.id=s.department_id JOIN sections c ON c.id=s.section_id WHERE s.roll=? AND d.name=? AND c.name=?',
                                         (str(row.get('roll_number','')),dept,row.get('section',''))).fetchone()
                    if student is None:
                        counts['skipped'] += 1; continue
                    status = row.get('status','').upper()
                    if status not in ('PRESENT','LATE','ABSENT','INCOMPLETE','EXCUSED'):
                        counts['skipped'] += 1; continue
                    db.execute("INSERT OR IGNORE INTO class_sessions(date,period,department_id,section_id,finalized,source) VALUES (?,?,?,?,1,'legacy')",
                               (row['date'],row['period'],student['department_id'],student['section_id']))
                    session = db.execute('SELECT id FROM class_sessions WHERE date=? AND period=? AND department_id=? AND section_id=?',
                                         (row['date'],row['period'],student['department_id'],student['section_id'])).fetchone()[0]
                    before = db.total_changes
                    db.execute("INSERT OR IGNORE INTO attendance(session_id,student_id,first_seen,last_seen,status,source) VALUES (?,?,?,?,?,'legacy')",
                               (session,student['id'],row.get('sign_in_time'),row.get('sign_in_time'),status))
                    counts['attendance'] += db.total_changes-before
                    db.execute('INSERT INTO imports(source) VALUES (?)',(digest,))
    return counts

if __name__ == '__main__':
    print(import_legacy())
