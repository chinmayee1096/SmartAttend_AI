CREATE TABLE IF NOT EXISTS departments(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS sections(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS students(
 id INTEGER PRIMARY KEY, roll TEXT NOT NULL, name TEXT NOT NULL,
 department_id INTEGER NOT NULL REFERENCES departments(id), section_id INTEGER NOT NULL REFERENCES sections(id),
 semester INTEGER NOT NULL DEFAULT 1, email TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1,
 enrolled_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(roll,department_id,section_id));
CREATE TABLE IF NOT EXISTS users(
 id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
 role TEXT NOT NULL CHECK(role IN ('ADMIN','FACULTY','HOD','STUDENT')),
 department_id INTEGER REFERENCES departments(id), student_id INTEGER UNIQUE REFERENCES students(id),
 active INTEGER NOT NULL DEFAULT 1, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS auth_sessions(token_hash TEXT PRIMARY KEY, user_id INTEGER REFERENCES users(id), expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS login_attempts(username TEXT PRIMARY KEY, failures INTEGER DEFAULT 0, blocked_until REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS faculty(id INTEGER PRIMARY KEY, user_id INTEGER UNIQUE REFERENCES users(id), name TEXT NOT NULL, department_id INTEGER REFERENCES departments(id));
CREATE TABLE IF NOT EXISTS subjects(id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS timetables(
 id INTEGER PRIMARY KEY, department_id INTEGER NOT NULL REFERENCES departments(id), section_id INTEGER NOT NULL REFERENCES sections(id),
 semester INTEGER NOT NULL, subject_id INTEGER NOT NULL REFERENCES subjects(id), faculty_id INTEGER NOT NULL REFERENCES faculty(id),
 weekday INTEGER NOT NULL CHECK(weekday BETWEEN 0 AND 6), start_time TEXT NOT NULL, end_time TEXT NOT NULL,
 classroom TEXT NOT NULL DEFAULT '', period TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
 valid_from TEXT NOT NULL, valid_to TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS class_sessions(
 id INTEGER PRIMARY KEY, timetable_id INTEGER REFERENCES timetables(id), date TEXT NOT NULL, period TEXT NOT NULL,
 department_id INTEGER NOT NULL REFERENCES departments(id), section_id INTEGER NOT NULL REFERENCES sections(id),
 subject_id INTEGER REFERENCES subjects(id), faculty_id INTEGER REFERENCES faculty(id), semester INTEGER NOT NULL DEFAULT 1,
 starts_at TEXT, ends_at TEXT, finalized INTEGER NOT NULL DEFAULT 0, source TEXT NOT NULL DEFAULT 'scheduled',
 UNIQUE(date,department_id,section_id,period));
CREATE TABLE IF NOT EXISTS attendance(
 id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES class_sessions(id), student_id INTEGER NOT NULL REFERENCES students(id),
 first_seen TEXT, last_seen TEXT, presence_seconds REAL NOT NULL DEFAULT 0,
 status TEXT NOT NULL CHECK(status IN ('PRESENT','LATE','ABSENT','INCOMPLETE','EXCUSED')),
 confidence REAL, provider TEXT, liveness INTEGER NOT NULL DEFAULT 0, source TEXT NOT NULL DEFAULT 'scheduled',
 UNIQUE(session_id,student_id));
CREATE TABLE IF NOT EXISTS face_profiles(
 id INTEGER PRIMARY KEY, student_id INTEGER NOT NULL REFERENCES students(id), provider TEXT NOT NULL,
 encrypted_embedding BLOB, model_path TEXT, label INTEGER, updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(student_id,provider));
CREATE TABLE IF NOT EXISTS notifications(
 id INTEGER PRIMARY KEY, student_id INTEGER REFERENCES students(id), user_id INTEGER REFERENCES users(id),
 kind TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL, recipient TEXT NOT NULL DEFAULT '',
 state TEXT NOT NULL DEFAULT 'PENDING', created_at TEXT DEFAULT CURRENT_TIMESTAMP, sent_at TEXT,
 dedup_key TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS attendance_corrections(
 id INTEGER PRIMARY KEY, attendance_id INTEGER NOT NULL REFERENCES attendance(id), requester INTEGER NOT NULL REFERENCES users(id),
 original_status TEXT NOT NULL, requested_status TEXT NOT NULL, reason TEXT NOT NULL,
 reviewer INTEGER REFERENCES users(id), decision TEXT NOT NULL DEFAULT 'PENDING', review_reason TEXT,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP, reviewed_at TEXT);
CREATE TABLE IF NOT EXISTS audit_logs(
 id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), role TEXT, action TEXT NOT NULL,
 target TEXT, metadata TEXT NOT NULL DEFAULT '{}', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS imports(source TEXT PRIMARY KEY, imported_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS anomalies(
 id INTEGER PRIMARY KEY, student_id INTEGER REFERENCES students(id), session_id INTEGER REFERENCES class_sessions(id),
 kind TEXT NOT NULL, score REAL NOT NULL, description TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP, dedup_key TEXT UNIQUE);
CREATE INDEX IF NOT EXISTS attendance_student ON attendance(student_id,session_id);
