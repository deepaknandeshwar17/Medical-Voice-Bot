"""Populates clinic.db with sample doctors, slots, appointments, refill requests.

Run from repo root: python backend/scripts/seed_db.py
Safe to re-run — drops and recreates all tables each time.
"""
import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = REPO_ROOT / "backend" / "data" / "clinic.db"
DOCTORS_JSON = REPO_ROOT / "backend" / "data" / "clinic_kb" / "doctors.json"

SLOT_TIMES = ["09:00", "10:00", "11:00", "14:00", "15:00", "16:00"]
DAYS_AHEAD = 14

SCHEMA = """
CREATE TABLE doctors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    specialty TEXT NOT NULL,
    available_days TEXT NOT NULL
);

CREATE TABLE slots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doctor_id INTEGER NOT NULL REFERENCES doctors(id),
    date TEXT NOT NULL,
    time TEXT NOT NULL,
    is_booked INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doctor_id INTEGER NOT NULL REFERENCES doctors(id),
    date TEXT NOT NULL,
    time TEXT NOT NULL,
    patient_name TEXT NOT NULL,
    patient_phone TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'confirmed'
);

CREATE TABLE refill_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_name TEXT NOT NULL,
    medicine_name TEXT NOT NULL,
    doctor_name TEXT,
    status TEXT NOT NULL DEFAULT 'pending review',
    created_at TEXT NOT NULL
);
"""


def main():
    doctors = json.loads(DOCTORS_JSON.read_text(encoding="utf-8"))

    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        DROP TABLE IF EXISTS slots;
        DROP TABLE IF EXISTS appointments;
        DROP TABLE IF EXISTS refill_requests;
        DROP TABLE IF EXISTS doctors;
    """)
    conn.executescript(SCHEMA)

    doctor_ids = []
    for doc in doctors:
        cur = conn.execute(
            "INSERT INTO doctors (name, specialty, available_days) VALUES (?, ?, ?)",
            (doc["name"], doc["specialty"], json.dumps(doc["available_days"])),
        )
        doctor_ids.append((cur.lastrowid, doc["available_days"]))

    today = date.today()
    slot_rows = []
    for doctor_id, available_days in doctor_ids:
        for offset in range(DAYS_AHEAD):
            d = today + timedelta(days=offset)
            if d.strftime("%A") in available_days:
                for t in SLOT_TIMES:
                    slot_rows.append((doctor_id, d.isoformat(), t, 0))
    conn.executemany(
        "INSERT INTO slots (doctor_id, date, time, is_booked) VALUES (?, ?, ?, ?)",
        slot_rows,
    )

    conn.commit()
    n_doctors = len(doctor_ids)
    n_slots = len(slot_rows)
    conn.close()
    print(f"Seeded {DB_PATH}: {n_doctors} doctors, {n_slots} slots, 0 appointments, 0 refill requests.")


if __name__ == "__main__":
    main()
