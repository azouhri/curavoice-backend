"""Pytest configuration and fixtures"""

import pytest
from app.config import supabase

@pytest.fixture
def test_clinic_id():
    """Fixture for test clinic ID"""
    # In real tests, create a test clinic and return its ID
    return "00000000-0000-0000-0000-000000000001"

@pytest.fixture
def test_doctor_id():
    """Fixture for test doctor ID"""
    return "00000000-0000-0000-0000-000000000002"

@pytest.fixture
def test_patient_phone():
    """Fixture for test patient phone"""
    return "+2348012345678"

