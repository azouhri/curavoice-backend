"""Integration tests for patient lookup by phone"""

import pytest
from uuid import uuid4
from app.services.patients import lookup_patient_by_phone


@pytest.mark.asyncio
async def test_lookup_patient_exists():
    """Test looking up an existing patient by phone"""
    clinic_id = uuid4()
    phone = "+2348012345678"
    
    result = await lookup_patient_by_phone(clinic_id, phone)
    
    assert result["found"] is True
    assert "patient" in result
    assert result["patient"]["phone"] == phone
    assert result["patient"]["clinic_id"] == str(clinic_id)


@pytest.mark.asyncio
async def test_lookup_patient_not_found():
    """Test looking up a non-existent patient"""
    clinic_id = uuid4()
    phone = "+2348099999999"
    
    result = await lookup_patient_by_phone(clinic_id, phone)
    
    assert result["found"] is False
    assert "patient" not in result or result["patient"] is None


@pytest.mark.asyncio
async def test_lookup_patient_with_appointments():
    """Test patient lookup includes upcoming appointments"""
    clinic_id = uuid4()
    phone = "+2348012345678"
    
    result = await lookup_patient_by_phone(clinic_id, phone)
    
    if result["found"]:
        assert "upcoming_appointments" in result["patient"]
        assert isinstance(result["patient"]["upcoming_appointments"], list)

