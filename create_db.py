# create_db.py
import sqlite3
from werkzeug.security import generate_password_hash

conn = sqlite3.connect('payroll.db')
c = conn.cursor()

# employees table
c.execute('''
CREATE TABLE IF NOT EXISTS employees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT,
    designation TEXT,
    salary REAL NOT NULL,
    bank_account TEXT,
    joining_date TEXT
)
''')

# attendance table: one row per day per employee
c.execute('''
CREATE TABLE IF NOT EXISTS attendance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER,
    date TEXT,
    present INTEGER, -- 1 or 0
    hours_worked REAL DEFAULT 0,
    remarks TEXT,
    FOREIGN KEY(employee_id) REFERENCES employees(id)
)
''')

# payslips log (optional)
c.execute('''
CREATE TABLE IF NOT EXISTS payslips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER,
    month TEXT, -- e.g. "2025-09"
    gross REAL,
    deductions REAL,
    net REAL,
    generated_at TEXT,
    FOREIGN KEY(employee_id) REFERENCES employees(id)
)
''')

# users (for simple admin)
c.execute('''
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE,
    password_hash TEXT
)
''')

# create default admin user (username: admin, password: admin123) - change after first login
try:
    pw_hash = generate_password_hash("admin123")
    c.execute("INSERT OR IGNORE INTO users (username, password_hash) VALUES (?, ?)", ("admin", pw_hash))
except Exception as e:
    print("User create error:", e)

conn.commit()
conn.close()
print("Database created/checked: payroll.db. Default admin/admin123 (change password!).")
