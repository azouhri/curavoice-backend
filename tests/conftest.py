"""Pytest configuration and fixtures for integration tests"""

import pytest
import os
from uuid import uuid4
from datetime import date, time, timedelta
from supabase import create_client, Client
from app.config import settings

# Test database client (uses same Supabase instance)
test_supabase: Client = create_client(
    settings.supabase_url,
    settings.supabase_service_role_key,
)


@pytest.fixture
def supabase_client():
    """Provide Supabase client for tests"""
    return test_supabase


@pytest.fixture
async def test_clinic_a(supabase_client):
    """Create test clinic A"""
    clinic_id = str(uuid4())
    clinic_data = {
        "id": clinic_id,
        "name": "Test Clinic A",
        "phone": "+2348011111111",
        "email": "clinic-a@test.com",
        "address": "123 Test Street, Lagos",
        "supported_languages": ["en", "yo", "pcm"],
        "ai_greeting": "Hello, welcome to Test Clinic A",
    }
    
    result = supabase_client.table("clinics").insert(clinic_data).execute()
    yield clinic_data
    
    # Cleanup
    try:
        supabase_client.table("clinics").delete().eq("id", clinic_id).execute()
    except Exception:
        pass


@pytest.fixture
async def test_clinic_b(supabase_client):
    """Create test clinic B"""
    clinic_id = str(uuid4())
    clinic_data = {
        "id": clinic_id,
        "name": "Test Clinic B",
        "phone": "+2348022222222",
        "email": "clinic-b@test.com",
        "address": "456 Test Avenue, Abuja",
        "supported_languages": ["en", "fr"],
        "ai_greeting": "Bonjour, bienvenue à Test Clinic B",
    }
    
    result = supabase_client.table("clinics").insert(clinic_data).execute()
    yield clinic_data
    
    # Cleanup
    try:
        supabase_client.table("clinics").delete().eq("id", clinic_id).execute()
    except Exception:
        pass


@pytest.fixture
async def test_doctor_a(supabase_client, test_clinic_a):
    """Create test doctor for clinic A"""
    doctor_id = str(uuid4())
    doctor_data = {
        "id": doctor_id,
        "clinic_id": test_clinic_a["id"],
        "name": "Dr. Test A",
        "specialty": "General Practice",
        "phone": "+2348033333333",
        "email": "doctor-a@test.com",
    }
    
    result = supabase_client.table("doctors").insert(doctor_data).execute()
    yield doctor_data
    
    # Cleanup
    try:
        supabase_client.table("doctors").delete().eq("id", doctor_id).execute()
    except Exception:
        pass


@pytest.fixture
async def test_doctor_b(supabase_client, test_clinic_b):
    """Create test doctor for clinic B"""
    doctor_id = str(uuid4())
    doctor_data = {
        "id": doctor_id,
        "clinic_id": test_clinic_b["id"],
        "name": "Dr. Test B",
        "specialty": "Cardiology",
        "phone": "+2348044444444",
        "email": "doctor-b@test.com",
    }
    
    result = supabase_client.table("doctors").insert(doctor_data).execute()
    yield doctor_data
    
    # Cleanup
    try:
        supabase_client.table("doctors").delete().eq("id", doctor_id).execute()
    except Exception:
        pass


@pytest.fixture
async def test_patient_a(supabase_client, test_clinic_a):
    """Create test patient for clinic A"""
    patient_id = str(uuid4())
    patient_data = {
        "id": patient_id,
        "clinic_id": test_clinic_a["id"],
        "name": "Patient A",
        "phone": "+2348055555555",
        "preferred_language": "en",
        "prefers_whatsapp": False,
    }
    
    result = supabase_client.table("patients").insert(patient_data).execute()
    yield patient_data
    
    # Cleanup
    try:
        supabase_client.table("patients").delete().eq("id", patient_id).execute()
    except Exception:
        pass


@pytest.fixture
async def test_patient_b(supabase_client, test_clinic_b):
    """Create test patient for clinic B"""
    patient_id = str(uuid4())
    patient_data = {
        "id": patient_id,
        "clinic_id": test_clinic_b["id"],
        "name": "Patient B",
        "phone": "+2348066666666",
        "preferred_language": "fr",
        "prefers_whatsapp": True,
    }
    
    result = supabase_client.table("patients").insert(patient_data).execute()
    yield patient_data
    
    # Cleanup
    try:
        supabase_client.table("patients").delete().eq("id", patient_id).execute()
    except Exception:
        pass


@pytest.fixture
async def test_appointment_a(supabase_client, test_clinic_a, test_doctor_a, test_patient_a):
    """Create test appointment for clinic A"""
    appointment_id = str(uuid4())
    appointment_date = date.today() + timedelta(days=1)
    appointment_data = {
        "id": appointment_id,
        "clinic_id": test_clinic_a["id"],
        "doctor_id": test_doctor_a["id"],
        "patient_id": test_patient_a["id"],
        "date": appointment_date.isoformat(),
        "time": "10:00:00",
        "duration_minutes": 30,
        "status": "scheduled",
    }
    
    result = supabase_client.table("appointments").insert(appointment_data).execute()
    yield appointment_data
    
    # Cleanup
    try:
        supabase_client.table("appointments").delete().eq("id", appointment_id).execute()
    except Exception:
        pass


@pytest.fixture
def vapi_webhook_secret():
    """Get Vapi webhook secret for tests"""
    return os.getenv("VAPI_WEBHOOK_SECRET", "test-secret")


@pytest.fixture
def tomorrow_date():
    """Get tomorrow's date for tests"""
    return date.today() + timedelta(days=1)

