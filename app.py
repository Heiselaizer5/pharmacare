import sqlite3
import os
from datetime import datetime, timedelta
from functools import wraps
from flask import (Flask, request, jsonify, render_template,
                   redirect, url_for, session, flash, send_file)
from werkzeug.security import generate_password_hash, check_password_hash
from io import BytesIO

app = Flask(__name__)
app.secret_key = 'pharmacy-secret-key-2026'
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'database.db')


def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        if session.get('role') != 'admin':
            flash('Access denied. Admin only.', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated


def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        full_name TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'pharmacist',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS medicines (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        category TEXT,
        description TEXT,
        buying_price REAL NOT NULL,
        selling_price REAL NOT NULL,
        stock_qty INTEGER NOT NULL DEFAULT 0,
        expiry_date TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS sales (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        total_amount REAL NOT NULL,
        payment_method TEXT DEFAULT 'cash',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS sale_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sale_id INTEGER,
        medicine_id INTEGER,
        quantity INTEGER NOT NULL,
        unit_price REAL NOT NULL,
        subtotal REAL NOT NULL,
        FOREIGN KEY (sale_id) REFERENCES sales(id),
        FOREIGN KEY (medicine_id) REFERENCES medicines(id)
    )''')

    c.execute("SELECT COUNT(*) FROM users")
    if c.fetchone()[0] == 0:
        admin_pw = generate_password_hash('admin123')
        pharm_pw = generate_password_hash('pharm123')
        c.execute("INSERT INTO users (username, password, full_name, role) VALUES (?, ?, ?, ?)",
                  ('admin', admin_pw, 'System Administrator', 'admin'))
        c.execute("INSERT INTO users (username, password, full_name, role) VALUES (?, ?, ?, ?)",
                  ('pharmacist', pharm_pw, 'Pharmacy Staff', 'pharmacist'))

    c.execute("SELECT COUNT(*) FROM medicines")
    if c.fetchone()[0] == 0:
        meds = [
            ('Paracetamol 500mg', 'Painkiller', 'Pain and fever relief tablet', 500, 1000, 100, '2027-12-31'),
            ('Amoxicillin 500mg', 'Antibiotic', 'Broad-spectrum antibiotic capsule', 1500, 3000, 50, '2026-09-30'),
            ('Cetirizine 10mg', 'Antihistamine', 'Allergy relief tablet', 300, 800, 120, '2028-05-15'),
            ('Panadol Extra', 'Painkiller', 'Extra strength pain relief', 600, 1200, 80, '2027-06-20'),
            ('Azithromycin 250mg', 'Antibiotic', 'Macrolide antibiotic', 2000, 4500, 30, '2026-11-15'),
            ('Omeprazole 20mg', 'Antacid', 'Proton pump inhibitor for acid reflux', 800, 1500, 60, '2027-08-10'),
            ('Metformin 500mg', 'Antidiabetic', 'Blood sugar control tablet', 1200, 2500, 45, '2027-03-25'),
            ('Loratadine 10mg', 'Antihistamine', 'Non-drowsy allergy relief', 400, 900, 90, '2028-01-20'),
            ('Ibuprofen 400mg', 'Painkiller', 'Anti-inflammatory pain relief', 600, 1200, 75, '2027-10-05'),
            ('Vitamin C 1000mg', 'Supplement', 'Immune system booster', 300, 700, 150, '2028-06-30'),
            ('Cough Syrup 100ml', 'Cough Medicine', 'Relief for dry and productive cough', 1000, 2000, 40, '2027-04-18'),
            ('ORS Sachets', 'Hydration', 'Oral rehydration salts', 200, 500, 200, '2028-12-31'),
        ]
        c.executemany("INSERT INTO medicines (name, category, description, buying_price, selling_price, stock_qty, expiry_date) VALUES (?, ?, ?, ?, ?, ?, ?)", meds)

    conn.commit()
    conn.close()


init_db()


@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        conn.close()
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['full_name'] = user['full_name']
            session['role'] = user['role']
            return redirect(url_for('dashboard'))
        flash('Wrong username or password', 'error')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/')
@login_required
def dashboard():
    conn = get_db()
    today = datetime.now().strftime('%Y-%m-%d')
    week_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    month_ago = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')

    today_sales = conn.execute("SELECT COALESCE(SUM(total_amount),0) FROM sales WHERE DATE(created_at)=?", (today,)).fetchone()[0]
    week_sales = conn.execute("SELECT COALESCE(SUM(total_amount),0) FROM sales WHERE DATE(created_at)>=?", (week_ago,)).fetchone()[0]
    month_sales = conn.execute("SELECT COALESCE(SUM(total_amount),0) FROM sales WHERE DATE(created_at)>=?", (month_ago,)).fetchone()[0]

    today_transactions = conn.execute("SELECT COUNT(*) FROM sales WHERE DATE(created_at)=?", (today,)).fetchone()[0]
    total_medicines = conn.execute("SELECT COUNT(*) FROM medicines").fetchone()[0]
    low_stock = conn.execute("SELECT COUNT(*) FROM medicines WHERE stock_qty <= 10").fetchone()[0]
    expiring_soon = conn.execute("SELECT COUNT(*) FROM medicines WHERE expiry_date <= date('now', '+60 days')").fetchone()[0]
    total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    recent_sales = conn.execute("""
        SELECT s.*, u.full_name as cashier_name
        FROM sales s LEFT JOIN users u ON s.user_id = u.id
        ORDER BY s.created_at DESC LIMIT 5
    """).fetchall()

    top_meds = conn.execute("""
        SELECT m.name, SUM(si.quantity) as total_sold, SUM(si.subtotal) as revenue
        FROM sale_items si JOIN medicines m ON si.medicine_id = m.id
        JOIN sales s ON si.sale_id = s.id
        WHERE DATE(s.created_at) >= date('now', '-30 days')
        GROUP BY si.medicine_id ORDER BY total_sold DESC LIMIT 5
    """).fetchall()

    conn.close()
    return render_template('dashboard.html',
        today_sales=today_sales, week_sales=week_sales, month_sales=month_sales,
        today_transactions=today_transactions, total_medicines=total_medicines,
        low_stock=low_stock, expiring_soon=expiring_soon, total_users=total_users,
        recent_sales=recent_sales, top_meds=top_meds)


@app.route('/medicines')
@login_required
def medicines():
    conn = get_db()
    search = request.args.get('q', '')
    if search:
        meds = conn.execute("SELECT * FROM medicines WHERE name LIKE ? OR category LIKE ? ORDER BY name",
                            (f'%{search}%', f'%{search}%')).fetchall()
    else:
        meds = conn.execute("SELECT * FROM medicines ORDER BY name").fetchall()
    conn.close()
    return render_template('medicines.html', medicines=meds, search=search)


@app.route('/medicines/add', methods=['GET', 'POST'])
@login_required
def add_medicine():
    if request.method == 'POST':
        conn = get_db()
        conn.execute("""INSERT INTO medicines (name, category, description, buying_price, selling_price, stock_qty, expiry_date)
                        VALUES (?, ?, ?, ?, ?, ?, ?)""",
                     (request.form['name'], request.form['category'], request.form['description'],
                      float(request.form['buying_price']), float(request.form['selling_price']),
                      int(request.form['stock_qty']), request.form['expiry_date']))
        conn.commit()
        conn.close()
        flash('Medicine added successfully!', 'success')
        return redirect(url_for('medicines'))
    return render_template('add_medicine.html')


@app.route('/medicines/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_medicine(id):
    conn = get_db()
    if request.method == 'POST':
        conn.execute("""UPDATE medicines SET name=?, category=?, description=?, buying_price=?, selling_price=?, stock_qty=?, expiry_date=?
                        WHERE id=?""",
                     (request.form['name'], request.form['category'], request.form['description'],
                      float(request.form['buying_price']), float(request.form['selling_price']),
                      int(request.form['stock_qty']), request.form['expiry_date'], id))
        conn.commit()
        conn.close()
        flash('Medicine updated successfully!', 'success')
        return redirect(url_for('medicines'))
    med = conn.execute("SELECT * FROM medicines WHERE id=?", (id,)).fetchone()
    conn.close()
    if not med:
        flash('Medicine not found', 'error')
        return redirect(url_for('medicines'))
    return render_template('edit_medicine.html', medicine=med)


@app.route('/medicines/delete/<int:id>', methods=['POST'])
@admin_required
def delete_medicine(id):
    conn = get_db()
    conn.execute("DELETE FROM medicines WHERE id=?", (id,))
    conn.commit()
    conn.close()
    flash('Medicine deleted.', 'success')
    return redirect(url_for('medicines'))


@app.route('/sales')
@login_required
def sales_pos():
    conn = get_db()
    meds = conn.execute("SELECT * FROM medicines WHERE stock_qty > 0 ORDER BY name").fetchall()
    conn.close()
    return render_template('sales.html', medicines=meds)


@app.route('/api/sales', methods=['POST'])
@login_required
def record_sale():
    data = request.get_json()
    items = data.get('items', [])
    if not items:
        return jsonify({"error": "Cart is empty"}), 400

    conn = get_db()
    try:
        conn.execute("BEGIN")
        total = 0.0
        sale_items = []
        for item in items:
            med = conn.execute("SELECT * FROM medicines WHERE id=?", (item['medicine_id'],)).fetchone()
            if not med:
                raise Exception(f"Medicine ID {item['medicine_id']} not found")
            if med['stock_qty'] < item['quantity']:
                raise Exception(f"Insufficient stock for {med['name']}. Available: {med['stock_qty']}")
            subtotal = item['quantity'] * med['selling_price']
            total += subtotal
            sale_items.append((item['medicine_id'], item['quantity'], med['selling_price'], subtotal))
            conn.execute("UPDATE medicines SET stock_qty = stock_qty - ? WHERE id = ?", (item['quantity'], item['medicine_id']))

        conn.execute("INSERT INTO sales (user_id, total_amount) VALUES (?, ?)", (session['user_id'], total))
        sale_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        for si in sale_items:
            conn.execute("INSERT INTO sale_items (sale_id, medicine_id, quantity, unit_price, subtotal) VALUES (?, ?, ?, ?, ?)",
                         (sale_id, si[0], si[1], si[2], si[3]))
        conn.commit()
        return jsonify({"success": True, "sale_id": sale_id, "total": total})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()


@app.route('/api/medicines')
@login_required
def api_medicines():
    q = request.args.get('q', '')
    conn = get_db()
    if q:
        meds = conn.execute("SELECT * FROM medicines WHERE name LIKE ? OR category LIKE ? ORDER BY name",
                            (f'%{q}%', f'%{q}%')).fetchall()
    else:
        meds = conn.execute("SELECT * FROM medicines WHERE stock_qty > 0 ORDER BY name").fetchall()
    conn.close()
    return jsonify([dict(m) for m in meds])


@app.route('/receipt/<int:sale_id>')
@login_required
def receipt(sale_id):
    conn = get_db()
    sale = conn.execute("SELECT s.*, u.full_name as cashier_name FROM sales s LEFT JOIN users u ON s.user_id = u.id WHERE s.id=?", (sale_id,)).fetchone()
    items = conn.execute("""SELECT si.*, m.name as medicine_name FROM sale_items si
                            JOIN medicines m ON si.medicine_id = m.id WHERE si.sale_id=?""", (sale_id,)).fetchall()
    conn.close()
    if not sale:
        flash('Sale not found', 'error')
        return redirect(url_for('reports'))
    return render_template('receipt.html', sale=sale, items=items)


@app.route('/reports')
@login_required
def reports():
    conn = get_db()
    period = request.args.get('period', 'daily')
    today = datetime.now().strftime('%Y-%m-%d')

    if period == 'daily':
        start_date = today
    elif period == 'weekly':
        start_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    elif period == 'monthly':
        start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    else:
        start_date = '2000-01-01'

    sales = conn.execute("""
        SELECT s.*, u.full_name as cashier_name FROM sales s
        LEFT JOIN users u ON s.user_id = u.id
        WHERE DATE(s.created_at) >= ? ORDER BY s.created_at DESC
    """, (start_date,)).fetchall()

    summary = conn.execute("""
        SELECT COUNT(*) as count, COALESCE(SUM(total_amount),0) as total
        FROM sales WHERE DATE(created_at) >= ?
    """, (start_date,)).fetchone()

    daily_data = conn.execute("""
        SELECT DATE(created_at) as day, SUM(total_amount) as total, COUNT(*) as count
        FROM sales WHERE DATE(created_at) >= ?
        GROUP BY DATE(created_at) ORDER BY day DESC
    """, (start_date,)).fetchall()

    medicine_report = conn.execute("""
        SELECT m.name, SUM(si.quantity) as qty_sold, SUM(si.subtotal) as revenue
        FROM sale_items si JOIN medicines m ON si.medicine_id = m.id
        JOIN sales s ON si.sale_id = s.id
        WHERE DATE(s.created_at) >= ?
        GROUP BY si.medicine_id ORDER BY revenue DESC
    """, (start_date,)).fetchall()

    conn.close()
    return render_template('reports.html', sales=sales, summary=summary,
                           daily_data=daily_data, medicine_report=medicine_report, period=period)


@app.route('/users')
@admin_required
def users():
    conn = get_db()
    all_users = conn.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
    conn.close()
    return render_template('users.html', users=all_users)


@app.route('/users/add', methods=['GET', 'POST'])
@admin_required
def add_user():
    if request.method == 'POST':
        username = request.form['username'].strip()
        full_name = request.form['full_name'].strip()
        role = request.form['role']
        password = request.form['password']
        if len(password) < 6:
            flash('Password must be at least 6 characters', 'error')
            return render_template('add_user.html')
        conn = get_db()
        existing = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
        if existing:
            flash('Username already exists', 'error')
            conn.close()
            return render_template('add_user.html')
        conn.execute("INSERT INTO users (username, password, full_name, role) VALUES (?, ?, ?, ?)",
                     (username, generate_password_hash(password), full_name, role))
        conn.commit()
        conn.close()
        flash('User created successfully!', 'success')
        return redirect(url_for('users'))
    return render_template('add_user.html')


@app.route('/users/edit/<int:id>', methods=['GET', 'POST'])
@admin_required
def edit_user(id):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (id,)).fetchone()
    if not user:
        conn.close()
        flash('User not found', 'error')
        return redirect(url_for('users'))
    if request.method == 'POST':
        full_name = request.form['full_name'].strip()
        role = request.form['role']
        password = request.form.get('password', '').strip()
        if password:
            if len(password) < 6:
                flash('Password must be at least 6 characters', 'error')
                conn.close()
                return render_template('edit_user.html', user=user)
            conn.execute("UPDATE users SET full_name=?, role=?, password=? WHERE id=?",
                         (full_name, role, generate_password_hash(password), id))
        else:
            conn.execute("UPDATE users SET full_name=?, role=? WHERE id=?", (full_name, role, id))
        conn.commit()
        conn.close()
        flash('User updated successfully!', 'success')
        return redirect(url_for('users'))
    conn.close()
    return render_template('edit_user.html', user=user)


@app.route('/users/delete/<int:id>', methods=['POST'])
@admin_required
def delete_user(id):
    if id == session.get('user_id'):
        flash("You cannot delete your own account", 'error')
        return redirect(url_for('users'))
    conn = get_db()
    conn.execute("DELETE FROM users WHERE id=?", (id,))
    conn.commit()
    conn.close()
    flash('User deleted.', 'success')
    return redirect(url_for('users'))


if __name__ == '__main__':
    app.run(debug=True)
