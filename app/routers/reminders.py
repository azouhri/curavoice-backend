"""Appointment reminders API router"""

import logging
from fastapi import APIRouter, HTTPException
from app.services.reminders import process_reminders, send_reminder_for_appointment

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reminders", tags=["reminders"])


@router.post("/process")
async def process_reminder_queue():
    """
    Process all pending appointment reminders.
    
    This endpoint should be called by a cron job or Supabase Edge Function.
    
    Returns:
        Dict with reminder processing results
    """
    try:
        logger.info("Processing reminder queue...")
        result = await process_reminders()
        
        return {
            "status": "ok",
            "result": result,
        }
    except Exception as e:
        logger.error(f"Error processing reminders: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/send/{appointment_id}")
async def send_reminder(appointment_id: str):
    """
    Manually send reminder for a specific appointment (for testing).
    
    Args:
        appointment_id: Appointment UUID
        
    Returns:
        Dict with success status
    """
    try:
        result = await send_reminder_for_appointment(appointment_id)
        
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error", "Failed to send reminder"))
        
        return {
            "status": "ok",
            "message": "Reminder sent successfully",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending reminder: {e}")
        raise HTTPException(status_code=500, detail=str(e))

