"""Thin SQLite access layer over clinic.db — one function per operation the Tier 3 tools need."""
import sqlite3
from datetime import datetime, timezone

from app.config import settings, REPO_ROOT

DB_PATH = REPO_ROOT / settings.db_path


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def find_available_slots(date: str, specialty: str | None = None, doctor_name: str | None = None) -> list[dict]:
    query = """
        SELECT slots.id, slots.date, slots.time, doctors.name AS doctor_name, doctors.specialty
        FROM slots
        JOIN doctors ON doctors.id = slots.doctor_id
        WHERE slots.date = ? AND slots.is_booked = 0
    """
    params: list = [date]
    if specialty:
        query += " AND doctors.specialty LIKE ?"
        params.append(f"%{specialty}%")
    if doctor_name:
        query += " AND doctors.name LIKE ?"
        params.append(f"%{doctor_name}%")
    query += " ORDER BY slots.time"

    conn = _connect()
    try:
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def book_appointment(doctor_name: str, date: str, time: str, patient_name: str, patient_phone: str) -> dict:
    conn = _connect()
    try:
        slot = conn.execute(
            """
            SELECT slots.id, slots.doctor_id FROM slots
            JOIN doctors ON doctors.id = slots.doctor_id
            WHERE doctors.name LIKE ? AND slots.date = ? AND slots.time = ? AND slots.is_booked = 0
            """,
            (f"%{doctor_name}%", date, time),
        ).fetchone()
        if slot is None:
            return {"error": "slot_not_found", "message": f"No open slot for {doctor_name} on {date} at {time}."}

        conn.execute("UPDATE slots SET is_booked = 1 WHERE id = ?", (slot["id"],))
        cur = conn.execute(
            """
            INSERT INTO appointments (doctor_id, date, time, patient_name, patient_phone, status)
            VALUES (?, ?, ?, ?, ?, 'confirmed')
            """,
            (slot["doctor_id"], date, time, patient_name, patient_phone),
        )
        conn.commit()
        return {
            "appointment_id": cur.lastrowid,
            "doctor_name": doctor_name,
            "date": date,
            "time": time,
            "status": "confirmed",
        }
    finally:
        conn.close()


def cancel_appointment(
    appointment_id: int | None = None,
    patient_phone: str | None = None,
    date: str | None = None,
    doctor_name: str | None = None,
) -> dict:
    conn = _connect()
    try:
        if appointment_id is not None:
            rows = conn.execute(
                "SELECT * FROM appointments WHERE id = ? AND status != 'cancelled'", (appointment_id,)
            ).fetchall()
        elif patient_phone and date:
            query = """
                SELECT appointments.*, doctors.name AS doctor_name FROM appointments
                JOIN doctors ON doctors.id = appointments.doctor_id
                WHERE appointments.patient_phone = ? AND appointments.date = ? AND appointments.status != 'cancelled'
            """
            params: list = [patient_phone, date]
            if doctor_name:
                query += " AND doctors.name LIKE ?"
                params.append(f"%{doctor_name}%")
            rows = conn.execute(query, params).fetchall()
        else:
            return {"error": "missing_lookup", "message": "Provide appointment_id, or patient_phone and date."}

        if not rows:
            return {"error": "not_found", "message": "No matching active appointment found."}

        if len(rows) > 1:
            # Multiple active appointments match phone+date — cancelling one arbitrarily
            # would risk cancelling the wrong one. Surface the options instead of guessing.
            candidates = [
                {"appointment_id": r["id"], "doctor_name": r["doctor_name"], "time": r["time"]} for r in rows
            ]
            return {
                "error": "ambiguous",
                "message": "More than one active appointment matches. Ask which one, then retry with appointment_id or doctor_name.",
                "candidates": candidates,
            }

        row = rows[0]
        conn.execute("UPDATE appointments SET status = 'cancelled' WHERE id = ?", (row["id"],))
        conn.execute(
            "UPDATE slots SET is_booked = 0 WHERE doctor_id = ? AND date = ? AND time = ?",
            (row["doctor_id"], row["date"], row["time"]),
        )
        conn.commit()
        return {"appointment_id": row["id"], "status": "cancelled"}
    finally:
        conn.close()


def create_refill_request(patient_name: str, medicine_name: str, doctor_name: str | None = None) -> dict:
    conn = _connect()
    try:
        cur = conn.execute(
            """
            INSERT INTO refill_requests (patient_name, medicine_name, doctor_name, status, created_at)
            VALUES (?, ?, ?, 'pending review', ?)
            """,
            (patient_name, medicine_name, doctor_name, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return {"refill_request_id": cur.lastrowid, "status": "pending review"}
    finally:
        conn.close()
