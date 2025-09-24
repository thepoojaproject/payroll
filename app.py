# app.py
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, session
import sqlite3, io, datetime, csv
from werkzeug.security import check_password_hash, generate_password_hash
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

app = Flask(__name__)
app.secret_key = 'replace_this_with_a_random_secret'

DB = 'payroll.db'

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

# ---- Auth ----
@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        conn.close()
        if user and check_password_hash(user['password_hash'], password):
            session['user'] = username
            return redirect(url_for('index'))
        flash("Invalid credentials", "danger")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

def admin_required(func):
    from functools import wraps
    @wraps(func)
    def wrapper(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        return func(*args, **kwargs)
    return wrapper

# ---- Dashboard / Employees ----
@app.route('/')
@admin_required
def index():
    conn = get_db()
    employees = conn.execute("SELECT * FROM employees").fetchall()
    conn.close()
    return render_template('index.html', employees=employees)

@app.route('/employee/add', methods=['GET','POST'])
@admin_required
def add_employee():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form.get('email','')
        designation = request.form.get('designation','')
        salary = float(request.form.get('salary',0))
        bank_account = request.form.get('bank_account','')
        joining_date = request.form.get('joining_date','')
        conn = get_db()
        conn.execute("INSERT INTO employees (name,email,designation,salary,bank_account,joining_date) VALUES (?,?,?,?,?,?)",
                     (name,email,designation,salary,bank_account,joining_date))
        conn.commit()
        conn.close()
        flash("Employee added", "success")
        return redirect(url_for('index'))
    return render_template('add_employee.html')

@app.route('/employee/edit/<int:id>', methods=['GET','POST'])
@admin_required
def edit_employee(id):
    conn = get_db()
    emp = conn.execute("SELECT * FROM employees WHERE id=?", (id,)).fetchone()
    if not emp:
        conn.close()
        flash("Employee not found", "danger")
        return redirect(url_for('index'))
    if request.method == 'POST':
        conn.execute("UPDATE employees SET name=?, email=?, designation=?, salary=?, bank_account=?, joining_date=? WHERE id=?",
                     (request.form['name'], request.form.get('email',''), request.form.get('designation',''),
                      float(request.form.get('salary',0)), request.form.get('bank_account',''), request.form.get('joining_date',''), id))
        conn.commit()
        conn.close()
        flash("Updated", "success")
        return redirect(url_for('index'))
    conn.close()
    return render_template('edit_employee.html', emp=emp)

@app.route('/employee/delete/<int:id>', methods=['POST'])
@admin_required
def delete_employee(id):
    conn = get_db()
    conn.execute("DELETE FROM employees WHERE id=?", (id,))
    conn.execute("DELETE FROM attendance WHERE employee_id=?", (id,))
    conn.commit()
    conn.close()
    flash("Deleted", "success")
    return redirect(url_for('index'))

# ---- Attendance ----
@app.route('/attendance/<int:emp_id>', methods=['GET','POST'])
@admin_required
def attendance(emp_id):
    conn = get_db()
    emp = conn.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone()
    if not emp:
        conn.close()
        flash("Employee not found", "danger")
        return redirect(url_for('index'))

    if request.method == 'POST':
        date = request.form['date']
        present = 1 if request.form.get('present')=='on' else 0
        hours = float(request.form.get('hours_worked', 0))
        remarks = request.form.get('remarks','')
        conn.execute("INSERT INTO attendance (employee_id, date, present, hours_worked, remarks) VALUES (?,?,?,?,?)",
                     (emp_id, date, present, hours, remarks))
        conn.commit()
        flash("Attendance recorded", "success")

    records = conn.execute("SELECT * FROM attendance WHERE employee_id=? ORDER BY date DESC LIMIT 50", (emp_id,)).fetchall()
    conn.close()
    return render_template('attendance.html', emp=emp, records=records)

# ---- Salary calculation & payslip (PDF) ----
def calculate_pay(salary, days_present=0, total_days=30, overtime_hours=0, bonus=0.0):
    # Basic approach:
    # monthly basic = salary
    # pro-rate by attendance (if needed). For simplicity we use full salary if full month present or pro-rate by days.
    daily_rate = salary / total_days
    gross = daily_rate * days_present + bonus + (overtime_hours * (daily_rate/8))  # simple overtime
    # Deductions: PF (employee 12% of basic), tax (flat 10% on gross)
    pf = gross * 0.12
    tax = gross * 0.10
    deductions = pf + tax
    net = gross - deductions
    return {
        'gross': round(gross,2),
        'pf': round(pf,2),
        'tax': round(tax,2),
        'deductions': round(deductions,2),
        'net': round(net,2)
    }

@app.route('/payslip/<int:emp_id>', methods=['GET','POST'])
@admin_required
def payslip(emp_id):
    conn = get_db()
    emp = conn.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone()
    if not emp:
        conn.close()
        flash("Employee not found", "danger")
        return redirect(url_for('index'))

    if request.method == 'POST':
        # Inputs
        month = request.form.get('month') # e.g. 2025-09
        total_days = int(request.form.get('total_days', 30))
        days_present = int(request.form.get('days_present', total_days))
        overtime_hours = float(request.form.get('overtime_hours', 0))
        bonus = float(request.form.get('bonus', 0))
        calc = calculate_pay(emp['salary'], days_present, total_days, overtime_hours, bonus)
        # store payslip log
        conn.execute("INSERT INTO payslips (employee_id, month, gross, deductions, net, generated_at) VALUES (?,?,?,?,?,?)",
                     (emp_id, month, calc['gross'], calc['deductions'], calc['net'], datetime.datetime.now().isoformat()))
        conn.commit()
        conn.close()
        # generate PDF and send
        buffer = io.BytesIO()
        c = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4
        c.setFont("Helvetica-Bold", 16)
        c.drawString(40, height-60, "Payslip")
        c.setFont("Helvetica", 11)
        c.drawString(40, height-90, f"Employee: {emp['name']} (ID: {emp['id']})")
        c.drawString(40, height-110, f"Designation: {emp['designation']}")
        c.drawString(40, height-130, f"Month: {month}")
        y = height-170
        c.drawString(40, y, f"Basic/Salary: {emp['salary']:.2f}")
        y -= 20
        c.drawString(40, y, f"Days Present: {days_present}/{total_days}")
        y -= 20
        c.drawString(40, y, f"Overtime Hours: {overtime_hours}")
        y -= 20
        c.drawString(40, y, f"Bonus: {bonus:.2f}")
        y -= 30
        c.drawString(40, y, f"Gross Pay: {calc['gross']:.2f}")
        y -= 20
        c.drawString(40, y, f"Provident Fund (12%): {calc['pf']:.2f}")
        y -= 20
        c.drawString(40, y, f"Tax (10%): {calc['tax']:.2f}")
        y -= 20
        c.drawString(40, y, f"Total Deductions: {calc['deductions']:.2f}")
        y -= 25
        c.setFont("Helvetica-Bold", 12)
        c.drawString(40, y, f"Net Pay: {calc['net']:.2f}")
        c.showPage()
        c.save()
        buffer.seek(0)
        return send_file(buffer, as_attachment=True, download_name=f"payslip_{emp['id']}_{month}.pdf", mimetype='application/pdf')

    conn.close()
    # default month to current year-month
    default_month = datetime.date.today().strftime("%Y-%m")
    return render_template('payslip_form.html', emp=emp, default_month=default_month)

# ---- Reports (CSV) ----
@app.route('/report/attendance/<int:emp_id>')
@admin_required
def export_attendance(emp_id):
    conn = get_db()
    emp = conn.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone()
    rows = conn.execute("SELECT date, present, hours_worked, remarks FROM attendance WHERE employee_id=? ORDER BY date", (emp_id,)).fetchall()
    conn.close()
    si = io.StringIO()
    writer = csv.writer(si)
    writer.writerow(['employee_id', 'employee_name', 'date', 'present', 'hours_worked', 'remarks'])
    for r in rows:
        writer.writerow([emp_id, emp['name'], r['date'], r['present'], r['hours_worked'], r['remarks']])
    output = io.BytesIO()
    output.write(si.getvalue().encode('utf-8'))
    output.seek(0)
    return send_file(output, as_attachment=True, download_name=f"attendance_{emp_id}.csv", mimetype='text/csv')

# ---- Password change (admin) ----
@app.route('/change_password', methods=['GET','POST'])
@admin_required
def change_password():
    if request.method == 'POST':
        new_pw = request.form['new_password']
        conn = get_db()
        conn.execute("UPDATE users SET password_hash=? WHERE username=?", (generate_password_hash(new_pw), session['user']))
        conn.commit()
        conn.close()
        flash("Password changed", "success")
        return redirect(url_for('index'))
    return render_template('change_password.html')

if __name__ == '__main__':
    app.run(debug=True)
