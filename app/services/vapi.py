"""Vapi.ai service for managing AI assistants"""

import logging
import httpx
import os
from uuid import UUID
from typing import Dict, Any, Optional, List
from app.config import settings, supabase

logger = logging.getLogger(__name__)


async def create_clinic_assistant(clinic_id: UUID) -> Dict[str, Any]:
    """
    Create a Vapi.ai assistant for a clinic.
    
    Args:
        clinic_id: Clinic UUID
        
    Returns:
        Dict with 'assistant_id' (str) and 'success' (bool)
    """
    if not settings.vapi_api_key:
        logger.error("Vapi API key not configured")
        return {"success": False, "error": "Vapi API key not configured"}
    
    try:
        # Get clinic data
        clinic_response = (
            supabase.table("clinics")
            .select("*")
            .eq("id", str(clinic_id))
            .execute()
        )
        
        if not clinic_response.data or len(clinic_response.data) == 0:
            return {"success": False, "error": "Clinic not found"}
        
        clinic = clinic_response.data[0]
        
        # Generate system prompt
        system_prompt = await generate_system_prompt(clinic_id)
        
        # Create assistant via Vapi API
        url = "https://api.vapi.ai/assistant"
        headers = {
            "Authorization": f"Bearer {settings.vapi_api_key}",
            "Content-Type": "application/json",
        }
        
        assistant_config = {
            "name": f"{clinic['name']} Assistant",
            "model": {
                "provider": "openai",
                "model": "gpt-4o",  # Full model - better function calling
                "temperature": 0.7,
                "messages": [
                    {
                        "role": "system",
                        "content": system_prompt
                    }
                ]
            },
            "voice": {
                "provider": "azure",
                "voiceId": "en-NG-EzinneNeural",
            },
            "transcriber": {
                "provider": "deepgram",
                "model": "nova-2",
                "language": "multi",  # Multi-language support
            },
            "firstMessage": clinic.get("greeting_template") or f"Hello! Welcome to {clinic['name']}. How can I help you today?",
            "functions": [
                {
                    "name": "check_availability",
                    "description": "Check available appointment slots for a doctor on a specific date",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "doctor_id": {
                                "type": "string",
                                "description": "UUID of the doctor"
                            },
                            "date": {
                                "type": "string",
                                "description": "Date in YYYY-MM-DD format"
                            }
                        },
                        "required": ["doctor_id", "date"]
                    }
                },
                {
                    "name": "book_appointment",
                    "description": "Book an appointment for a patient",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "doctor_id": {
                                "type": "string",
                                "description": "UUID of the doctor"
                            },
                            "date": {
                                "type": "string",
                                "description": "Date in YYYY-MM-DD format"
                            },
                            "time": {
                                "type": "string",
                                "description": "Time in HH:MM format"
                            },
                            "patient_name": {
                                "type": "string",
                                "description": "Patient's full name"
                            },
                            "patient_phone": {
                                "type": "string",
                                "description": "Patient's phone number"
                            },
                            "reason": {
                                "type": "string",
                                "description": "Reason for visit (optional)"
                            },
                            "appointment_type_id": {
                                "type": "string",
                                "description": "UUID of appointment type (optional)"
                            }
                        },
                        "required": ["doctor_id", "date", "time", "patient_name", "patient_phone"]
                    }
                },
                {
                    "name": "lookup_patient",
                    "description": "Look up patient by phone number",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "phone": {
                                "type": "string",
                                "description": "Patient's phone number"
                            }
                        },
                        "required": ["phone"]
                    }
                },
                {
                    "name": "get_clinic_info",
                    "description": "Get clinic information like hours, address, services, or doctors",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "info_type": {
                                "type": "string",
                                "description": "Type of information requested (hours, address, services, doctors)"
                            }
                        },
                        "required": ["info_type"]
                    }
                },
            ],
            "serverUrl": os.getenv("VAPI_WEBHOOK_URL", "https://api.curavoice.io/api/vapi/webhook"),
            "serverUrlSecret": settings.vapi_webhook_secret,
        }
        
        # Log the payload for debugging
        logger.info(f"Creating Vapi assistant with config: {assistant_config}")
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=assistant_config, headers=headers, timeout=30.0)
            
            # Log response for debugging
            logger.info(f"Vapi API Response Status: {response.status_code}")
            if response.status_code >= 400:
                logger.error(f"Vapi API Error Response: {response.text}")
            elif response.status_code in [200, 201]:
                logger.info(f"Vapi API Success Response: {response.text}")
            
            response.raise_for_status()
            result = response.json()
            
            assistant_id = result.get("id")
            
            # Update clinic with assistant ID
            supabase.table("clinics").update({
                "vapi_assistant_id": assistant_id,
            }).eq("id", str(clinic_id)).execute()
            
            logger.info(f"Created Vapi assistant {assistant_id} for clinic {clinic_id}")
            
            return {
                "success": True,
                "assistant_id": assistant_id,
            }
            
    except Exception as e:
        logger.error(f"Error creating Vapi assistant: {e}")
        return {
            "success": False,
            "error": str(e),
        }


async def generate_system_prompt(clinic_id: UUID) -> str:
    """
    Generate system prompt for clinic's AI assistant.
    
    Args:
        clinic_id: Clinic UUID
        
    Returns:
        System prompt string
    """
    try:
        # Get clinic data
        clinic_response = (
            supabase.table("clinics")
            .select("*")
            .eq("id", str(clinic_id))
            .execute()
        )
        
        if not clinic_response.data:
            return "You are a helpful medical clinic assistant."
        
        clinic = clinic_response.data[0]
        clinic_name = clinic.get("name", "Clinic")
        supported_languages = clinic.get("supported_languages", ["en"])
        
        # Get doctors
        doctors_response = (
            supabase.table("doctors")
            .select("name, title, specialty")
            .eq("clinic_id", str(clinic_id))
            .eq("is_active", True)
            .execute()
        )
        
        doctors = doctors_response.data or []
        doctor_list = ", ".join([f"{d.get('title', 'Dr.')} {d.get('name')}" for d in doctors])
        
        # Get appointment types
        types_response = (
            supabase.table("appointment_types")
            .select("name, duration_minutes")
            .eq("clinic_id", str(clinic_id))
            .eq("is_active", True)
            .execute()
        )
        
        appointment_types = types_response.data or []
        
        # Build multi-language prompt
        language_instructions = ""
        if "en" in supported_languages:
            language_instructions += "You can speak English. "
        if "pidgin" in supported_languages or "pcm" in supported_languages:
            language_instructions += "You can speak Nigerian Pidgin. Use casual, friendly language. "
        if "yo" in supported_languages:
            language_instructions += "You can speak Yoruba. Use respectful language. "
        if "fr" in supported_languages:
            language_instructions += "You can speak French. Use formal language. "
        if "ar" in supported_languages:
            language_instructions += "You can speak Arabic. Use respectful, formal language. "
        
        prompt = f"""You are the appointment booking assistant for {clinic_name}.

CRITICAL: You MUST use functions to get information. NEVER make up data.

When patient asks about doctors or services:
→ IMMEDIATELY call get_clinic_info function (don't just say "let me check")

When patient wants to book:
→ IMMEDIATELY call get_clinic_info to get doctor list
→ After patient chooses doctor and date: IMMEDIATELY call check_availability 
→ After patient chooses time: IMMEDIATELY call book_appointment

NEVER say "let me check" without actually calling the function.
NEVER provide appointment times without calling check_availability first.
NEVER confirm a booking without calling book_appointment.

WORKFLOW:
1. Greet: "Hello! Welcome to {clinic_name}. How can I help you?"
2. If booking:
   - Call get_clinic_info("doctors") → read real doctor names to patient
   - Get patient name (full name)
   - Get patient phone (all 10+ digits)
   - Get preferred date
   - Call check_availability(doctor_id, date) → read REAL available times
   - Get time choice
   - Call book_appointment → confirm with booking details

Language: Stay in patient's language throughout entire call.

Remember: CALL THE FUNCTION, don't just talk about calling it."""
        
        return prompt
        
    except Exception as e:
        logger.error(f"Error generating system prompt: {e}")
        return "You are a helpful medical clinic assistant."

