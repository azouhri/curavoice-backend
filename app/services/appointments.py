"""Appointment service for booking and managing appointments"""

import logging
from datetime import date, time, datetime
from uuid import UUID
from typing import Dict, Any, Optional, List
from app.config import supabase
from app.models.schemas import AppointmentCreate
from app.services.patients import create_or_get_by_phone
from app.services.notifications import (
    send_appointment_confirmation,
    send_cancellation_confirmation,
    send_reschedule_confirmation,
)

logger = logging.getLogger(__name__)


async def book_appointment(appointment_data: AppointmentCreate) -> Dict[str, Any]:
    """
    Book an appointment for a patient.
    
    Args:
        appointment_data: Appointment creation data
        
    Returns:
        Dict with 'success' (bool), 'appointment_id' (UUID), and 'message' (str)
    """
    try:
        clinic_id = appointment_data.clinic_id
        doctor_id = appointment_data.doctor_id
        
        # Create or get patient
        patient_result = await create_or_get_by_phone(
            clinic_id=clinic_id,
            phone=appointment_data.patient_phone,
            name=appointment_data.patient_name,
            preferred_language=getattr(appointment_data, "preferred_language", "en"),
            prefers_whatsapp=getattr(appointment_data, "prefers_whatsapp", True),
        )
        
        patient_id = patient_result["id"]
        
        # Check if slot is already booked (double-booking prevention)
        existing_response = (
            supabase.table("appointments")
            .select("id")
            .eq("doctor_id", str(doctor_id))
            .eq("date", appointment_data.date.isoformat())
            .eq("time", appointment_data.time.strftime("%H:%M:%S"))
            .in_("status", ["scheduled", "confirmed"])
            .execute()
        )
        
        if existing_response.data and len(existing_response.data) > 0:
            return {
                "success": False,
                "appointment_id": None,
                "message": "This time slot is already booked",
            }
        
        # Create appointment
        appointment_record = {
            "clinic_id": str(clinic_id),
            "doctor_id": str(doctor_id),
            "patient_id": patient_id,
            "appointment_type_id": str(appointment_data.appointment_type_id) if appointment_data.appointment_type_id else None,
            "date": appointment_data.date.isoformat(),
            "time": appointment_data.time.strftime("%H:%M:%S"),
            "duration_minutes": appointment_data.duration_minutes,
            "reason": appointment_data.reason,
            "status": "scheduled",
            "created_via": "ai_voice",
        }
        
        response = supabase.table("appointments").insert(appointment_record).execute()
        
        if not response.data or len(response.data) == 0:
            raise Exception("Failed to create appointment")
        
        appointment_id = response.data[0]["id"]
        
        # Send confirmation SMS/WhatsApp (async, don't block)
        try:
            await send_appointment_confirmation(
                clinic_id=clinic_id,
                patient_id=patient_id,
                appointment_id=appointment_id,
            )
        except Exception as e:
            logger.warning(f"Failed to send confirmation SMS: {e}")
            # Don't fail the booking if SMS fails
        
        logger.info(f"Appointment booked: {appointment_id} for clinic {clinic_id}")
        
        return {
            "success": True,
            "appointment_id": appointment_id,
            "message": "Appointment booked successfully",
        }
        
    except Exception as e:
        logger.error(f"Error in book_appointment: {e}")
        return {
            "success": False,
            "appointment_id": None,
            "message": f"Error booking appointment: {str(e)}",
        }


async def cancel_appointment(
    clinic_id: UUID,
    appointment_id: UUID,
    cancellation_reason: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Cancel an appointment.
    
    Args:
        clinic_id: Clinic UUID
        appointment_id: Appointment UUID
        cancellation_reason: Optional reason for cancellation
        
    Returns:
        Dict with 'success' (bool) and 'message' (str)
    """
    try:
        # Verify appointment exists and belongs to clinic
        appointment_response = (
            supabase.table("appointments")
            .select("*, patients(phone, name, prefers_whatsapp)")
            .eq("id", str(appointment_id))
            .eq("clinic_id", str(clinic_id))
            .execute()
        )
        
        if not appointment_response.data or len(appointment_response.data) == 0:
            return {
                "success": False,
                "message": "Appointment not found",
            }
        
        appointment = appointment_response.data[0]
        
        # Check if appointment can be cancelled
        current_status = appointment.get("status")
        if current_status in ["cancelled", "completed", "no_show"]:
            return {
                "success": False,
                "message": f"Cannot cancel appointment with status: {current_status}",
            }
        
        # Update appointment status
        update_data = {
            "status": "cancelled",
            "cancellation_reason": cancellation_reason,
            "cancelled_at": datetime.now().isoformat(),
        }
        
        supabase.table("appointments").update(update_data).eq("id", str(appointment_id)).execute()
        
        # Send cancellation confirmation SMS/WhatsApp
        try:
            await send_cancellation_confirmation(
                clinic_id=clinic_id,
                appointment_id=appointment_id,
            )
        except Exception as e:
            logger.warning(f"Failed to send cancellation confirmation: {e}")
            # Don't fail the cancellation if SMS fails
        
        logger.info(f"Appointment cancelled: {appointment_id}")
        
        return {
            "success": True,
            "message": "Appointment cancelled successfully",
        }
        
    except Exception as e:
        logger.error(f"Error in cancel_appointment: {e}")
        return {
            "success": False,
            "message": f"Error cancelling appointment: {str(e)}",
        }


async def reschedule_appointment(
    clinic_id: UUID,
    appointment_id: UUID,
    new_date: date,
    new_time: time,
) -> Dict[str, Any]:
    """
    Reschedule an appointment to a new date/time.
    
    Args:
        clinic_id: Clinic UUID
        appointment_id: Appointment UUID
        new_date: New appointment date
        new_time: New appointment time
        
    Returns:
        Dict with 'success' (bool) and 'message' (str)
    """
    try:
        # Verify appointment exists and belongs to clinic
        appointment_response = (
            supabase.table("appointments")
            .select("*, patients(phone, name, prefers_whatsapp), doctors(id)")
            .eq("id", str(appointment_id))
            .eq("clinic_id", str(clinic_id))
            .execute()
        )
        
        if not appointment_response.data or len(appointment_response.data) == 0:
            return {
                "success": False,
                "message": "Appointment not found",
            }
        
        appointment = appointment_response.data[0]
        doctor_id = appointment.get("doctor_id")
        
        # Check if appointment can be rescheduled
        current_status = appointment.get("status")
        if current_status in ["cancelled", "completed", "no_show"]:
            return {
                "success": False,
                "message": f"Cannot reschedule appointment with status: {current_status}",
            }
        
        # Check if new slot is available (prevent double-booking)
        existing_response = (
            supabase.table("appointments")
            .select("id")
            .eq("doctor_id", str(doctor_id))
            .eq("date", new_date.isoformat())
            .eq("time", new_time.strftime("%H:%M:%S"))
            .in_("status", ["scheduled", "confirmed"])
            .neq("id", str(appointment_id))  # Exclude current appointment
            .execute()
        )
        
        if existing_response.data and len(existing_response.data) > 0:
            return {
                "success": False,
                "message": "The new time slot is already booked",
            }
        
        # Update appointment with new date/time
        update_data = {
            "date": new_date.isoformat(),
            "time": new_time.strftime("%H:%M:%S"),
            "rescheduled_at": datetime.now().isoformat(),
            "reminder_sent": False,  # Reset reminder flag for new date
            "reminder_sent_at": None,
        }
        
        supabase.table("appointments").update(update_data).eq("id", str(appointment_id)).execute()
        
        # Send rescheduling confirmation SMS/WhatsApp
        try:
            await send_reschedule_confirmation(
                clinic_id=clinic_id,
                appointment_id=appointment_id,
            )
        except Exception as e:
            logger.warning(f"Failed to send reschedule confirmation: {e}")
            # Don't fail the rescheduling if SMS fails
        
        logger.info(f"Appointment rescheduled: {appointment_id} to {new_date} {new_time}")
        
        return {
            "success": True,
            "message": "Appointment rescheduled successfully",
        }
        
    except Exception as e:
        logger.error(f"Error in reschedule_appointment: {e}")
        return {
            "success": False,
            "message": f"Error rescheduling appointment: {str(e)}",
        }


async def get_patient_appointments(
    clinic_id: UUID,
    patient_phone: str,
) -> Dict[str, Any]:
    """
    Get upcoming appointments for a patient by phone number.
    
    Args:
        clinic_id: Clinic UUID
        patient_phone: Patient phone number
        
    Returns:
        Dict with 'success' (bool) and 'appointments' (List)
    """
    try:
        # Find patient by phone
        patient_response = (
            supabase.table("patients")
            .select("id")
            .eq("clinic_id", str(clinic_id))
            .eq("phone", patient_phone)
            .execute()
        )
        
        if not patient_response.data or len(patient_response.data) == 0:
            return {
                "success": False,
                "message": "Patient not found",
                "appointments": [],
            }
        
        patient_id = patient_response.data[0]["id"]
        
        # Get upcoming appointments (not cancelled, not completed)
        today = datetime.now().date().isoformat()
        
        appointments_response = (
            supabase.table("appointments")
            .select("*, doctors(name, title, specialty)")
            .eq("patient_id", patient_id)
            .eq("clinic_id", str(clinic_id))
            .gte("date", today)
            .in_("status", ["scheduled", "confirmed"])
            .order("date", desc=False)
            .order("time", desc=False)
            .execute()
        )
        
        appointments = appointments_response.data or []
        
        return {
            "success": True,
            "appointments": appointments,
            "count": len(appointments),
        }
        
    except Exception as e:
        logger.error(f"Error in get_patient_appointments: {e}")
        return {
            "success": False,
            "message": f"Error fetching appointments: {str(e)}",
            "appointments": [],
        }

