"""Integration tests for Vapi webhook handlers"""

import pytest
from fastapi.testclient import TestClient
from app.main import app
from uuid import uuid4
import json

client = TestClient(app)


def test_function_call_webhook_check_availability():
    """Test function-call webhook for check_availability"""
    clinic_id = str(uuid4())
    
    payload = {
        "message": {
            "type": "function-call",
            "functionCall": {
                "name": "check_availability",
                "parameters": {
                    "doctor_id": str(uuid4()),
                    "date": "2026-01-10"
                }
            },
            "call": {
                "metadata": {
                    "clinic_id": clinic_id
                }
            }
        }
    }
    
    # This will fail until webhook handler is implemented
    response = client.post(
        "/api/vapi/webhook",
        json=payload,
        headers={"x-vapi-secret": "test-secret"}
    )
    
    assert response.status_code == 200
    assert "result" in response.json()


def test_function_call_webhook_book_appointment():
    """Test function-call webhook for book_appointment"""
    clinic_id = str(uuid4())
    
    payload = {
        "message": {
            "type": "function-call",
            "functionCall": {
                "name": "book_appointment",
                "parameters": {
                    "doctor_id": str(uuid4()),
                    "date": "2026-01-10",
                    "time": "10:00",
                    "patient_name": "Test Patient",
                    "patient_phone": "+2348012345678"
                }
            },
            "call": {
                "metadata": {
                    "clinic_id": clinic_id
                }
            }
        }
    }
    
    response = client.post(
        "/api/vapi/webhook",
        json=payload,
        headers={"x-vapi-secret": "test-secret"}
    )
    
    assert response.status_code == 200
    result = response.json()
    assert "result" in result
    assert result["result"]["success"] is True


def test_webhook_secret_verification():
    """Test that webhook rejects requests without valid secret"""
    payload = {
        "message": {
            "type": "function-call",
            "functionCall": {
                "name": "check_availability",
                "parameters": {}
            }
        }
    }
    
    # Request without secret should fail
    response = client.post("/api/vapi/webhook", json=payload)
    assert response.status_code == 401


def test_call_ended_webhook():
    """Test call-ended webhook handler"""
    clinic_id = str(uuid4())
    
    payload = {
        "message": {
            "type": "end-of-call-report",
            "call": {
                "id": "test-call-id",
                "metadata": {
                    "clinic_id": clinic_id
                },
                "from": "+2348012345678",
                "to": "+2348098765432",
                "startedAt": "2026-01-06T10:00:00Z",
                "endedAt": "2026-01-06T10:05:00Z",
                "duration": 300
            },
            "transcript": "Test conversation transcript",
            "summary": "Test call summary",
            "cost": 0.05
        }
    }
    
    response = client.post(
        "/api/vapi/webhook",
        json=payload,
        headers={"x-vapi-secret": "test-secret"}
    )
    
    assert response.status_code == 200

