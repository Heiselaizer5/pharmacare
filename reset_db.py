import psycopg
import sys

DATABASE_URL = 'postgresql://neondb_owner:npg_8Q7zjucTVLZn@ep-super-hat-aziy97vt.c-3.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&connect_timeout=30'

print("This will DELETE ALL DATA from the database!")
confirm = input("Type 'YES' to confirm: ")
if confirm != 'YES':
    print("Cancelled.")
    sys.exit()

conn = psycopg.connect(DATABASE_URL)
cur = conn.cursor()

tables = ['sale_items', 'sales', 'adjustments', 'expenses', 'purchases', 'medicines', 'users', 'branches']

for table in tables:
    cur.execute(f"DELETE FROM {table}")
    print(f"Cleared: {table}")

cur.execute("ALTER SEQUENCE users_id_seq RESTART WITH 1")
cur.execute("ALTER SEQUENCE branches_id_seq RESTART WITH 1")
cur.execute("ALTER SEQUENCE medicines_id_seq RESTART WITH 1")
cur.execute("ALTER SEQUENCE sales_id_seq RESTART WITH 1")
cur.execute("ALTER SEQUENCE sale_items_id_seq RESTART WITH 1")
cur.execute("ALTER SEQUENCE purchases_id_seq RESTART WITH 1")
cur.execute("ALTER SEQUENCE adjustments_id_seq RESTART WITH 1")
cur.execute("ALTER SEQUENCE expenses_id_seq RESTART WITH 1")
print("Reset all sequences.")

conn.commit()
cur.close()
conn.close()

print("Database reset complete! Restart dawa.py to reinitialize.")
