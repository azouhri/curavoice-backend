"""
Integration tests for Retell multi-tenant webhooks.

Tests the inbound webhook and custom function endpoints.
"""

import pytest
import json
from fastapi.testclient import TestClient
from uuid import uuid4
from unittest.mock import patch, MagicMock


@pytest.fixture
def client():
    """Create test client"""
    from app.main import app
    return TestClient(app)


@pytest.fixture
def mock_supabase():
    """Mock Supabase client"""
    with patch("app.routers.retell.supabase") as mock:
        yield mock


@pytest.fixture
def mock_settings():
    """Mock settings"""
    with patch("app.config.settings") as mock:
        mock.retell_api_key = "test_key_12345"
        mock.retell_master_agent_id = "agent_abc123"
        yield mock


class TestInboundWebhook:
    """Test suite for inbound webhook endpoint"""
    
    def test_inbound_webhook_success(self, client, mock_supabase, mock_settings):
        """Test successful inbound webhook call"""
        clinic_id = str(uuid4())
        
        # Mock clinic data
        clinic_data = {
            "id": clinic_id,
            "name": "Test Clinic",
            "address": "123 Main St",
            "phone_number": "+1234567890",
            "default_language": "en",
            "greeting_template": "Welcome to Test Clinic"
        }
        
        # Mock doctors data
        doctors_data = [
            {"id": str(uuid4()), "name": "Smith", "title": "Dr.", "specialty": "General", "is_active": True},
            {"id": str(uuid4()), "name": "Jones", "title": "Dr.", "specialty": "Pediatrics", "is_active": True}
        ]
        
        # Configure mocks
        mock_supabase.table().select().eq().single().execute.return_value = MagicMock(data=clinic_data)
        mock_supabase.table().select().eq().eq().limit().execute.return_value = MagicMock(data=doctors_data)
        
        # Make request
        response = client.post(
            f"/api/retell/inbound/{clinic_id}",
            json={
                "call_id": "call_123",
                "from_number": "+1999888777",
                "to_number": "+1234567890"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["agent_id"] == "agent_abc123"
        assert "retell_llm_dynamic_variables" in data
        
        variables = data["retell_llm_dynamic_variables"]
        assert variables["clinic_id"] == clinic_id
        assert variables["clinic_name"] == "Test Clinic"
        assert variables["language"] == "en"
        assert "Dr. Smith" in variables["available_doctors"]
        assert "Dr. Jones" in variables["available_doctors"]
    
    def test_inbound_webhook_clinic_not_found_fallback(self, client, mock_supabase, mock_settings):
        """Test inbound webhook with non-existent clinic returns fallback"""
        clinic_id = str(uuid4())
        
        # Mock clinic not found
        mock_supabase.table().select().eq().single().execute.side_effect = Exception("Not found")
        
        # Mock get_clinic_by_phone also returns None
        with patch("app.routers.retell.get_clinic_by_phone", return_value=None):
            response = client.post(
                f"/api/retell/inbound/{clinic_id}",
                json={
                    "call_id": "call_123",
                    "from_number": "+1999888777",
                    "to_number": "+1234567890"
                }
            )
        
        assert response.status_code == 200
        data = response.json()
        
        # Should return fallback data
        assert data["agent_id"] == "agent_abc123"
        variables = data["retell_llm_dynamic_variables"]
        assert variables["clinic_name"] == "Our Medical Clinic"
        assert variables["error_mode"] == "true"
    
    def test_inbound_webhook_phone_fallback(self, client, mock_supabase, mock_settings):
        """Test inbound webhook falls back to phone lookup when clinic_id fails"""
        clinic_id = str(uuid4())
        to_number = "+1234567890"
        
        # Mock clinic not found by ID
        mock_supabase.table().select().eq().single().execute.side_effect = Exception("Not found")
        
        # Mock successful phone lookup
        clinic_data = {
            "id": clinic_id,
            "name": "Phone Lookup Clinic",
            "address": "456 Oak St",
            "phone_number": to_number,
            "default_language": "fr",
            "greeting_template": "Bonjour!"
        }
        
        with patch("app.routers.retell.get_clinic_by_phone", return_value=clinic_data):
            # Reset mock for second attempt
            mock_supabase.table().select().eq().eq().limit().execute.return_value = MagicMock(data=[])
            
            response = client.post(
                f"/api/retell/inbound/{clinic_id}",
                json={
                    "call_id": "call_123",
                    "from_number": "+1999888777",
                    "to_number": to_number
                }
            )
        
        assert response.status_code == 200
        data = response.json()
        
        variables = data["retell_llm_dynamic_variables"]
        assert variables["clinic_name"] == "Phone Lookup Clinic"
        assert variables["language"] == "fr"


class TestMultiTenantFunctions:
    """Test suite for multi-tenant custom function endpoints"""
    
    def test_check_availability_multitenant(self, client):
        """Test check_availability with clinic_id in args"""
        clinic_id = str(uuid4())
        doctor_id = str(uuid4())
        
        with patch("app.routers.retell.check_doctor_availability") as mock_check:
            mock_check.return_value = [
                {"time": "09:00", "available": True},
                {"time": "10:00", "available": True}
            ]
            
            response = client.post(
                "/api/retell/functions/check_availability",
                json={
                    "args": {
                        "clinic_id": clinic_id,
                        "doctor_id": doctor_id,
                        "date": "2026-01-15",
                        "language": "en"
                    }
                }
            )
        
        assert response.status_code == 200
        data = response.json()
        assert "Available times" in data["result"]
    
    def test_check_availability_missing_clinic_id(self, client):
        """Test check_availability without clinic_id returns error message"""
        response = client.post(
            "/api/retell/functions/check_availability",
            json={
                "args": {
                    "doctor_id": str(uuid4()),
                    "date": "2026-01-15"
                }
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "trouble" in data["result"].lower()
    
    def test_book_appointment_multitenant(self, client):
        """Test book_appointment with clinic_id in args"""
        clinic_id = str(uuid4())
        doctor_id = str(uuid4())
        
        with patch("app.routers.retell.book_appointment") as mock_book:
            mock_book.return_value = {
                "success": True,
                "appointment_id": str(uuid4())
            }
            
            response = client.post(
                "/api/retell/functions/book_appointment",
                json={
                    "args": {
                        "clinic_id": clinic_id,
                        "doctor_id": doctor_id,
                        "date": "2026-01-15",
                        "time": "10:00",
                        "patient_name": "John Doe",
                        "patient_phone": "+1555123456",
                        "reason": "Checkup",
                        "language": "en"
                    }
                }
            )
        
        assert response.status_code == 200
        data = response.json()
        assert "booked" in data["result"].lower()
    
    def test_book_appointment_missing_parameters(self, client):
        """Test book_appointment with missing required parameters"""
        response = client.post(
            "/api/retell/functions/book_appointment",
            json={
                "args": {
                    "clinic_id": str(uuid4()),
                    "doctor_id": str(uuid4())
                    # Missing date, time, patient info
                }
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "need" in data["result"].lower()
    
    def test_get_clinic_info_multitenant(self, client, mock_supabase):
        """Test get_clinic_info with clinic_id in args"""
        clinic_id = str(uuid4())
        
        # Mock clinic data
        clinic_data = {
            "id": clinic_id,
            "name": "Test Clinic",
            "business_hours": "9 AM - 5 PM"
        }
        
        mock_supabase.table().select().eq().single().execute.return_value = MagicMock(data=clinic_data)
        
        response = client.post(
            "/api/retell/functions/get_clinic_info",
            json={
                "args": {
                    "clinic_id": clinic_id,
                    "info_type": "hours"
                }
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "result" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

