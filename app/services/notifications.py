"""Notification service for SMS and WhatsApp messaging"""

import logging
import httpx
from uuid import UUID
from typing import Dict, Any, Optional
from app.config import settings, supabase

logger = logging.getLogger(__name__)


async def send_sms(
    phone: str,
    message: str,
    sender_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Send SMS via Termii API.
    
    Args:
        phone: Recipient phone number
        message: Message text
        sender_id: Optional sender ID
        
    Returns:
        Dict with 'success' (bool) and 'message_id' (str) if successful
    """
    if not settings.termii_api_key:
        logger.warning("Termii API key not configured, skipping SMS")
        return {"success": False, "error": "Termii API key not configured"}
    
    try:
        # Termii v3 API endpoint for sending SMS
        url = "https://v3.api.termii.com/api/sms/send"
        
        headers = {
            "Content-Type": "application/json",
        }
        
        payload = {
            "api_key": settings.termii_api_key,
            "to": phone,
            "from": sender_id or "Curavoice",
            "sms": message,
            "type": "plain",
            "channel": "generic",
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=headers, timeout=10.0)
            response.raise_for_status()
            result = response.json()
            
            # Termii v3 API response format
            if result.get("code") == "ok" or result.get("message") == "Successfully sent":
                logger.info(f"SMS sent successfully to {phone}")
                return {
                    "success": True,
                    "message_id": result.get("message_id") or result.get("messageId"),
                }
            else:
                logger.error(f"Termii API error: {result}")
                return {
                    "success": False,
                    "error": result.get("message", "Unknown error"),
                }
                
    except Exception as e:
        logger.error(f"Error sending SMS: {e}")
        return {
            "success": False,
            "error": str(e),
        }


async def send_whatsapp(
    phone: str,
    message: str,
) -> Dict[str, Any]:
    """
    Send WhatsApp message via Termii API.
    
    Args:
        phone: Recipient phone number
        message: Message text
        
    Returns:
        Dict with 'success' (bool) and 'message_id' (str) if successful
    """
    if not settings.termii_api_key:
        logger.warning("Termii API key not configured, skipping WhatsApp")
        return {"success": False, "error": "Termii API key not configured"}
    
    try:
        # Termii v3 API endpoint for sending WhatsApp messages
        url = "https://v3.api.termii.com/api/whatsapp/send"
        
        headers = {
            "Content-Type": "application/json",
        }
        
        payload = {
            "api_key": settings.termii_api_key,
            "to": phone,
            "message": message,
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=headers, timeout=10.0)
            response.raise_for_status()
            result = response.json()
            
            # Termii v3 API response format
            if result.get("code") == "ok" or result.get("message") == "Successfully sent":
                logger.info(f"WhatsApp sent successfully to {phone}")
                return {
                    "success": True,
                    "message_id": result.get("message_id") or result.get("messageId"),
                }
            else:
                logger.error(f"Termii API error: {result}")
                return {
                    "success": False,
                    "error": result.get("message", "Unknown error"),
                }
                
    except Exception as e:
        logger.error(f"Error sending WhatsApp: {e}")
        return {
            "success": False,
            "error": str(e),
        }


def format_confirmation_message(appointment: Dict[str, Any]) -> str:
    """
    Format appointment confirmation message.
    
    Args:
        appointment: Appointment dict with nested patient, doctor, clinic
        
    Returns:
        Formatted message string
    """
    patient = appointment.get("patients", {})
    doctor = appointment.get("doctors", {})
    clinic = appointment.get("clinics", {})
    
    # Format doctor name with title
    doctor_name = f"{doctor.get('title', 'Dr.')} {doctor.get('name', 'Doctor')}"
    
    message = f"""✅ Appointment Confirmed!

Hi {patient.get('name', 'Patient')}!

Your appointment has been booked:

🏥 Clinic: {clinic.get('name', 'Clinic')}
👨‍⚕️ Doctor: {doctor_name}
📅 Date: {appointment['date']}
🕐 Time: {appointment['time']}
📍 Address: {clinic.get('address', 'TBA')}

We look forward to seeing you!

Questions? Call {clinic.get('phone_number', '')}"""
    
    return message


def format_reminder_message(appointment: Dict[str, Any]) -> str:
    """
    Format appointment reminder message.
    
    Args:
        appointment: Appointment dict with nested patient, doctor, clinic
        
    Returns:
        Formatted reminder message string
    """
    patient = appointment.get("patients", {})
    doctor = appointment.get("doctors", {})
    clinic = appointment.get("clinics", {})
    
    # Format doctor name with title
    doctor_name = f"{doctor.get('title', 'Dr.')} {doctor.get('name', 'Doctor')}"
    
    message = f"""⏰ Appointment Reminder

Hi {patient.get('name', 'Patient')}!

This is a reminder about your upcoming appointment:

🏥 Clinic: {clinic.get('name', 'Clinic')}
👨‍⚕️ Doctor: {doctor_name}
📅 Date: {appointment['date']}
🕐 Time: {appointment['time']}
📍 Address: {clinic.get('address', 'TBA')}

See you tomorrow!

Need to reschedule? Call {clinic.get('phone_number', '')}"""
    
    return message


def format_cancellation_message(appointment: Dict[str, Any]) -> str:
    """
    Format appointment cancellation confirmation message.
    
    Args:
        appointment: Appointment dict with nested patient, doctor, clinic
        
    Returns:
        Formatted cancellation message string
    """
    patient = appointment.get("patients", {})
    doctor = appointment.get("doctors", {})
    clinic = appointment.get("clinics", {})
    
    # Format doctor name with title
    doctor_name = f"{doctor.get('title', 'Dr.')} {doctor.get('name', 'Doctor')}"
    
    message = f"""❌ Appointment Cancelled

Hi {patient.get('name', 'Patient')}!

Your appointment has been cancelled:

🏥 Clinic: {clinic.get('name', 'Clinic')}
👨‍⚕️ Doctor: {doctor_name}
📅 Date: {appointment['date']}
🕐 Time: {appointment['time']}

Your appointment slot has been freed up.

Need to book a new appointment? Call {clinic.get('phone_number', '')} or call us back!"""
    
    return message


def format_reschedule_message(appointment: Dict[str, Any]) -> str:
    """
    Format appointment rescheduling confirmation message.
    
    Args:
        appointment: Appointment dict with nested patient, doctor, clinic
        
    Returns:
        Formatted rescheduling message string
    """
    patient = appointment.get("patients", {})
    doctor = appointment.get("doctors", {})
    clinic = appointment.get("clinics", {})
    
    # Format doctor name with title
    doctor_name = f"{doctor.get('title', 'Dr.')} {doctor.get('name', 'Doctor')}"
    
    message = f"""🔄 Appointment Rescheduled!

Hi {patient.get('name', 'Patient')}!

Your appointment has been rescheduled to:

🏥 Clinic: {clinic.get('name', 'Clinic')}
👨‍⚕️ Doctor: {doctor_name}
📅 NEW Date: {appointment['date']}
🕐 NEW Time: {appointment['time']}
📍 Address: {clinic.get('address', 'TBA')}

We look forward to seeing you at your new time!

Questions? Call {clinic.get('phone_number', '')}"""
    
    return message


async def send_appointment_confirmation(
    clinic_id: UUID,
    patient_id: UUID,
    appointment_id: UUID,
) -> Dict[str, Any]:
    """
    Send appointment confirmation SMS/WhatsApp to patient.
    
    Args:
        clinic_id: Clinic UUID
        patient_id: Patient UUID
        appointment_id: Appointment UUID
        
    Returns:
        Dict with 'success' (bool)
    """
    try:
        # Get appointment details
        appointment_response = (
            supabase.table("appointments")
            .select("*, patients(*), doctors(*), clinics(*)")
            .eq("id", str(appointment_id))
            .eq("clinic_id", str(clinic_id))
            .execute()
        )
        
        if not appointment_response.data or len(appointment_response.data) == 0:
            return {"success": False, "error": "Appointment not found"}
        
        appointment = appointment_response.data[0]
        patient = appointment.get("patients", {})
        clinic = appointment.get("clinics", {})
        
        # Build confirmation message
        message = format_confirmation_message(appointment)
        
        phone = patient.get("phone")
        prefers_whatsapp = patient.get("prefers_whatsapp", True)
        
        if not phone:
            return {"success": False, "error": "Patient phone number not found"}
        
        # Get clinic name for sender ID (max 11 characters for Termii)
        clinic_name = clinic.get("name", "Clinic")[:11]
        
        # Send via preferred channel
        if prefers_whatsapp:
            result = await send_whatsapp(phone, message)
        else:
            result = await send_sms(phone, message, sender_id=clinic_name)
        
        # Update appointment confirmation status
        if result.get("success"):
            supabase.table("appointments").update({
                "confirmation_sent": True,
                "confirmation_sent_at": "now()",
            }).eq("id", str(appointment_id)).execute()
        
        return result
        
    except Exception as e:
        logger.error(f"Error sending appointment confirmation: {e}")
        return {
            "success": False,
            "error": str(e),
        }


async def send_appointment_reminder(
    appointment_id: UUID,
) -> Dict[str, Any]:
    """
    Send appointment reminder SMS/WhatsApp to patient.
    
    Args:
        appointment_id: Appointment UUID
        
    Returns:
        Dict with 'success' (bool)
    """
    try:
        # Get appointment details
        appointment_response = (
            supabase.table("appointments")
            .select("*, patients(*), doctors(*), clinics(*)")
            .eq("id", str(appointment_id))
            .execute()
        )
        
        if not appointment_response.data or len(appointment_response.data) == 0:
            return {"success": False, "error": "Appointment not found"}
        
        appointment = appointment_response.data[0]
        patient = appointment.get("patients", {})
        clinic = appointment.get("clinics", {})
        
        # Check if reminder already sent
        if appointment.get("reminder_sent"):
            logger.info(f"Reminder already sent for appointment {appointment_id}")
            return {"success": True, "message": "Reminder already sent"}
        
        # Build reminder message
        message = format_reminder_message(appointment)
        
        phone = patient.get("phone")
        prefers_whatsapp = patient.get("prefers_whatsapp", True)
        
        if not phone:
            return {"success": False, "error": "Patient phone number not found"}
        
        # Get clinic name for sender ID (max 11 characters for Termii)
        clinic_name = clinic.get("name", "Clinic")[:11]
        
        # Send via preferred channel
        if prefers_whatsapp:
            result = await send_whatsapp(phone, message)
        else:
            result = await send_sms(phone, message, sender_id=clinic_name)
        
        # Update appointment reminder status
        if result.get("success"):
            supabase.table("appointments").update({
                "reminder_sent": True,
                "reminder_sent_at": "now()",
            }).eq("id", str(appointment_id)).execute()
        
        return result
        
    except Exception as e:
        logger.error(f"Error sending appointment reminder: {e}")
        return {
            "success": False,
            "error": str(e),
        }


async def send_cancellation_confirmation(
    clinic_id: UUID,
    appointment_id: UUID,
) -> Dict[str, Any]:
    """
    Send appointment cancellation confirmation SMS/WhatsApp to patient.
    
    Args:
        clinic_id: Clinic UUID
        appointment_id: Appointment UUID
        
    Returns:
        Dict with 'success' (bool)
    """
    try:
        # Get appointment details
        appointment_response = (
            supabase.table("appointments")
            .select("*, patients(*), doctors(*), clinics(*)")
            .eq("id", str(appointment_id))
            .eq("clinic_id", str(clinic_id))
            .execute()
        )
        
        if not appointment_response.data or len(appointment_response.data) == 0:
            return {"success": False, "error": "Appointment not found"}
        
        appointment = appointment_response.data[0]
        patient = appointment.get("patients", {})
        clinic = appointment.get("clinics", {})
        
        # Build cancellation message
        message = format_cancellation_message(appointment)
        
        phone = patient.get("phone")
        prefers_whatsapp = patient.get("prefers_whatsapp", True)
        
        if not phone:
            return {"success": False, "error": "Patient phone number not found"}
        
        # Get clinic name for sender ID (max 11 characters for Termii)
        clinic_name = clinic.get("name", "Clinic")[:11]
        
        # Send via preferred channel
        if prefers_whatsapp:
            result = await send_whatsapp(phone, message)
        else:
            result = await send_sms(phone, message, sender_id=clinic_name)
        
        return result
        
    except Exception as e:
        logger.error(f"Error sending cancellation confirmation: {e}")
        return {
            "success": False,
            "error": str(e),
        }


async def send_reschedule_confirmation(
    clinic_id: UUID,
    appointment_id: UUID,
) -> Dict[str, Any]:
    """
    Send appointment rescheduling confirmation SMS/WhatsApp to patient.
    
    Args:
        clinic_id: Clinic UUID
        appointment_id: Appointment UUID
        
    Returns:
        Dict with 'success' (bool)
    """
    try:
        # Get appointment details
        appointment_response = (
            supabase.table("appointments")
            .select("*, patients(*), doctors(*), clinics(*)")
            .eq("id", str(appointment_id))
            .eq("clinic_id", str(clinic_id))
            .execute()
        )
        
        if not appointment_response.data or len(appointment_response.data) == 0:
            return {"success": False, "error": "Appointment not found"}
        
        appointment = appointment_response.data[0]
        patient = appointment.get("patients", {})
        clinic = appointment.get("clinics", {})
        
        # Build rescheduling message
        message = format_reschedule_message(appointment)
        
        phone = patient.get("phone")
        prefers_whatsapp = patient.get("prefers_whatsapp", True)
        
        if not phone:
            return {"success": False, "error": "Patient phone number not found"}
        
        # Get clinic name for sender ID (max 11 characters for Termii)
        clinic_name = clinic.get("name", "Clinic")[:11]
        
        # Send via preferred channel
        if prefers_whatsapp:
            result = await send_whatsapp(phone, message)
        else:
            result = await send_sms(phone, message, sender_id=clinic_name)
        
        return result
        
    except Exception as e:
        logger.error(f"Error sending reschedule confirmation: {e}")
        return {
            "success": False,
            "error": str(e),
        }

