"""Patient service for managing patient records"""

import logging
from uuid import UUID
from typing import Optional, Dict, Any
from app.config import supabase

logger = logging.getLogger(__name__)


async def create_or_get_by_phone(
    clinic_id: UUID,
    phone: str,
    name: str,
    email: Optional[str] = None,
    preferred_language: str = "en",
    prefers_whatsapp: bool = True,
) -> Dict[str, Any]:
    """
    Create a new patient or get existing patient by phone number.
    
    Args:
        clinic_id: Clinic UUID
        phone: Patient phone number
        name: Patient name
        email: Optional email
        preferred_language: Preferred language code
        prefers_whatsapp: Whether patient prefers WhatsApp
        
    Returns:
        Dict with patient data including 'id' and 'created' (bool)
    """
    try:
        # Check if patient exists
        response = (
            supabase.table("patients")
            .select("*")
            .eq("clinic_id", str(clinic_id))
            .eq("phone", phone)
            .execute()
        )
        
        if response.data and len(response.data) > 0:
            logger.info(f"Found existing patient: {phone} for clinic {clinic_id}")
            return {
                "id": response.data[0]["id"],
                "created": False,
                **response.data[0],
            }
        
        # Create new patient
        patient_data = {
            "clinic_id": str(clinic_id),
            "phone": phone,
            "name": name,
            "email": email,
            "preferred_language": preferred_language,
            "prefers_whatsapp": prefers_whatsapp,
        }
        
        response = supabase.table("patients").insert(patient_data).execute()
        
        if not response.data:
            raise Exception("Failed to create patient")
        
        logger.info(f"Created new patient: {phone} for clinic {clinic_id}")
        return {
            "id": response.data[0]["id"],
            "created": True,
            **response.data[0],
        }
        
    except Exception as e:
        logger.error(f"Error in create_or_get_by_phone: {e}")
        raise


async def lookup_patient_by_phone(
    clinic_id: UUID,
    phone: str,
) -> Dict[str, Any]:
    """
    Look up patient by phone number and return with upcoming appointments.
    
    Args:
        clinic_id: Clinic UUID
        phone: Patient phone number
        
    Returns:
        Dict with 'found' (bool), 'patient' (dict), and 'message' (str)
    """
    try:
        # Find patient
        response = (
            supabase.table("patients")
            .select("*")
            .eq("clinic_id", str(clinic_id))
            .eq("phone", phone)
            .execute()
        )
        
        if not response.data or len(response.data) == 0:
            return {
                "found": False,
                "patient": None,
                "message": "Patient not found",
            }
        
        patient = response.data[0]
        patient_id = patient["id"]
        
        # Get upcoming appointments
        appointments_response = (
            supabase.table("appointments")
            .select("*")
            .eq("clinic_id", str(clinic_id))
            .eq("patient_id", patient_id)
            .in_("status", ["scheduled", "confirmed"])
            .gte("date", "now()")
            .order("date")
            .order("time")
            .execute()
        )
        
        patient["upcoming_appointments"] = appointments_response.data or []
        
        return {
            "found": True,
            "patient": patient,
            "message": f"Found patient: {patient['name']}",
        }
        
    except Exception as e:
        logger.error(f"Error in lookup_patient_by_phone: {e}")
        return {
            "found": False,
            "patient": None,
            "message": f"Error looking up patient: {str(e)}",
        }

