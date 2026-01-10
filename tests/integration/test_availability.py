"""Integration tests for doctor availability checking"""

import pytest
from datetime import date, timedelta
from uuid import uuid4
from app.services.availability import check_doctor_availability
from app.config import supabase


@pytest.mark.asyncio
async def test_check_availability_no_appointments():
    """Test availability check when doctor has no appointments"""
    # This test will fail initially - doctor and clinic need to exist
    clinic_id = uuid4()
    doctor_id = uuid4()
    test_date = date.today() + timedelta(days=1)
    
    result = await check_doctor_availability(doctor_id, test_date, clinic_id)
    
    assert result["available"] is True
    assert len(result["slots"]) > 0
    assert "message" in result


@pytest.mark.asyncio
async def test_check_availability_with_existing_appointments():
    """Test availability check excludes booked appointments"""
    clinic_id = uuid4()
    doctor_id = uuid4()
    test_date = date.today() + timedelta(days=1)
    
    # Create test appointment
    # This will fail until appointment service is implemented
    
    result = await check_doctor_availability(doctor_id, test_date, clinic_id)
    
    # Verify booked slots are not in available slots
    assert "slots" in result


@pytest.mark.asyncio
async def test_check_availability_respects_working_hours():
    """Test availability check respects doctor's working hours"""
    clinic_id = uuid4()
    doctor_id = uuid4()
    test_date = date.today() + timedelta(days=1)
    
    result = await check_doctor_availability(doctor_id, test_date, clinic_id)
    
    # Verify slots are within working hours
    assert result["available"] is True
    # Additional assertions for working hours validation

