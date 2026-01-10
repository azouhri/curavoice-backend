"""Integration tests for appointment booking"""

import pytest
from datetime import date, time, timedelta
from uuid import uuid4
from app.services.appointments import book_appointment
from app.models.schemas import AppointmentCreate


@pytest.mark.asyncio
async def test_book_appointment_new_patient():
    """Test booking appointment for a new patient"""
    clinic_id = uuid4()
    doctor_id = uuid4()
    test_date = date.today() + timedelta(days=1)
    test_time = time(10, 0)
    
    appointment_data = AppointmentCreate(
        clinic_id=clinic_id,
        doctor_id=doctor_id,
        patient_name="John Doe",
        patient_phone="+2348012345678",
        date=test_date,
        time=test_time,
        duration_minutes=30,
    )
    
    result = await book_appointment(appointment_data)
    
    assert result["success"] is True
    assert "appointment_id" in result
    assert "message" in result


@pytest.mark.asyncio
async def test_book_appointment_existing_patient():
    """Test booking appointment for existing patient"""
    clinic_id = uuid4()
    doctor_id = uuid4()
    test_date = date.today() + timedelta(days=1)
    test_time = time(11, 0)
    
    appointment_data = AppointmentCreate(
        clinic_id=clinic_id,
        doctor_id=doctor_id,
        patient_name="Jane Smith",
        patient_phone="+2348012345679",
        date=test_date,
        time=test_time,
    )
    
    result = await book_appointment(appointment_data)
    
    assert result["success"] is True
    assert "appointment_id" in result


@pytest.mark.asyncio
async def test_book_appointment_prevent_double_booking():
    """Test that double-booking is prevented"""
    clinic_id = uuid4()
    doctor_id = uuid4()
    test_date = date.today() + timedelta(days=1)
    test_time = time(14, 0)
    
    appointment_data = AppointmentCreate(
        clinic_id=clinic_id,
        doctor_id=doctor_id,
        patient_name="Test Patient",
        patient_phone="+2348012345680",
        date=test_date,
        time=test_time,
    )
    
    # Book first appointment
    result1 = await book_appointment(appointment_data)
    assert result1["success"] is True
    
    # Try to book same slot - should fail
    result2 = await book_appointment(appointment_data)
    assert result2["success"] is False
    assert "already booked" in result2.get("message", "").lower()

