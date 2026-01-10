"""Call log service for recording voice call interactions"""

import logging
from uuid import UUID
from typing import Dict, Any, Optional
from datetime import datetime
from app.config import supabase

logger = logging.getLogger(__name__)


async def create_call_log(
    clinic_id: UUID,
    vapi_call_id: str,
    from_number: Optional[str] = None,
    to_number: Optional[str] = None,
    started_at: Optional[datetime] = None,
    ended_at: Optional[datetime] = None,
    duration_seconds: Optional[int] = None,
    transcript: Optional[str] = None,
    summary: Optional[str] = None,
    detected_language: Optional[str] = None,
    outcome: Optional[str] = None,
    cost_usd: Optional[float] = None,
    patient_id: Optional[UUID] = None,
    appointment_id: Optional[UUID] = None,
) -> Dict[str, Any]:
    """
    Create a call log entry.
    
    Args:
        clinic_id: Clinic UUID
        vapi_call_id: Vapi.ai call ID (unique)
        from_number: Caller's phone number
        to_number: Called phone number
        started_at: Call start time
        ended_at: Call end time
        duration_seconds: Call duration in seconds
        transcript: Full conversation transcript
        summary: AI-generated summary
        detected_language: Language detected during call
        outcome: Call outcome (appointment_booked, etc.)
        cost_usd: Call cost in USD
        patient_id: Associated patient UUID
        appointment_id: Associated appointment UUID
        
    Returns:
        Dict with 'success' (bool) and 'call_log_id' (UUID)
    """
    try:
        call_log_data = {
            "clinic_id": str(clinic_id),
            "vapi_call_id": vapi_call_id,
            "from_number": from_number,
            "to_number": to_number,
            "started_at": started_at.isoformat() if started_at else None,
            "ended_at": ended_at.isoformat() if ended_at else None,
            "duration_seconds": duration_seconds,
            "transcript": transcript,
            "summary": summary,
            "detected_language": detected_language,
            "outcome": outcome,
            "cost_usd": cost_usd,
            "patient_id": str(patient_id) if patient_id else None,
            "appointment_id": str(appointment_id) if appointment_id else None,
            "channel": "voice",
            "direction": "inbound",
        }
        
        response = supabase.table("call_logs").insert(call_log_data).execute()
        
        if not response.data or len(response.data) == 0:
            raise Exception("Failed to create call log")
        
        call_log_id = response.data[0]["id"]
        logger.info(f"Call log created: {call_log_id} for clinic {clinic_id}")
        
        return {
            "success": True,
            "call_log_id": call_log_id,
        }
        
    except Exception as e:
        logger.error(f"Error creating call log: {e}")
        return {
            "success": False,
            "error": str(e),
        }

