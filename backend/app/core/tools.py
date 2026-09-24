"""Tier 3 tool implementations + their Claude tool-use JSON schemas.

Every function returns a plain dict — errors come back as {"error": ..., "message": ...}
rather than raising, so a bad tool call never surfaces a raw exception to the caller.
"""
import json

from app.config import REPO_ROOT
from app.services import db

TIMINGS_PATH = REPO_ROOT / "backend" / "data" / "clinic_kb" / "timings.json"
_timings = json.loads(TIMINGS_PATH.read_text(encoding="utf-8"))


def check_availability(date: str, specialty: str | None = None, doctor_name: str | None = None) -> dict:
    slots = db.find_available_slots(date=date, specialty=specialty, doctor_name=doctor_name)
    if not slots:
        return {"available": False, "slots": [], "message": f"No open slots found for {date}."}
    return {"available": True, "slots": slots}


def book_appointment(doctor_name: str, date: str, time: str, patient_name: str, patient_phone: str) -> dict:
    return db.book_appointment(doctor_name, date, time, patient_name, patient_phone)


def cancel_appointment(
    appointment_id: str | None = None,
    patient_phone: str | None = None,
    date: str | None = None,
    doctor_name: str | None = None,
) -> dict:
    appointment_id_int = int(appointment_id) if appointment_id else None
    return db.cancel_appointment(
        appointment_id=appointment_id_int, patient_phone=patient_phone, date=date, doctor_name=doctor_name
    )


def get_clinic_hours(day: str | None = None) -> dict:
    return {
        "clinic_name": _timings["clinic_name"],
        "weekday_hours": _timings["weekday_hours"],
        "sunday_hours": _timings["sunday_hours"],
        "day_queried": day,
    }


def request_prescription_refill(patient_name: str, medicine_name: str, doctor_name: str | None = None) -> dict:
    result = db.create_refill_request(patient_name, medicine_name, doctor_name)
    result["message"] = "Refill request logged for doctor review. It has NOT been approved yet."
    return result


def transfer_to_human() -> dict:
    return {"transfer": True}


TOOL_SCHEMAS = [
    {
        "name": "check_availability",
        "description": (
            "Check available appointment time slots for a given date, optionally filtered "
            "by doctor name or specialty."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "Date in YYYY-MM-DD format."},
                "specialty": {"type": "string", "description": "e.g. Pediatrics, Orthopedics, General Medicine."},
                "doctor_name": {"type": "string", "description": "e.g. Dr. Ravi Kulkarni."},
            },
            "required": ["date"],
        },
    },
    {
        "name": "book_appointment",
        "description": (
            "Book an appointment for a patient with a specific doctor, date, and time. Only call this "
            "after confirming the slot is available and the patient's details are correct."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "doctor_name": {"type": "string"},
                "date": {"type": "string", "description": "Date in YYYY-MM-DD format."},
                "time": {"type": "string", "description": "Time in HH:MM 24-hour format."},
                "patient_name": {"type": "string"},
                "patient_phone": {"type": "string"},
            },
            "required": ["doctor_name", "date", "time", "patient_name", "patient_phone"],
        },
    },
    {
        "name": "cancel_appointment",
        "description": (
            "Cancel an existing appointment, looked up either by appointment_id or by patient_phone plus date. "
            "If the caller mentioned a doctor, always pass doctor_name too — a patient can have more than one "
            "appointment on the same date with different doctors, and this disambiguates which one to cancel. "
            "If the tool returns error 'ambiguous', it means multiple appointments matched: read the candidates "
            "list back to the caller (doctor + time) and ask which one, then retry with the chosen appointment_id."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "appointment_id": {"type": "string"},
                "patient_phone": {"type": "string"},
                "date": {"type": "string", "description": "Date in YYYY-MM-DD format."},
                "doctor_name": {"type": "string", "description": "e.g. Dr. Ravi Kulkarni — pass this whenever the caller mentions a doctor."},
            },
        },
    },
    {
        "name": "get_clinic_hours",
        "description": "Get the clinic's opening hours, optionally for a specific day.",
        "input_schema": {
            "type": "object",
            "properties": {
                "day": {"type": "string", "description": "Day of week, e.g. Monday. Omit for general hours."},
            },
        },
    },
    {
        "name": "request_prescription_refill",
        "description": (
            "Log a prescription refill request for doctor review. This does NOT approve the refill — "
            "never tell the patient it has been approved."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_name": {"type": "string"},
                "medicine_name": {"type": "string"},
                "doctor_name": {"type": "string"},
            },
            "required": ["patient_name", "medicine_name"],
        },
    },
    {
        "name": "transfer_to_human",
        "description": "Transfer the call to a human front-desk staff member. Use when explicitly requested or when you cannot help.",
        "input_schema": {"type": "object", "properties": {}},
    },
]

TOOL_FUNCTIONS = {
    "check_availability": check_availability,
    "book_appointment": book_appointment,
    "cancel_appointment": cancel_appointment,
    "get_clinic_hours": get_clinic_hours,
    "request_prescription_refill": request_prescription_refill,
    "transfer_to_human": transfer_to_human,
}
