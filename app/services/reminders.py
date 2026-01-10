"""Appointment reminder scheduler service"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any
from app.config import supabase
from app.services.notifications import send_appointment_reminder

logger = logging.getLogger(__name__)


async def get_appointments_needing_reminders() -> List[Dict[str, Any]]:
    """
    Get appointments that need reminders sent.
    
    Finds appointments:
    - Scheduled within next 24-48 hours
    - reminder_sent is False
    - Status is 'scheduled' or 'confirmed'
    
    Returns:
        List of appointment dictionaries
    """
    try:
        # Calculate time window (24-48 hours from now)
        now = datetime.now()
        reminder_start = now + timedelta(hours=24)
        reminder_end = now + timedelta(hours=48)
        
        # Format dates for Supabase query
        start_date = reminder_start.strftime("%Y-%m-%d")
        end_date = reminder_end.strftime("%Y-%m-%d")
        
        # Query appointments in time window
        response = (
            supabase.table("appointments")
            .select("id, date, time, clinic_id, patient_id, doctor_id, reminder_sent")
            .gte("date", start_date)
            .lte("date", end_date)
            .eq("reminder_sent", False)
            .in_("status", ["scheduled", "confirmed"])
            .execute()
        )
        
        appointments = response.data or []
        logger.info(f"Found {len(appointments)} appointments needing reminders")
        
        return appointments
        
    except Exception as e:
        logger.error(f"Error getting appointments needing reminders: {e}")
        return []


async def process_reminders() -> Dict[str, Any]:
    """
    Process all pending reminders.
    
    Returns:
        Dict with 'total', 'success', 'failed' counts
    """
    try:
        appointments = await get_appointments_needing_reminders()
        
        results = {
            "total": len(appointments),
            "success": 0,
            "failed": 0,
            "errors": [],
        }
        
        for appointment in appointments:
            try:
                result = await send_appointment_reminder(appointment["id"])
                
                if result.get("success"):
                    results["success"] += 1
                    logger.info(f"Reminder sent for appointment {appointment['id']}")
                else:
                    results["failed"] += 1
                    error_msg = result.get("error", "Unknown error")
                    results["errors"].append({
                        "appointment_id": str(appointment["id"]),
                        "error": error_msg,
                    })
                    logger.error(f"Failed to send reminder for {appointment['id']}: {error_msg}")
                    
            except Exception as e:
                results["failed"] += 1
                error_msg = str(e)
                results["errors"].append({
                    "appointment_id": str(appointment["id"]),
                    "error": error_msg,
                })
                logger.error(f"Exception sending reminder for {appointment['id']}: {e}")
        
        logger.info(f"Reminder processing complete: {results['success']}/{results['total']} sent successfully")
        return results
        
    except Exception as e:
        logger.error(f"Error processing reminders: {e}")
        return {
            "total": 0,
            "success": 0,
            "failed": 0,
            "errors": [{"error": str(e)}],
        }


async def send_reminder_for_appointment(appointment_id: str) -> Dict[str, Any]:
    """
    Send reminder for a specific appointment (for testing or manual trigger).
    
    Args:
        appointment_id: Appointment UUID as string
        
    Returns:
        Dict with 'success' (bool) and optional 'error'
    """
    try:
        result = await send_appointment_reminder(appointment_id)
        return result
    except Exception as e:
        logger.error(f"Error sending reminder for appointment {appointment_id}: {e}")
        return {
            "success": False,
            "error": str(e),
        }

