import psycopg
from psycopg.rows import dict_row
import os
import shutil
from datetime import datetime, timedelta, timezone
from functools import wraps
from flask import (Flask, request, jsonify, render_template,
                   redirect, url_for, session, flash, send_file)
from werkzeug.security import generate_password_hash, check_password_hash
from io import BytesIO, StringIO
import csv

app = Flask(__name__)
app.secret_key = 'pharmacy-secret-key-2026'


@app.template_filter('dateonly')
def dateonly_filter(value):
    if value is None:
        return ''
    if hasattr(value, 'strftime'):
        return value.strftime('%Y-%m-%d')
    return str(value)[:10]


@app.template_filter('datetime_short')
def datetime_short_filter(value):
    if value is None:
        return ''
    if hasattr(value, 'strftime'):
        return value.strftime('%Y-%m-%d %H:%M')
    return str(value)[:16]
DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://postgres.oypqzvhtszdyahtrxysc:pharmadawa123@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres')


def get_db():
    import time
    for attempt in range(2):
        try:
            conn = psycopg.connect(DATABASE_URL)
            conn.autocommit = False
            return conn
        except Exception:
            if attempt == 0:
                time.sleep(5)
            else:
                raise


def dict_query(conn, sql, params=None):
    cur = conn.cursor(row_factory=dict_row)
    cur.execute(sql, params or ())
    return cur


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


def get_branch_id():
    if session.get('role') == 'admin':
        bid = session.get('selected_branch_id', 1)
        if bid == 0:
            return None
        return bid
    return session.get('branch_id', 1)


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute('''CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        full_name TEXT NOT NULL,
        phone TEXT,
        role TEXT NOT NULL DEFAULT 'pharmacist',
        branch_id INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    cur.execute('''CREATE TABLE IF NOT EXISTS expenses (
        id SERIAL PRIMARY KEY,
        category TEXT NOT NULL,
        description TEXT,
        amount REAL NOT NULL,
        expense_date DATE DEFAULT CURRENT_DATE,
        branch_id INTEGER DEFAULT 1,
        user_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (branch_id) REFERENCES branches(id),
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')

    cur.execute('''CREATE TABLE IF NOT EXISTS medicines (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        category TEXT,
        description TEXT,
        buying_price REAL NOT NULL,
        selling_price REAL NOT NULL,
        stock_qty INTEGER NOT NULL DEFAULT 0,
        expiry_date TEXT NOT NULL,
        purchase_date TEXT,
        branch_id INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    cur.execute('''CREATE TABLE IF NOT EXISTS purchases (
        id SERIAL PRIMARY KEY,
        medicine_id INTEGER,
        quantity INTEGER NOT NULL,
        unit_cost REAL NOT NULL,
        supplier TEXT,
        notes TEXT,
        branch_id INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (medicine_id) REFERENCES medicines(id)
    )''')

    cur.execute('''CREATE TABLE IF NOT EXISTS adjustments (
        id SERIAL PRIMARY KEY,
        medicine_id INTEGER,
        quantity_changed INTEGER NOT NULL,
        reason TEXT NOT NULL,
        notes TEXT,
        user_id INTEGER,
        branch_id INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (medicine_id) REFERENCES medicines(id),
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')

    cur.execute('''CREATE TABLE IF NOT EXISTS sales (
        id SERIAL PRIMARY KEY,
        user_id INTEGER,
        total_amount REAL NOT NULL,
        payment_method TEXT DEFAULT 'cash',
        branch_id INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')

    cur.execute('''CREATE TABLE IF NOT EXISTS sale_items (
        id SERIAL PRIMARY KEY,
        sale_id INTEGER,
        medicine_id INTEGER,
        quantity INTEGER NOT NULL,
        unit_price REAL NOT NULL,
        subtotal REAL NOT NULL,
        FOREIGN KEY (sale_id) REFERENCES sales(id),
        FOREIGN KEY (medicine_id) REFERENCES medicines(id)
    )''')

    cur.execute('''CREATE TABLE IF NOT EXISTS branches (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        location TEXT,
        phone TEXT,
        is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    try:
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS phone TEXT")
        cur.execute("ALTER TABLE medicines ADD COLUMN IF NOT EXISTS branch_id INTEGER DEFAULT 1")
        conn.commit()
    except Exception:
        conn.rollback()

    cur.execute("SELECT COUNT(*) FROM users")
    if cur.fetchone()[0] == 0:
        admin_pw = generate_password_hash('admin123')
        pharm_pw = generate_password_hash('pharm123')
        cur.execute("INSERT INTO users (username, password, full_name, role) VALUES (%s, %s, %s, %s)",
                    ('admin', admin_pw, 'System Administrator', 'admin'))
        cur.execute("INSERT INTO users (username, password, full_name, role) VALUES (%s, %s, %s, %s)",
                    ('pharmacist', pharm_pw, 'Pharmacy Staff', 'pharmacist'))

    cur.execute("SELECT COUNT(*) FROM branches")
    if cur.fetchone()[0] == 0:
        cur.execute("INSERT INTO branches (name, location, phone) VALUES (%s, %s, %s)",
                    ('Main Branch', 'Dar es Salaam', '+255 123 456 789'))

    cur.execute("SELECT COUNT(*) FROM medicines")
    if cur.fetchone()[0] == 0:
        cur.execute("SELECT id FROM branches WHERE is_active=1 ORDER BY id LIMIT 1")
        branch = cur.fetchone()
        branch_id = branch[0] if branch else 1
        meds = [
            ('Paracetamol 500mg', 'Painkiller', 'Pain and fever relief tablet', 500, 1000, 100, '2027-12-31', '2026-01-15'),
            ('Amoxicillin 500mg', 'Antibiotic', 'Broad-spectrum antibiotic capsule', 1500, 3000, 50, '2026-09-30', '2026-02-10'),
            ('Cetirizine 10mg', 'Antihistamine', 'Allergy relief tablet', 300, 800, 120, '2028-05-15', '2026-03-05'),
            ('Panadol Extra', 'Painkiller', 'Extra strength pain relief', 600, 1200, 80, '2027-06-20', '2026-01-20'),
            ('Azithromycin 250mg', 'Antibiotic', 'Macrolide antibiotic', 2000, 4500, 30, '2026-11-15', '2026-02-28'),
            ('Omeprazole 20mg', 'Antacid', 'Proton pump inhibitor for acid reflux', 800, 1500, 60, '2027-08-10', '2026-04-01'),
            ('Metformin 500mg', 'Antidiabetic', 'Blood sugar control tablet', 1200, 2500, 45, '2027-03-25', '2026-03-15'),
            ('Loratadine 10mg', 'Antihistamine', 'Non-drowsy allergy relief', 400, 900, 90, '2028-01-20', '2026-05-10'),
            ('Ibuprofen 400mg', 'Painkiller', 'Anti-inflammatory pain relief', 600, 1200, 75, '2027-10-05', '2026-02-05'),
            ('Vitamin C 1000mg', 'Supplement', 'Immune system booster', 300, 700, 150, '2028-06-30', '2026-06-01'),
            ('Cough Syrup 100ml', 'Cough Medicine', 'Relief for dry and productive cough', 1000, 2000, 40, '2027-04-18', '2026-01-25'),
            ('ORS Sachets', 'Hydration', 'Oral rehydration salts', 200, 500, 200, '2028-12-31', '2026-03-20'),
        ]
        for m in meds:
            cur.execute("INSERT INTO medicines (name, category, description, buying_price, selling_price, stock_qty, expiry_date, purchase_date, branch_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (*m, branch_id))

    conn.commit()
    cur.close()
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
        cur = dict_query(conn, "SELECT * FROM users WHERE username = %s", (username,))
        user = cur.fetchone()
        cur.close()
        conn.close()
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['full_name'] = user['full_name']
            session['role'] = user['role']
            session['phone'] = user.get('phone', '') or ''
            session['branch_id'] = user['branch_id'] or 1
            session['selected_branch_id'] = session['branch_id']
            return redirect(url_for('dashboard'))
        flash('Wrong username or password', 'error')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/switch-branch', methods=['POST'])
@login_required
def switch_branch():
    if session.get('role') != 'admin':
        flash('Only admins can switch branches', 'error')
        return redirect(url_for('dashboard'))
    branch_id = int(request.form.get('branch_id', 1))
    session['selected_branch_id'] = branch_id
    return redirect(request.referrer or url_for('dashboard'))


@app.route('/')
@login_required
def dashboard():
    conn = get_db()
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime('%Y-%m-%d')
    month_ago = (datetime.now(timezone.utc) - timedelta(days=30)).strftime('%Y-%m-%d')
    bid = get_branch_id()
    bfilter = "AND branch_id=%s" if bid else ""
    bargs = (bid,) if bid else ()

    cur = dict_query(conn, f"SELECT COALESCE(SUM(total_amount),0) as val FROM sales WHERE created_at::date=%s {bfilter}", (today, *bargs))
    today_sales = cur.fetchone()['val']
    cur.close()

    cur = dict_query(conn, f"SELECT COALESCE(SUM(total_amount),0) as val FROM sales WHERE created_at::date>=%s {bfilter}", (week_ago, *bargs))
    week_sales = cur.fetchone()['val']
    cur.close()

    cur = dict_query(conn, f"SELECT COALESCE(SUM(total_amount),0) as val FROM sales WHERE created_at::date>=%s {bfilter}", (month_ago, *bargs))
    month_sales = cur.fetchone()['val']
    cur.close()

    cur = dict_query(conn, f"SELECT COUNT(*) as val FROM sales WHERE created_at::date=%s {bfilter}", (today, *bargs))
    today_transactions = cur.fetchone()['val']
    cur.close()

    cur = dict_query(conn, f"SELECT COUNT(*) as val FROM medicines WHERE 1=1 {bfilter}", (*bargs,))
    total_medicines = cur.fetchone()['val']
    cur.close()

    cur = dict_query(conn, f"SELECT COUNT(*) as val FROM medicines WHERE stock_qty <= 10 {bfilter}", (*bargs,))
    low_stock_count = cur.fetchone()['val']
    cur.close()

    cur = dict_query(conn, f"SELECT COUNT(*) as val FROM medicines WHERE expiry_date <= (CURRENT_DATE + INTERVAL '60 days')::text {bfilter}", (*bargs,))
    expiring_count = cur.fetchone()['val']
    cur.close()

    cur = dict_query(conn, "SELECT COUNT(*) as val FROM users")
    total_users = cur.fetchone()['val']
    cur.close()

    sbfilter = "AND s.branch_id=%s" if bid else ""
    cur = dict_query(conn, f"""
        SELECT COALESCE(SUM((si.unit_price - m.buying_price) * si.quantity), 0) as val
        FROM sale_items si JOIN medicines m ON si.medicine_id = m.id
        JOIN sales s ON si.sale_id = s.id WHERE s.created_at::date>=%s {sbfilter}
    """, (month_ago, *bargs))
    month_profit = cur.fetchone()['val']
    cur.close()

    cur = dict_query(conn, f"""
        SELECT COALESCE(SUM((si.unit_price - m.buying_price) * si.quantity), 0) as val
        FROM sale_items si JOIN medicines m ON si.medicine_id = m.id
        JOIN sales s ON si.sale_id = s.id WHERE s.created_at::date=%s {sbfilter}
    """, (today, *bargs))
    today_profit = cur.fetchone()['val']
    cur.close()

    cur = dict_query(conn, f"SELECT COALESCE(SUM(quantity * unit_cost), 0) as val FROM purchases WHERE created_at::date=%s {bfilter}", (today, *bargs))
    today_expenses = cur.fetchone()['val']
    cur.close()

    cur = dict_query(conn, f"SELECT COALESCE(SUM(quantity * unit_cost), 0) as val FROM purchases WHERE created_at::date>=%s {bfilter}", (month_ago, *bargs))
    month_expenses = cur.fetchone()['val']
    cur.close()

    cur = dict_query(conn, f"""
        SELECT COALESCE(SUM(m.buying_price * si.quantity), 0) as val
        FROM sale_items si JOIN medicines m ON si.medicine_id = m.id
        JOIN sales s ON si.sale_id = s.id WHERE s.created_at::date=%s {sbfilter}
    """, (today, *bargs))
    today_cogs = cur.fetchone()['val']
    cur.close()

    cur = dict_query(conn, f"""
        SELECT COALESCE(SUM(m.buying_price * si.quantity), 0) as val
        FROM sale_items si JOIN medicines m ON si.medicine_id = m.id
        JOIN sales s ON si.sale_id = s.id WHERE s.created_at::date>=%s {sbfilter}
    """, (month_ago, *bargs))
    month_cogs = cur.fetchone()['val']
    cur.close()

    cur = dict_query(conn, f"SELECT COALESCE(SUM(amount), 0) as val FROM expenses WHERE expense_date=%s {bfilter}", (today, *bargs))
    today_op_expenses = cur.fetchone()['val']
    cur.close()

    cur = dict_query(conn, f"SELECT COALESCE(SUM(amount), 0) as val FROM expenses WHERE expense_date>=%s {bfilter}", (month_ago, *bargs))
    month_op_expenses = cur.fetchone()['val']
    cur.close()

    today_gross_profit = today_sales - today_cogs
    today_net_profit = today_gross_profit - today_op_expenses
    month_gross_profit = month_sales - month_cogs
    month_net_profit = month_gross_profit - month_op_expenses

    cur = dict_query(conn, f"SELECT id, name, category, stock_qty, selling_price FROM medicines WHERE stock_qty <= 10 {bfilter} ORDER BY stock_qty ASC LIMIT 8", (*bargs,))
    low_stock_items = cur.fetchall()
    cur.close()

    cur = dict_query(conn, f"""
        SELECT id, name, category, stock_qty, expiry_date,
        (expiry_date::date - CURRENT_DATE) as days_left
        FROM medicines WHERE expiry_date <= (CURRENT_DATE + INTERVAL '60 days')::text
        AND expiry_date >= CURRENT_DATE::text
        {bfilter}
        ORDER BY expiry_date ASC LIMIT 8
    """, (*bargs,))
    expiring_items = cur.fetchall()
    cur.close()

    cur = dict_query(conn, f"SELECT COUNT(*) as val FROM medicines WHERE expiry_date < CURRENT_DATE::text {bfilter}", (*bargs,))
    expired_count = cur.fetchone()['val']
    cur.close()

    cur = dict_query(conn, f"""
        SELECT s.*, u.full_name as cashier_name
        FROM sales s LEFT JOIN users u ON s.user_id = u.id
        WHERE 1=1 {sbfilter}
        ORDER BY s.created_at DESC LIMIT 5
    """, (*bargs,))
    recent_sales = cur.fetchall()
    cur.close()

    cur = dict_query(conn, f"""
        SELECT m.name, SUM(si.quantity) as total_sold, SUM(si.subtotal) as revenue,
        SUM((si.unit_price - m.buying_price) * si.quantity) as profit
        FROM sale_items si JOIN medicines m ON si.medicine_id = m.id
        JOIN sales s ON si.sale_id = s.id
        WHERE s.created_at::date >= CURRENT_DATE - INTERVAL '30 days' {sbfilter}
        GROUP BY si.medicine_id, m.name ORDER BY total_sold DESC LIMIT 5
    """, (*bargs,))
    top_meds = cur.fetchall()
    cur.close()

    cur = dict_query(conn, "SELECT * FROM branches WHERE is_active=1 ORDER BY name")
    branches = cur.fetchall()
    cur.close()

    current_branch = None
    if bid:
        cur = dict_query(conn, "SELECT * FROM branches WHERE id=%s", (bid,))
        current_branch = cur.fetchone()
        cur.close()

    conn.close()
    return render_template('dashboard.html',
        today_sales=today_sales, week_sales=week_sales, month_sales=month_sales,
        today_transactions=today_transactions, total_medicines=total_medicines,
        low_stock_count=low_stock_count, expiring_count=expiring_count,
        expired_count=expired_count, total_users=total_users,
        recent_sales=recent_sales, top_meds=top_meds,
        month_profit=month_profit, today_profit=today_profit,
        today_expenses=today_expenses, month_expenses=month_expenses,
        today_cogs=today_cogs, month_cogs=month_cogs,
        today_op_expenses=today_op_expenses, month_op_expenses=month_op_expenses,
        today_gross_profit=today_gross_profit, today_net_profit=today_net_profit,
        month_gross_profit=month_gross_profit, month_net_profit=month_net_profit,
        low_stock_items=low_stock_items, expiring_items=expiring_items,
        branches=branches, current_branch=current_branch)


@app.route('/medicines')
@login_required
def medicines():
    conn = get_db()
    bid = get_branch_id()
    search = request.args.get('q', '')
    bfilter = "AND branch_id=%s" if bid else ""
    bargs = (bid,) if bid else ()
    if search:
        cur = dict_query(conn, f"SELECT * FROM medicines WHERE (name ILIKE %s OR category ILIKE %s) {bfilter} ORDER BY name",
                         (f'%{search}%', f'%{search}%', *bargs))
    else:
        cur = dict_query(conn, f"SELECT * FROM medicines WHERE 1=1 {bfilter} ORDER BY name", (*bargs,))
    meds = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('medicines.html', medicines=meds, search=search)


@app.route('/medicines/add', methods=['GET', 'POST'])
@login_required
def add_medicine():
    if request.method == 'POST':
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""INSERT INTO medicines (name, category, description, buying_price, selling_price, stock_qty, expiry_date, purchase_date, branch_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                     (request.form['name'], request.form['category'], request.form['description'],
                      float(request.form['buying_price']), float(request.form['selling_price']),
                      int(request.form['stock_qty']), request.form['expiry_date'],
                      request.form.get('purchase_date', ''), get_branch_id()))
        conn.commit()
        cur.close()
        conn.close()
        flash('Medicine added successfully!', 'success')
        return redirect(url_for('medicines'))
    return render_template('add_medicine.html')


@app.route('/medicines/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_medicine(id):
    conn = get_db()
    if request.method == 'POST':
        cur = conn.cursor()
        cur.execute("""UPDATE medicines SET name=%s, category=%s, description=%s, buying_price=%s, selling_price=%s, stock_qty=%s, expiry_date=%s, purchase_date=%s
                        WHERE id=%s""",
                     (request.form['name'], request.form['category'], request.form['description'],
                      float(request.form['buying_price']), float(request.form['selling_price']),
                      int(request.form['stock_qty']), request.form['expiry_date'],
                      request.form.get('purchase_date', ''), id))
        conn.commit()
        cur.close()
        conn.close()
        flash('Medicine updated successfully!', 'success')
        return redirect(url_for('medicines'))
    bid = get_branch_id()
    if bid is not None:
        cur = dict_query(conn, "SELECT * FROM medicines WHERE id=%s AND branch_id=%s", (id, bid))
    else:
        cur = dict_query(conn, "SELECT * FROM medicines WHERE id=%s", (id,))
    med = cur.fetchone()
    cur.close()
    conn.close()
    if not med:
        flash('Medicine not found', 'error')
        return redirect(url_for('medicines'))
    return render_template('edit_medicine.html', medicine=med)


@app.route('/medicines/delete/<int:id>', methods=['POST'])
@admin_required
def delete_medicine(id):
    bid = get_branch_id()
    conn = get_db()
    cur = conn.cursor()
    if bid is not None:
        cur.execute("DELETE FROM medicines WHERE id=%s AND branch_id=%s", (id, bid))
    else:
        cur.execute("DELETE FROM medicines WHERE id=%s", (id,))
    conn.commit()
    cur.close()
    conn.close()
    flash('Medicine deleted.', 'success')
    return redirect(url_for('medicines'))


@app.route('/sales')
@login_required
def sales_pos():
    conn = get_db()
    bid = get_branch_id()
    bfilter = "AND branch_id=%s" if bid else ""
    bargs = (bid,) if bid else ()
    cur = dict_query(conn, f"SELECT * FROM medicines WHERE stock_qty > 0 {bfilter} ORDER BY name", (*bargs,))
    meds = cur.fetchall()
    cur.close()
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
    cur = conn.cursor(row_factory=dict_row)
    try:
        total = 0.0
        sale_items = []
        for item in items:
            cur.execute("SELECT * FROM medicines WHERE id=%s", (item['medicine_id'],))
            med = cur.fetchone()
            if not med:
                raise Exception(f"Medicine ID {item['medicine_id']} not found")
            qty = int(item['quantity'])
            if med['stock_qty'] < qty:
                raise Exception(f"Insufficient stock for {med['name']}. Available: {med['stock_qty']}")
            subtotal = qty * med['selling_price']
            total += subtotal
            sale_items.append((item['medicine_id'], qty, med['selling_price'], subtotal))
            cur.execute("UPDATE medicines SET stock_qty = stock_qty - %s WHERE id = %s", (qty, item['medicine_id']))

        cur.execute("INSERT INTO sales (user_id, total_amount, branch_id) VALUES (%s, %s, %s) RETURNING id",
                    (session['user_id'], total, get_branch_id()))
        sale_id = cur.fetchone()['id']
        for si in sale_items:
            cur.execute("INSERT INTO sale_items (sale_id, medicine_id, quantity, unit_price, subtotal) VALUES (%s, %s, %s, %s, %s)",
                        (sale_id, si[0], si[1], si[2], si[3]))
        conn.commit()
        return jsonify({"success": True, "sale_id": sale_id, "total": total})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 400
    finally:
        cur.close()
        conn.close()


@app.route('/api/medicines')
@login_required
def api_medicines():
    q = request.args.get('q', '')
    bid = get_branch_id()
    bfilter = "AND branch_id=%s" if bid else ""
    bargs = (bid,) if bid else ()
    conn = get_db()
    if q:
        cur = dict_query(conn, f"SELECT * FROM medicines WHERE (name ILIKE %s OR category ILIKE %s) {bfilter} ORDER BY name",
                         (f'%{q}%', f'%{q}%', *bargs))
    else:
        cur = dict_query(conn, f"SELECT * FROM medicines WHERE stock_qty > 0 {bfilter} ORDER BY name", (*bargs,))
    meds = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([dict(m) for m in meds])


@app.route('/receipt/<int:sale_id>')
@login_required
def receipt(sale_id):
    conn = get_db()
    cur = dict_query(conn, """SELECT s.*, u.full_name as cashier_name, b.name as branch_name
                            FROM sales s
                            LEFT JOIN users u ON s.user_id = u.id
                            LEFT JOIN branches b ON s.branch_id = b.id
                            WHERE s.id=%s""", (sale_id,))
    sale = cur.fetchone()
    cur.close()
    cur = dict_query(conn, """SELECT si.*, m.name as medicine_name FROM sale_items si
                            JOIN medicines m ON si.medicine_id = m.id WHERE si.sale_id=%s""", (sale_id,))
    items = cur.fetchall()
    cur.close()
    conn.close()
    if not sale:
        flash('Sale not found', 'error')
        return redirect(url_for('reports'))
    pharmacist_phone = session.get('phone', '')

    branch_name = sale.get('branch_name') or 'PharmaCare'
    cashier = sale.get('cashier_name') or 'N/A'
    date_str = sale['created_at'].strftime('%d %b %Y %H:%M') if hasattr(sale['created_at'], 'strftime') else str(sale['created_at'])
    receipt_lines = [
        "\u2728 *PHARMACARE RECEIPT* \u2728",
        "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500",
        f"\uD83D\uDCCD *Branch:* {branch_name}",
        f"\uD83D\uDCC5 *Date:* {date_str}",
        f"\uD83D\uDCCB *Receipt:* #{sale['id']:05d}",
        f"\uD83D\uDC64 *Cashier:* {cashier}",
        "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500",
        "\uD83D\uDCC2 *ITEMS PURCHASED*",
        "",
    ]
    for item in items:
        receipt_lines.append(f"\u2022 *{item['medicine_name']}*")
        receipt_lines.append(f"  Qty: {item['quantity']} \u00D7 TSH {item['unit_price']:,.0f} = *TSH {item['subtotal']:,.0f}*")
        receipt_lines.append("")
    receipt_lines.extend([
        "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500",
        f"\uD83D\uDCB0 *TOTAL: TSH {sale['total_amount']:,.0f}*",
        "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500",
        "\u2705 *Payment Confirmed!*",
        "\uD83D\uDE0A Thank you for choosing *PharmaCare*!",
        f"\uD83C\uDFF0 *{branch_name}*",
    ])
    receipt_text = "\n".join(receipt_lines)

    import json as _json
    receipt_text_json = _json.dumps(receipt_text)

    return render_template('receipt.html', sale=sale, items=items, pharmacist_phone=pharmacist_phone, receipt_text_json=receipt_text_json)


@app.route('/reports')
@login_required
def reports():
    conn = get_db()
    period = request.args.get('period', 'daily')
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    bid = get_branch_id()
    sbfilter = "AND s.branch_id=%s" if bid else ""
    bfilter = "AND branch_id=%s" if bid else ""
    bargs = (bid,) if bid else ()

    if period == 'daily':
        start_date = today
    elif period == 'weekly':
        start_date = (datetime.now(timezone.utc) - timedelta(days=7)).strftime('%Y-%m-%d')
    elif period == 'monthly':
        start_date = (datetime.now(timezone.utc) - timedelta(days=30)).strftime('%Y-%m-%d')
    else:
        start_date = '2000-01-01'

    cur = dict_query(conn, f"""
        SELECT s.*, u.full_name as cashier_name FROM sales s
        LEFT JOIN users u ON s.user_id = u.id
        WHERE s.created_at::date >= %s {sbfilter} ORDER BY s.created_at DESC
    """, (start_date, *bargs))
    sales = cur.fetchall()
    cur.close()

    cur = dict_query(conn, f"""
        SELECT COUNT(*) as count, COALESCE(SUM(total_amount),0) as total
        FROM sales WHERE created_at::date >= %s {bfilter}
    """, (start_date, *bargs))
    summary = cur.fetchone()
    cur.close()

    cur = dict_query(conn, f"""
        SELECT COALESCE(SUM(si.subtotal), 0) as revenue,
               COALESCE(SUM(m.buying_price * si.quantity), 0) as cost,
               COALESCE(SUM((si.unit_price - m.buying_price) * si.quantity), 0) as profit
        FROM sale_items si JOIN medicines m ON si.medicine_id = m.id
        JOIN sales s ON si.sale_id = s.id WHERE s.created_at::date >= %s {sbfilter}
    """, (start_date, *bargs))
    profit_summary = cur.fetchone()
    cur.close()

    cur = dict_query(conn, f"""
        SELECT created_at::date as day, SUM(total_amount) as total, COUNT(*) as count
        FROM sales WHERE created_at::date >= %s {bfilter}
        GROUP BY created_at::date ORDER BY day DESC
    """, (start_date, *bargs))
    daily_data = cur.fetchall()
    cur.close()

    cur = dict_query(conn, f"""
        SELECT m.name, SUM(si.quantity) as qty_sold, SUM(si.subtotal) as revenue,
        SUM(m.buying_price * si.quantity) as cost,
        SUM((si.unit_price - m.buying_price) * si.quantity) as profit
        FROM sale_items si JOIN medicines m ON si.medicine_id = m.id
        JOIN sales s ON si.sale_id = s.id
        WHERE s.created_at::date >= %s {sbfilter}
        GROUP BY si.medicine_id, m.name ORDER BY revenue DESC
    """, (start_date, *bargs))
    medicine_report = cur.fetchall()
    cur.close()

    conn.close()
    return render_template('reports.html', sales=sales, summary=summary,
                           profit_summary=profit_summary, daily_data=daily_data,
                           medicine_report=medicine_report, period=period, start_date=start_date)


@app.route('/users')
@admin_required
def users():
    conn = get_db()
    cur = dict_query(conn, "SELECT * FROM users ORDER BY created_at DESC")
    all_users = cur.fetchall()
    cur.close()
    cur = dict_query(conn, "SELECT * FROM branches WHERE is_active=1 ORDER BY name")
    branches = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('users.html', users=all_users, branches=branches)


@app.route('/users/add', methods=['GET', 'POST'])
@admin_required
def add_user():
    conn = get_db()
    cur = dict_query(conn, "SELECT * FROM branches WHERE is_active=1 ORDER BY name")
    branches = cur.fetchall()
    cur.close()
    if request.method == 'POST':
        username = request.form['username'].strip()
        full_name = request.form['full_name'].strip()
        phone = request.form.get('phone', '').strip()
        role = request.form['role']
        password = request.form['password']
        branch_id = int(request.form.get('branch_id', 1))
        if len(password) < 6:
            flash('Password must be at least 6 characters', 'error')
            conn.close()
            return render_template('add_user.html', branches=branches)
        cur = dict_query(conn, "SELECT id FROM users WHERE username=%s", (username,))
        existing = cur.fetchone()
        cur.close()
        if existing:
            flash('Username already exists', 'error')
            conn.close()
            return render_template('add_user.html', branches=branches)
        cur = conn.cursor()
        cur.execute("INSERT INTO users (username, password, full_name, phone, role, branch_id) VALUES (%s, %s, %s, %s, %s, %s)",
                    (username, generate_password_hash(password), full_name, phone or None, role, branch_id))
        conn.commit()
        cur.close()
        conn.close()
        flash('User created successfully!', 'success')
        return redirect(url_for('users'))
    conn.close()
    return render_template('add_user.html', branches=branches)


@app.route('/users/edit/<int:id>', methods=['GET', 'POST'])
@admin_required
def edit_user(id):
    conn = get_db()
    cur = dict_query(conn, "SELECT * FROM users WHERE id=%s", (id,))
    user = cur.fetchone()
    cur.close()
    cur = dict_query(conn, "SELECT * FROM branches WHERE is_active=1 ORDER BY name")
    branches = cur.fetchall()
    cur.close()
    if not user:
        conn.close()
        flash('User not found', 'error')
        return redirect(url_for('users'))
    if request.method == 'POST':
        full_name = request.form['full_name'].strip()
        phone = request.form.get('phone', '').strip()
        role = request.form['role']
        branch_id = int(request.form.get('branch_id', 1))
        password = request.form.get('password', '').strip()
        cur = conn.cursor()
        if password:
            if len(password) < 6:
                flash('Password must be at least 6 characters', 'error')
                conn.close()
                return render_template('edit_user.html', user=user, branches=branches)
            cur.execute("UPDATE users SET full_name=%s, phone=%s, role=%s, password=%s, branch_id=%s WHERE id=%s",
                        (full_name, phone or None, role, generate_password_hash(password), branch_id, id))
        else:
            cur.execute("UPDATE users SET full_name=%s, phone=%s, role=%s, branch_id=%s WHERE id=%s",
                        (full_name, phone or None, role, branch_id, id))
        conn.commit()
        cur.close()
        conn.close()
        flash('User updated successfully!', 'success')
        return redirect(url_for('users'))
    conn.close()
    return render_template('edit_user.html', user=user, branches=branches)


@app.route('/users/delete/<int:id>', methods=['POST'])
@admin_required
def delete_user(id):
    if id == session.get('user_id'):
        flash("You cannot delete your own account", 'error')
        return redirect(url_for('users'))
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM users WHERE id=%s", (id,))
    conn.commit()
    cur.close()
    conn.close()
    flash('User deleted.', 'success')
    return redirect(url_for('users'))


@app.route('/export/csv/<period>')
@login_required
def export_csv(period):
    conn = get_db()
    bid = get_branch_id()
    sbfilter = "AND s.branch_id=%s" if bid else ""
    bargs = (bid,) if bid else ()
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    if period == 'daily':
        start_date = today
    elif period == 'weekly':
        start_date = (datetime.now(timezone.utc) - timedelta(days=7)).strftime('%Y-%m-%d')
    elif period == 'monthly':
        start_date = (datetime.now(timezone.utc) - timedelta(days=30)).strftime('%Y-%m-%d')
    else:
        start_date = '2000-01-01'

    cur = dict_query(conn, f"""
        SELECT s.id, s.created_at, u.full_name, s.total_amount,
        COALESCE(SUM((si.unit_price - m.buying_price) * si.quantity), 0) as profit
        FROM sales s LEFT JOIN users u ON s.user_id = u.id
        LEFT JOIN sale_items si ON si.sale_id = s.id
        LEFT JOIN medicines m ON si.medicine_id = m.id
        WHERE s.created_at::date >= %s {sbfilter}
        GROUP BY s.id, s.created_at, u.full_name, s.total_amount ORDER BY s.created_at DESC
    """, (start_date, *bargs))
    sales = cur.fetchall()
    cur.close()
    conn.close()

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['Sale ID', 'Date', 'Cashier', 'Total (TSH)', 'Profit (TSH)'])
    for sale in sales:
        writer.writerow([sale['id'], sale['created_at'], sale['full_name'],
                        sale['total_amount'], sale['profit']])

    mem = BytesIO()
    mem.write(output.getvalue().encode('utf-8'))
    mem.seek(0)
    return send_file(mem, mimetype='text/csv',
                     as_attachment=True,
                     download_name=f'pharmcare_sales_{period}_{today}.csv')


@app.route('/export/excel/<period>')
@login_required
def export_excel(period):
    conn = get_db()
    bid = get_branch_id()
    sbfilter = "AND s.branch_id=%s" if bid else ""
    bargs = (bid,) if bid else ()
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    if period == 'daily':
        start_date = today
    elif period == 'weekly':
        start_date = (datetime.now(timezone.utc) - timedelta(days=7)).strftime('%Y-%m-%d')
    elif period == 'monthly':
        start_date = (datetime.now(timezone.utc) - timedelta(days=30)).strftime('%Y-%m-%d')
    else:
        start_date = '2000-01-01'

    cur = dict_query(conn, f"""
        SELECT s.id, s.created_at, u.full_name, s.total_amount,
        COALESCE(SUM((si.unit_price - m.buying_price) * si.quantity), 0) as profit
        FROM sales s LEFT JOIN users u ON s.user_id = u.id
        LEFT JOIN sale_items si ON si.sale_id = s.id
        LEFT JOIN medicines m ON si.medicine_id = m.id
        WHERE s.created_at::date >= %s {sbfilter}
        GROUP BY s.id, s.created_at, u.full_name, s.total_amount ORDER BY s.created_at DESC
    """, (start_date, *bargs))
    sales = cur.fetchall()
    cur.close()

    cur = dict_query(conn, f"""
        SELECT m.name, SUM(si.quantity) as qty_sold, SUM(si.subtotal) as revenue,
        SUM(m.buying_price * si.quantity) as cost,
        SUM((si.unit_price - m.buying_price) * si.quantity) as profit
        FROM sale_items si JOIN medicines m ON si.medicine_id = m.id
        JOIN sales s ON si.sale_id = s.id
        WHERE s.created_at::date >= %s {sbfilter}
        GROUP BY si.medicine_id, m.name ORDER BY revenue DESC
    """, (start_date, *bargs))
    medicine_report = cur.fetchall()
    cur.close()
    conn.close()

    output = StringIO()
    output.write('\ufeff')
    writer = csv.writer(output)
    writer.writerow([f'PharmaCare Sales Report - {period.upper()}'])
    writer.writerow([f'Generated: {today}'])
    writer.writerow([])
    writer.writerow(['=== SALES SUMMARY ==='])
    writer.writerow(['Sale ID', 'Date', 'Cashier', 'Total (TSH)', 'Profit (TSH)'])
    for sale in sales:
        writer.writerow([sale['id'], sale['created_at'], sale['full_name'],
                        f"{sale['total_amount']:.0f}", f"{sale['profit']:.0f}"])
    writer.writerow([])
    writer.writerow(['=== MEDICINE PERFORMANCE ==='])
    writer.writerow(['Medicine', 'Qty Sold', 'Revenue (TSH)', 'Cost (TSH)', 'Profit (TSH)'])
    for med in medicine_report:
        writer.writerow([med['name'], med['qty_sold'], f"{med['revenue']:.0f}",
                        f"{med['cost']:.0f}", f"{med['profit']:.0f}"])

    mem = BytesIO()
    mem.write(output.getvalue().encode('utf-8-sig'))
    mem.seek(0)
    return send_file(mem, mimetype='text/csv',
                     as_attachment=True,
                     download_name=f'pharmcare_report_{period}_{today}.csv')


@app.route('/export/inventory')
@login_required
def export_inventory():
    conn = get_db()
    bid = get_branch_id()
    bfilter = "WHERE branch_id=%s" if bid else ""
    bargs = (bid,) if bid else ()
    cur = dict_query(conn, f"SELECT * FROM medicines {bfilter} ORDER BY category, name", (*bargs,))
    meds = cur.fetchall()
    cur.close()
    conn.close()

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['PharmaCare Inventory Report'])
    writer.writerow([f'Generated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")}'])
    writer.writerow([])
    writer.writerow(['Name', 'Category', 'Description', 'Buy Price', 'Sell Price', 'Stock', 'Profit/Unit', 'Expiry'])
    for m in meds:
        profit = m['selling_price'] - m['buying_price']
        writer.writerow([m['name'], m['category'], m['description'],
                        f"{m['buying_price']:.0f}", f"{m['selling_price']:.0f}",
                        m['stock_qty'], f"{profit:.0f}", m['expiry_date']])

    mem = BytesIO()
    mem.write(output.getvalue().encode('utf-8-sig'))
    mem.seek(0)
    return send_file(mem, mimetype='text/csv',
                     as_attachment=True,
                     download_name=f'pharmcare_inventory_{datetime.now(timezone.utc).strftime("%Y-%m-%d")}.csv')


BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backups')
BRANCH_TABLES = ['medicines', 'purchases', 'sales', 'adjustments', 'expenses', 'users']
SHARED_TABLES = ['branches']

DELETE_ORDER = ['sale_items', 'adjustments', 'purchases', 'expenses', 'sales', 'medicines', 'users']
INSERT_ORDER = ['users', 'medicines', 'branches', 'sales', 'sale_items', 'expenses', 'purchases', 'adjustments']


def parse_backup_info(filepath):
    info = {'branch_id': None, 'branch_name': 'All Branches'}
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith('-- BRANCH_ID:'):
                    info['branch_id'] = line.split(':', 1)[1].strip()
                elif line.startswith('-- BRANCH_NAME:'):
                    info['branch_name'] = line.split(':', 1)[1].strip()
                elif not line.startswith('--'):
                    break
    except Exception:
        pass
    return info


@app.route('/backup')
@admin_required
def backup_database():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    bid = get_branch_id()
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d_%H-%M-%S')

    branch_name = 'AllBranches'
    if bid:
        conn = get_db()
        cur = dict_query(conn, "SELECT name FROM branches WHERE id=%s", (bid,))
        b = cur.fetchone()
        cur.close()
        conn.close()
        if b:
            branch_name = b['name'].replace(' ', '_')

    filename = f'pharmcare_{branch_name}_{timestamp}.sql'
    filepath = os.path.join(BACKUP_DIR, filename)

    conn = get_db()
    cur = conn.cursor()

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(f'-- PharmaCare Database Backup\n')
        f.write(f'-- BRANCH_ID: {bid or 0}\n')
        f.write(f'-- BRANCH_NAME: {branch_name}\n')
        f.write(f'-- Generated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")} UTC\n\n')

        f.write('DO $$ BEGIN SET session_replication_role = \'replica\'; EXCEPTION WHEN OTHERS THEN NULL; END $$;\n\n')

        all_data = {}

        all_tables = list(dict.fromkeys(DELETE_ORDER + BRANCH_TABLES))
        for table in all_tables:
            if table == 'sale_items':
                cur.execute("""SELECT si.* FROM sale_items si
                    JOIN sales s ON si.sale_id = s.id""" + (" WHERE s.branch_id = %s" if bid else ""),
                    (bid,) if bid else ())
            elif bid:
                cur.execute(f"SELECT * FROM {table} WHERE branch_id = %s", (bid,))
            else:
                cur.execute(f"SELECT * FROM {table}")
            rows = cur.fetchall()
            cols = [desc[0] for desc in cur.description] if rows else []
            all_data[table] = (rows, cols)

        f.write('-- DELETE PHASE (children first)\n')
        for table in DELETE_ORDER:
            rows, cols = all_data.get(table, ([], []))
            if not rows:
                continue
            if bid and table != 'sale_items':
                f.write(f"DELETE FROM {table} WHERE branch_id = {bid};\n")
            elif table == 'sale_items':
                f.write(f"DELETE FROM sale_items WHERE sale_id IN (SELECT id FROM sales WHERE branch_id = {bid});\n") if bid else f.write(f"DELETE FROM sale_items;\n")
            else:
                f.write(f"DELETE FROM {table};\n")

        f.write('\n-- INSERT PHASE (parents first)\n')
        for table in INSERT_ORDER:
            rows, cols = all_data.get(table, ([], []))
            if not rows:
                f.write(f'-- {table}: (empty)\n')
                continue
            if not bid:
                f.write(f"ALTER SEQUENCE {table}_id_seq RESTART WITH 1;\n")
            for row in rows:
                values = []
                for val in row:
                    if val is None:
                        values.append('NULL')
                    elif isinstance(val, bool):
                        values.append('TRUE' if val else 'FALSE')
                    elif isinstance(val, (int, float)):
                        values.append(str(val))
                    elif hasattr(val, 'strftime'):
                        escaped = val.strftime('%Y-%m-%d %H:%M:%S').replace("'", "''")
                        values.append(f"'{escaped}'")
                    else:
                        escaped = str(val).replace("'", "''")
                        values.append(f"'{escaped}'")
                cols_str = ', '.join(cols)
                vals_str = ', '.join(values)
                f.write(f"INSERT INTO {table} ({cols_str}) VALUES ({vals_str});\n")
            f.write('\n')

        f.write('\nDO $$ BEGIN SET session_replication_role = \'origin\'; EXCEPTION WHEN OTHERS THEN NULL; END $$;\n')

    cur.close()
    conn.close()

    size = os.path.getsize(filepath)
    if size > 1024 * 1024:
        size_str = f'{size / (1024*1024):.1f} MB'
    elif size > 1024:
        size_str = f'{size / 1024:.1f} KB'
    else:
        size_str = f'{size} B'

    flash(f'Backup created: {filename} ({size_str})', 'success')
    return send_file(filepath, as_attachment=True, download_name=filename)


@app.route('/backup/download/<filename>')
@admin_required
def download_backup(filename):
    if '..' in filename or '/' in filename or '\\' in filename:
        flash('Invalid filename', 'error')
        return redirect(url_for('settings'))
    filepath = os.path.join(BACKUP_DIR, filename)
    if not os.path.exists(filepath):
        flash('Backup not found', 'error')
        return redirect(url_for('settings'))
    return send_file(filepath, as_attachment=True, download_name=filename)


@app.route('/backup/delete/<filename>', methods=['POST'])
@admin_required
def delete_backup(filename):
    if '..' in filename or '/' in filename or '\\' in filename:
        flash('Invalid filename', 'error')
        return redirect(url_for('settings'))
    filepath = os.path.join(BACKUP_DIR, filename)
    if os.path.exists(filepath):
        os.remove(filepath)
        flash(f'Backup deleted: {filename}', 'success')
    else:
        flash('Backup not found', 'error')
    return redirect(url_for('settings'))


@app.route('/backup/restore/<filename>', methods=['POST'])
@admin_required
def restore_backup(filename):
    if '..' in filename or '/' in filename or '\\' in filename:
        flash('Invalid filename', 'error')
        return redirect(url_for('settings'))
    filepath = os.path.join(BACKUP_DIR, filename)
    if not os.path.exists(filepath):
        flash('Backup not found', 'error')
        return redirect(url_for('settings'))

    info = parse_backup_info(filepath)
    backup_branch_id = int(info['branch_id']) if info['branch_id'] and info['branch_id'] != '0' else None

    conn = get_db()
    cur = conn.cursor()
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            sql = f.read()
        statements = [s.strip() for s in sql.split(';') if s.strip() and not s.strip().startswith('--')]
        executed = 0
        for stmt in statements:
            try:
                cur.execute(stmt)
                executed += 1
            except Exception as e:
                conn.rollback()
                flash(f'Error on statement {executed + 1}: {str(e)[:200]}', 'error')
                cur.close()
                conn.close()
                return redirect(url_for('settings'))
        conn.commit()
        label = info['branch_name'] if backup_branch_id else 'ALL branches'
        flash(f'Restored "{label}" from: {filename} ({executed} statements OK)', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Restore failed: {str(e)}', 'error')
    finally:
        cur.close()
        conn.close()
    return redirect(url_for('settings'))


@app.route('/backup/upload', methods=['POST'])
@admin_required
def upload_restore():
    if 'backup_file' not in request.files:
        flash('No file selected', 'error')
        return redirect(url_for('settings'))
    file = request.files['backup_file']
    if not file.filename or not file.filename.endswith('.sql'):
        flash('Please select a valid .sql backup file', 'error')
        return redirect(url_for('settings'))

    os.makedirs(BACKUP_DIR, exist_ok=True)
    filename = file.filename
    filepath = os.path.join(BACKUP_DIR, filename)
    file.save(filepath)

    info = parse_backup_info(filepath)

    conn = get_db()
    cur = conn.cursor()
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            sql = f.read()
        statements = [s.strip() for s in sql.split(';') if s.strip() and not s.strip().startswith('--')]
        executed = 0
        for stmt in statements:
            try:
                cur.execute(stmt)
                executed += 1
            except Exception as e:
                conn.rollback()
                os.remove(filepath)
                flash(f'Error on statement {executed + 1}: {str(e)[:200]}', 'error')
                cur.close()
                conn.close()
                return redirect(url_for('settings'))
        conn.commit()
        label = info['branch_name'] if info['branch_id'] and info['branch_id'] != '0' else 'ALL branches'
        flash(f'Restored "{label}" from upload: {filename} ({executed} statements OK)', 'success')
    except Exception as e:
        conn.rollback()
        os.remove(filepath)
        flash(f'Restore failed: {str(e)}. File removed.', 'error')
    finally:
        cur.close()
        conn.close()
    return redirect(url_for('settings'))


@app.route('/settings')
@admin_required
def settings():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    backups = []
    for f in sorted(os.listdir(BACKUP_DIR), reverse=True):
        if f.endswith('.sql'):
            fpath = os.path.join(BACKUP_DIR, f)
            size = os.path.getsize(fpath)
            if size > 1024 * 1024:
                size_str = f'{size / (1024*1024):.1f} MB'
            elif size > 1024:
                size_str = f'{size / 1024:.1f} KB'
            else:
                size_str = f'{size} B'
            mtime = datetime.fromtimestamp(os.path.getmtime(fpath), tz=timezone.utc)
            info = parse_backup_info(fpath)
            backups.append({
                'name': f,
                'size': size_str,
                'date': mtime.strftime('%Y-%m-%d %H:%M'),
                'branch_name': info['branch_name'],
                'branch_id': info['branch_id']
            })
    return render_template('settings.html', backups=backups)


@app.route('/purchases')
@login_required
def purchases():
    conn = get_db()
    bid = get_branch_id()
    bfilter = "WHERE p.branch_id=%s" if bid else ""
    bargs = (bid,) if bid else ()
    cur = dict_query(conn, f"""
        SELECT p.*, m.name as medicine_name, m.buying_price
        FROM purchases p JOIN medicines m ON p.medicine_id = m.id
        {bfilter}
        ORDER BY p.created_at DESC
    """, (*bargs,))
    all_purchases = cur.fetchall()
    cur.close()
    cur = dict_query(conn, f"SELECT id, name, buying_price FROM medicines WHERE 1=1 {('AND branch_id=%s' if bid else '')} ORDER BY name", (*bargs,))
    meds = cur.fetchall()
    cur.close()
    cur = dict_query(conn, f"SELECT COALESCE(SUM(quantity * unit_cost), 0) as val FROM purchases {'WHERE branch_id=%s' if bid else ''}", (*bargs,))
    total_spent = cur.fetchone()['val']
    cur.close()
    conn.close()
    return render_template('purchases.html', purchases=all_purchases, medicines=meds, total_spent=total_spent)


@app.route('/purchases/add', methods=['POST'])
@login_required
def add_purchase():
    med_id = int(request.form['medicine_id'])
    qty = int(request.form['quantity'])
    unit_cost = float(request.form['unit_cost'])
    supplier = request.form.get('supplier', '')
    notes = request.form.get('notes', '')

    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO purchases (medicine_id, quantity, unit_cost, supplier, notes, branch_id) VALUES (%s, %s, %s, %s, %s, %s)",
                (med_id, qty, unit_cost, supplier, notes, get_branch_id()))
    cur.execute("UPDATE medicines SET stock_qty = stock_qty + %s, purchase_date = CURRENT_DATE::text WHERE id = %s", (qty, med_id))
    conn.commit()
    cur.close()
    conn.close()
    flash(f'Stock purchased: {qty} units added', 'success')
    return redirect(url_for('purchases'))


@app.route('/adjustments')
@login_required
def adjustments():
    conn = get_db()
    bid = get_branch_id()
    bfilter = "WHERE a.branch_id=%s" if bid else ""
    bargs = (bid,) if bid else ()
    cur = dict_query(conn, f"""
        SELECT a.*, m.name as medicine_name, u.full_name as user_name
        FROM adjustments a JOIN medicines m ON a.medicine_id = m.id
        LEFT JOIN users u ON a.user_id = u.id
        {bfilter}
        ORDER BY a.created_at DESC
    """, (*bargs,))
    all_adj = cur.fetchall()
    cur.close()
    cur = dict_query(conn, f"SELECT id, name, stock_qty FROM medicines WHERE 1=1 {('AND branch_id=%s' if bid else '')} ORDER BY name", (*bargs,))
    meds = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('adjustments.html', adjustments=all_adj, medicines=meds)


@app.route('/adjustments/add', methods=['POST'])
@login_required
def add_adjustment():
    med_id = int(request.form['medicine_id'])
    qty_changed = int(request.form['quantity_changed'])
    reason = request.form['reason']
    notes = request.form.get('notes', '')

    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO adjustments (medicine_id, quantity_changed, reason, notes, user_id, branch_id) VALUES (%s, %s, %s, %s, %s, %s)",
                (med_id, qty_changed, reason, notes, session['user_id'], get_branch_id()))
    cur.execute("UPDATE medicines SET stock_qty = stock_qty + %s WHERE id = %s", (qty_changed, med_id))
    conn.commit()
    cur.close()
    conn.close()
    flash(f'Stock adjusted by {qty_changed} units', 'success')
    return redirect(url_for('adjustments'))


@app.route('/expenses')
@login_required
def expenses():
    conn = get_db()
    bid = get_branch_id()
    bfilter = "AND e.branch_id=%s" if bid else ""
    sbfilter = "AND branch_id=%s" if bid else ""
    bargs = (bid,) if bid else ()
    cur = dict_query(conn, f"""
        SELECT e.*, u.full_name as user_name FROM expenses e
        LEFT JOIN users u ON e.user_id = u.id
        WHERE 1=1 {bfilter}
        ORDER BY e.created_at DESC
    """, (*bargs,))
    all_expenses = cur.fetchall()
    cur.close()
    cur = dict_query(conn, f"SELECT COALESCE(SUM(amount),0) as val FROM expenses WHERE expense_date = CURRENT_DATE {sbfilter}", (*bargs,))
    today_exp = cur.fetchone()['val']
    cur.close()
    cur = dict_query(conn, f"SELECT COALESCE(SUM(amount),0) as val FROM expenses WHERE expense_date >= (CURRENT_DATE - INTERVAL '30 days') {sbfilter}", (*bargs,))
    month_exp = cur.fetchone()['val']
    cur.close()
    conn.close()
    return render_template('expenses.html', expenses=all_expenses, today_expenses=today_exp, month_expenses=month_exp)


@app.route('/expenses/add', methods=['POST'])
@login_required
def add_expense():
    category = request.form['category'].strip()
    description = request.form.get('description', '').strip()
    amount = float(request.form['amount'])
    expense_date = request.form.get('expense_date') or datetime.now(timezone.utc).strftime('%Y-%m-%d')
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO expenses (category, description, amount, expense_date, branch_id, user_id) VALUES (%s, %s, %s, %s, %s, %s)",
                (category, description, amount, expense_date, get_branch_id(), session['user_id']))
    conn.commit()
    cur.close()
    conn.close()
    flash('Expense added!', 'success')
    return redirect(url_for('expenses'))


@app.route('/expenses/delete/<int:id>', methods=['POST'])
@login_required
def delete_expense(id):
    bid = get_branch_id()
    conn = get_db()
    cur = conn.cursor()
    if bid is not None:
        cur.execute("DELETE FROM expenses WHERE id=%s AND branch_id=%s", (id, bid))
    else:
        cur.execute("DELETE FROM expenses WHERE id=%s", (id,))
    conn.commit()
    cur.close()
    conn.close()
    flash('Expense deleted.', 'success')
    return redirect(url_for('expenses'))


@app.route('/branches')
@admin_required
def branches():
    conn = get_db()
    cur = dict_query(conn, "SELECT * FROM branches ORDER BY created_at DESC")
    all_branches = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('branches.html', branches=all_branches)


@app.route('/branches/add', methods=['POST'])
@admin_required
def add_branch():
    name = request.form['name'].strip()
    location = request.form.get('location', '').strip()
    phone = request.form.get('phone', '').strip()
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO branches (name, location, phone) VALUES (%s, %s, %s)", (name, location, phone))
    conn.commit()
    cur.close()
    conn.close()
    flash('Branch added!', 'success')
    return redirect(url_for('branches'))


@app.route('/branches/delete/<int:id>', methods=['POST'])
@admin_required
def delete_branch(id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM branches WHERE id=%s", (id,))
    conn.commit()
    cur.close()
    conn.close()
    flash('Branch deleted.', 'success')
    return redirect(url_for('branches'))


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 7860))
    app.run(debug=False, host='0.0.0.0', port=port)
