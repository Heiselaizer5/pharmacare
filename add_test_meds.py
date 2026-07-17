import psycopg

DATABASE_URL = 'postgresql://neondb_owner:npg_8Q7zjucTVLZn@ep-super-hat-aziy97vt.c-3.ap-southeast-1.aws.neon.tech/neondb?sslmode=require'

conn = psycopg.connect(DATABASE_URL)
cur = conn.cursor()

meds = [
    ('Paracetamol 500mg', 'Painkiller', 'Pain and fever relief tablet', 500, 1000, 100, '2027-12-31', '2026-01-15', 1),
    ('Amoxicillin 500mg', 'Antibiotic', 'Broad-spectrum antibiotic capsule', 1500, 3000, 50, '2026-09-30', '2026-02-10', 1),
    ('Cetirizine 10mg', 'Antihistamine', 'Allergy relief tablet', 300, 800, 120, '2028-05-15', '2026-03-05', 1),
    ('Panadol Extra', 'Painkiller', 'Extra strength pain relief', 600, 1200, 80, '2027-06-20', '2026-01-20', 1),
    ('Azithromycin 250mg', 'Antibiotic', 'Macrolide antibiotic', 2000, 4500, 30, '2026-11-15', '2026-02-28', 1),
]

for m in meds:
    cur.execute("INSERT INTO medicines (name, category, description, buying_price, selling_price, stock_qty, expiry_date, purchase_date, branch_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)", m)
    print(f"Added: {m[0]}")

conn.commit()
cur.close()
conn.close()
print("Done! 5 medicines added to Branch 1.")
