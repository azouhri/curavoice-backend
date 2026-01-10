"""Pydantic schemas for request/response models"""

from pydantic import BaseModel
from typing import Optional
from datetime import date, time
from uuid import UUID


# Patient schemas
class PatientBase(BaseModel):
    phone: str
    name: str
    email: Optional[str] = None
    preferred_language: str = "en"
    prefers_whatsapp: bool = True


class PatientCreate(PatientBase):
    clinic_id: UUID


class Patient(PatientBase):
    id: UUID
    clinic_id: UUID

    class Config:
        from_attributes = True


# Appointment schemas
class AppointmentBase(BaseModel):
    doctor_id: UUID
    patient_id: Optional[UUID] = None
    appointment_type_id: Optional[UUID] = None
    date: date
    time: time
    duration_minutes: int = 30
    reason: Optional[str] = None


class AppointmentCreate(AppointmentBase):
    clinic_id: UUID
    patient_name: str
    patient_phone: str


class Appointment(AppointmentBase):
    id: UUID
    clinic_id: UUID
    status: str

    class Config:
        from_attributes = True


# Availability schemas
class AvailabilityRequest(BaseModel):
    doctor_id: UUID
    date: date


class AvailabilityResponse(BaseModel):
    available: bool
    slots: list[str]  # List of time strings (HH:MM format)
    message: str


# Vapi function call schemas
class FunctionCallRequest(BaseModel):
    name: str
    parameters: dict


class FunctionCallResponse(BaseModel):
    result: dict

