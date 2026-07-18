import psycopg
from psycopg.rows import dict_row
from werkzeug.security import generate_password_hash

NEON_URL = 'postgresql://neondb_owner:npg_8Q7zjucTVLZn@ep-super-hat-aziy97vt.c-3.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&connect_timeout=60'
SUPABASE_URL = 'postgresql://postgres.oypqzvhtszdyahtrxysc:pharmadawa123@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres'

TABLES_ORDER = [
    'branches',
    'users',
    'medicines',
    'purchases',
    'sales',
    'sale_items',
    'adjustments',
    'expenses',
]

CREATE_SQL = {
    'branches': '''CREATE TABLE IF NOT EXISTS branches (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        location TEXT,
        phone TEXT,
        is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''',
    'users': '''CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        full_name TEXT NOT NULL,
        phone TEXT,
        role TEXT NOT NULL DEFAULT 'pharmacist',
        branch_id INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''',
    'medicines': '''CREATE TABLE IF NOT EXISTS medicines (
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
    )''',
    'purchases': '''CREATE TABLE IF NOT EXISTS purchases (
        id SERIAL PRIMARY KEY,
        medicine_id INTEGER,
        quantity INTEGER NOT NULL,
        unit_cost REAL NOT NULL,
        supplier TEXT,
        notes TEXT,
        branch_id INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (medicine_id) REFERENCES medicines(id)
    )''',
    'sales': '''CREATE TABLE IF NOT EXISTS sales (
        id SERIAL PRIMARY KEY,
        user_id INTEGER,
        total_amount REAL NOT NULL,
        payment_method TEXT DEFAULT 'cash',
        branch_id INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''',
    'sale_items': '''CREATE TABLE IF NOT EXISTS sale_items (
        id SERIAL PRIMARY KEY,
        sale_id INTEGER,
        medicine_id INTEGER,
        quantity INTEGER NOT NULL,
        unit_price REAL NOT NULL,
        subtotal REAL NOT NULL,
        FOREIGN KEY (sale_id) REFERENCES sales(id),
        FOREIGN KEY (medicine_id) REFERENCES medicines(id)
    )''',
    'adjustments': '''CREATE TABLE IF NOT EXISTS adjustments (
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
    )''',
    'expenses': '''CREATE TABLE IF NOT EXISTS expenses (
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
    )''',
}


def migrate():
    print("Connecting to Supabase...")
    supa = psycopg.connect(SUPABASE_URL)
    supa.autocommit = True
    scur = supa.cursor()

    print("Creating tables on Supabase...")
    for table in TABLES_ORDER:
        scur.execute(CREATE_SQL[table])
        print(f"  -> {table} created")

    print("\nConnecting to Neon...")
    neon = psycopg.connect(NEON_URL)
    neon.autocommit = True

    for table in TABLES_ORDER:
        print(f"\nMigrating: {table}")
        ncur = neon.cursor(row_factory=dict_row)
        ncur.execute(f'SELECT * FROM {table}')
        rows = ncur.fetchall()

        if not rows:
            print(f"  -> 0 rows (skipped)")
            continue

        cols = [desc.name for desc in ncur.description]
        print(f"  -> {len(rows)} rows found")

        placeholders = ','.join(['%s'] * len(cols))
        col_names = ','.join(cols)

        scur2 = supa.cursor()
        scur2.execute(f'DELETE FROM {table}')
        supa.commit()

        count = 0
        for row in rows:
            vals = []
            for v in row.values():
                if hasattr(v, 'isoformat'):
                    vals.append(v.isoformat())
                elif isinstance(v, memoryview):
                    vals.append(bytes(v))
                else:
                    vals.append(v)
            try:
                scur2.execute(f'INSERT INTO {table} ({col_names}) VALUES ({placeholders})', vals)
                count += 1
            except Exception as e:
                print(f"  ERROR: {e}")
                supa.rollback()
                break
        else:
            supa.commit()
            print(f"  -> {count} rows migrated!")

    # Reset sequences
    print("\nResetting sequences...")
    for table in TABLES_ORDER:
        try:
            scur.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), (SELECT COALESCE(MAX(id),1) FROM {table}))")
        except Exception:
            pass
    supa.commit()

    neon.close()
    supa.close()
    print("\nMigration complete!")


if __name__ == '__main__':
    migrate()
