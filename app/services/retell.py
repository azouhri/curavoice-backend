"""
Retell AI service for managing AI voice agents and phone numbers.

Architecture:
- ONE shared Conversation Flow Agent handles ALL clinics
- Each clinic gets a dedicated phone number
- Phone number metadata routes calls to the correct clinic context
"""

import logging
import httpx
from uuid import UUID
from typing import Dict, Any, Optional, List
from app.config import settings, supabase

logger = logging.getLogger(__name__)

RETELL_API_BASE = "https://api.retellai.com"


def _get_headers() -> Dict[str, str]:
    """Get Retell API headers"""
    return {
        "Authorization": f"Bearer {settings.retell_api_key}",
        "Content-Type": "application/json",
    }


# =============================================================================
# PHONE NUMBER MANAGEMENT
# =============================================================================

async def provision_phone_number(
    clinic_id: UUID,
    area_code: str = "234",  # Nigeria default
) -> Dict[str, Any]:
    """
    Provision a new phone number for a clinic from Retell.
    
    Multi-tenant architecture: Uses the MASTER agent with inbound webhook.
    
    This is called automatically when a clinic is created during onboarding.
    
    Args:
        clinic_id: UUID of the clinic
        area_code: Area code for the phone number (default: Nigeria)
        
    Returns:
        Dict with 'success', 'phone_number', 'phone_id'
    """
    if not settings.retell_api_key:
        logger.error("Retell API key not configured")
        return {"success": False, "error": "Retell API key not configured"}
    
    if not settings.retell_master_agent_id:
        logger.error("Retell master agent ID not configured")
        return {"success": False, "error": "Master agent not configured. Please create it first."}
    
    try:
        # Get clinic info
        clinic_response = (
            supabase.table("clinics")
            .select("id, name, retell_webhook_base_url")
            .eq("id", str(clinic_id))
            .single()
            .execute()
        )
        
        if not clinic_response.data:
            return {"success": False, "error": "Clinic not found"}
        
        clinic = clinic_response.data
        
        # Get webhook base URL (from clinic or settings)
        webhook_base = clinic.get("retell_webhook_base_url") or settings.webhook_base_url
        if not webhook_base:
            logger.warning(f"No webhook_base_url configured for clinic {clinic_id}, using default")
            webhook_base = "https://yourdomain.com"  # TODO: Make this configurable
        
        # Construct inbound webhook URL with clinic_id
        inbound_webhook_url = f"{webhook_base}/api/retell/inbound/{clinic_id}"
        
        async with httpx.AsyncClient() as client:
            # 1. Purchase a phone number
            buy_response = await client.post(
                f"{RETELL_API_BASE}/create-phone-number",
                headers=_get_headers(),
                json={
                    "area_code": int(area_code),
                    "nickname": f"{clinic['name']} - Main Line",
                },
                timeout=30.0,
            )
            
            if buy_response.status_code >= 400:
                logger.error(f"Failed to buy phone number: {buy_response.text}")
                return {"success": False, "error": f"Failed to provision phone: {buy_response.text}"}
            
            phone_data = buy_response.json()
            phone_number = phone_data.get("phone_number")
            phone_id = phone_data.get("phone_number_id")
            
            logger.info(f"Purchased phone number {phone_number} for clinic {clinic_id}")
            
            # 2. Link phone number to MASTER agent with inbound webhook
            link_response = await client.patch(
                f"{RETELL_API_BASE}/update-phone-number/{phone_id}",
                headers=_get_headers(),
                json={
                    "inbound_agent_id": settings.retell_master_agent_id,
                    "inbound_webhook_url": inbound_webhook_url,
                    "metadata": {
                        "clinic_id": str(clinic_id),
                        "clinic_name": clinic["name"],
                    },
                },
                timeout=30.0,
            )
            
            if link_response.status_code >= 400:
                logger.error(f"Failed to link phone to master agent: {link_response.text}")
                # Phone was purchased but not linked - log but don't fail completely
            else:
                logger.info(f"Linked phone {phone_number} to master agent with webhook: {inbound_webhook_url}")
            
            # 3. Save to database
            supabase.table("clinic_phone_numbers").insert({
                "clinic_id": str(clinic_id),
                "phone_number": phone_number,
                "retell_phone_id": phone_id,
                "retell_agent_id": settings.retell_master_agent_id,
                "webhook_url": inbound_webhook_url,
                "is_primary": True,
                "is_active": True,
            }).execute()
            
            # 4. Update clinic record with phone number ID
            supabase.table("clinics").update({
                "retell_phone_number_id": phone_id,
                "phone_number": phone_number,  # Also update the main phone_number field
            }).eq("id", str(clinic_id)).execute()
            
            logger.info(f"Phone {phone_number} provisioned and linked for clinic {clinic_id}")
            
            return {
                "success": True,
                "phone_number": phone_number,
                "phone_id": phone_id,
            }
            
    except Exception as e:
        logger.error(f"Error provisioning phone number: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


async def get_clinic_by_phone(phone_number: str) -> Optional[Dict[str, Any]]:
    """
    Look up which clinic owns a phone number.
    Used for multi-tenant call routing.
    
    Args:
        phone_number: Phone number in E.164 format
        
    Returns:
        Clinic data dict or None
    """
    try:
        # Normalize phone number (remove spaces, ensure + prefix)
        normalized = phone_number.strip().replace(" ", "")
        if not normalized.startswith("+"):
            normalized = f"+{normalized}"
        
        result = (
            supabase.table("clinic_phone_numbers")
            .select("clinic_id, clinics(*)")
            .eq("phone_number", normalized)
            .eq("is_active", True)
            .maybe_single()
            .execute()
        )
        
        if result.data:
            return result.data["clinics"]
        
        # Fallback: try without + prefix
        result = (
            supabase.table("clinic_phone_numbers")
            .select("clinic_id, clinics(*)")
            .eq("phone_number", normalized[1:])  # Try without +
            .eq("is_active", True)
            .maybe_single()
            .execute()
        )
        
        if result.data:
            return result.data["clinics"]
        
        return None
        
    except Exception as e:
        logger.error(f"Error looking up clinic by phone: {e}")
        return None


async def list_clinic_phone_numbers(clinic_id: UUID) -> List[Dict[str, Any]]:
    """Get all phone numbers for a clinic"""
    try:
        result = (
            supabase.table("clinic_phone_numbers")
            .select("*")
            .eq("clinic_id", str(clinic_id))
            .eq("is_active", True)
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.error(f"Error listing clinic phone numbers: {e}")
        return []


# =============================================================================
# AGENT MANAGEMENT
# =============================================================================

async def create_clinic_agent(clinic_id: UUID) -> Dict[str, Any]:
    """
    Create a Retell AI agent for a clinic.
    
    Uses the new Retell API format:
    1. First create an LLM with the system prompt
    2. Then create an agent that references that LLM
    
    Args:
        clinic_id: Clinic UUID
        
    Returns:
        Dict with 'success', 'agent_id'
    """
    if not settings.retell_api_key:
        logger.error("Retell API key not configured")
        return {"success": False, "error": "Retell API key not configured"}
    
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
        
        # Get doctors for context
        doctors_response = (
            supabase.table("doctors")
            .select("id, name, title, specialty")
            .eq("clinic_id", str(clinic_id))
            .eq("is_active", True)
            .execute()
        )
        doctors = doctors_response.data or []
        
        # Get appointment types
        types_response = (
            supabase.table("appointment_types")
            .select("id, name, duration_minutes")
            .eq("clinic_id", str(clinic_id))
            .eq("is_active", True)
            .execute()
        )
        appointment_types = types_response.data or []
        
        # Build the comprehensive system prompt
        system_prompt = _build_system_prompt(clinic, doctors, appointment_types)
        begin_message = clinic.get("greeting_template") or f"Hello! Welcome to {clinic['name']}. How can I help you today?"
        
        logger.info(f"Creating Retell LLM and agent for clinic {clinic_id}")
        
        async with httpx.AsyncClient() as client:
            # Step 1: Create an LLM with the system prompt and custom functions
            # Each function has its own dedicated endpoint for better routing
            webhook_base_url = "https://curavoice-backend-production.up.railway.app/api/retell"
            
            llm_config = {
                "model": "gpt-4o",
                "general_prompt": system_prompt,
                "begin_message": begin_message,
                "general_tools": _build_tools_config_with_webhook(webhook_base_url, clinic_id),
            }
            
            llm_response = await client.post(
                f"{RETELL_API_BASE}/create-retell-llm",
                json=llm_config,
                headers=_get_headers(),
                timeout=30.0,
            )
            
            logger.info(f"Retell LLM API Response Status: {llm_response.status_code}")
            
            if llm_response.status_code >= 400:
                logger.error(f"Retell LLM API Error: {llm_response.text}")
                return {"success": False, "error": f"LLM creation failed: {llm_response.text}"}
            
            llm_result = llm_response.json()
            llm_id = llm_result.get("llm_id")
            logger.info(f"Created Retell LLM {llm_id}")
            
            # Step 2: Create an agent that references this LLM
            # Include clinic_id in metadata so custom functions can identify which clinic to query
            agent_config = {
                "agent_name": f"{clinic['name']} Voice Assistant",
                "voice_id": "11labs-Adrian",  # Professional male voice
                "response_engine": {
                    "type": "retell-llm",
                    "llm_id": llm_id,
                },
                "language": _map_language_code(clinic.get("default_language", "en")),
                "webhook_url": "https://curavoice-backend-production.up.railway.app/api/retell/webhook",
                "voice_temperature": 0.7,
                "voice_speed": 1.0,
                "responsiveness": 0.8,
                "interruption_sensitivity": 0.5,
                "enable_backchannel": True,
                "reminder_trigger_ms": 10000,
                "reminder_max_count": 2,
                "end_call_after_silence_ms": 30000,  # End call after 30s silence
                "max_call_duration_ms": 600000,  # 10 minute max call
                "metadata": {
                    "clinic_id": str(clinic_id),  # Include clinic_id for custom function routing
                },
            }
            
            agent_response = await client.post(
                f"{RETELL_API_BASE}/create-agent",
                json=agent_config,
                headers=_get_headers(),
                timeout=30.0,
            )
            
            logger.info(f"Retell Agent API Response Status: {agent_response.status_code}")
            
            if agent_response.status_code >= 400:
                logger.error(f"Retell Agent API Error: {agent_response.text}")
                return {"success": False, "error": f"Agent creation failed: {agent_response.text}"}
            
            agent_result = agent_response.json()
            agent_id = agent_result.get("agent_id")
            
            # Update clinic with agent ID and LLM ID
            supabase.table("clinics").update({
                "retell_agent_id": agent_id,
            }).eq("id", str(clinic_id)).execute()
            
            logger.info(f"Created Retell agent {agent_id} with LLM {llm_id} for clinic {clinic_id}")
            
            return {
                "success": True,
                "agent_id": agent_id,
                "llm_id": llm_id,
            }
            
    except Exception as e:
        logger.error(f"Error creating Retell agent: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


async def update_clinic_agent(clinic_id: UUID) -> Dict[str, Any]:
    """
    Update an existing Retell agent with new clinic data.
    Call this when clinic info, doctors, or services change.
    """
    try:
        clinic_response = (
            supabase.table("clinics")
            .select("*, retell_agent_id")
            .eq("id", str(clinic_id))
            .single()
            .execute()
        )
        
        if not clinic_response.data:
            return {"success": False, "error": "Clinic not found"}
        
        clinic = clinic_response.data
        agent_id = clinic.get("retell_agent_id")
        
        if not agent_id:
            # No existing agent, create one
            return await create_clinic_agent(clinic_id)
        
        # Get updated doctors and appointment types
        doctors_response = (
            supabase.table("doctors")
            .select("id, name, title, specialty")
            .eq("clinic_id", str(clinic_id))
            .eq("is_active", True)
            .execute()
        )
        doctors = doctors_response.data or []
        
        types_response = (
            supabase.table("appointment_types")
            .select("id, name, duration_minutes")
            .eq("clinic_id", str(clinic_id))
            .eq("is_active", True)
            .execute()
        )
        appointment_types = types_response.data or []
        
        # Rebuild prompt with updated data
        system_prompt = _build_system_prompt(clinic, doctors, appointment_types)
        
        async with httpx.AsyncClient() as client:
            response = await client.patch(
                f"{RETELL_API_BASE}/update-agent/{agent_id}",
                headers=_get_headers(),
                json={
                    "general_prompt": system_prompt,
                    "begin_message": clinic.get("greeting_template") or f"Hello! Welcome to {clinic['name']}. How can I help you today?",
                },
                timeout=30.0,
            )
            
            if response.status_code >= 400:
                logger.error(f"Failed to update agent: {response.text}")
                return {"success": False, "error": response.text}
            
            logger.info(f"Updated Retell agent {agent_id} for clinic {clinic_id}")
            return {"success": True, "agent_id": agent_id}
            
    except Exception as e:
        logger.error(f"Error updating Retell agent: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


async def delete_clinic_agent(clinic_id: UUID) -> Dict[str, Any]:
    """Delete a clinic's Retell agent and release phone numbers"""
    try:
        clinic_response = (
            supabase.table("clinics")
            .select("retell_agent_id")
            .eq("id", str(clinic_id))
            .single()
            .execute()
        )
        
        if not clinic_response.data:
            return {"success": False, "error": "Clinic not found"}
        
        agent_id = clinic_response.data.get("retell_agent_id")
        
        async with httpx.AsyncClient() as client:
            # Delete agent
            if agent_id:
                await client.delete(
                    f"{RETELL_API_BASE}/delete-agent/{agent_id}",
                    headers=_get_headers(),
                    timeout=30.0,
                )
            
            # Get and release phone numbers
            phone_numbers = await list_clinic_phone_numbers(clinic_id)
            for phone in phone_numbers:
                phone_id = phone.get("retell_phone_id")
                if phone_id:
                    await client.delete(
                        f"{RETELL_API_BASE}/delete-phone-number/{phone_id}",
                        headers=_get_headers(),
                        timeout=30.0,
                    )
        
        # Update database
        supabase.table("clinics").update({
            "retell_agent_id": None,
            "retell_phone_number_id": None,
        }).eq("id", str(clinic_id)).execute()
        
        supabase.table("clinic_phone_numbers").update({
            "is_active": False,
        }).eq("clinic_id", str(clinic_id)).execute()
        
        logger.info(f"Deleted Retell resources for clinic {clinic_id}")
        return {"success": True}
        
    except Exception as e:
        logger.error(f"Error deleting Retell resources: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _map_language_code(lang_code: str) -> str:
    """Map short language codes to Retell-compatible locale codes."""
    mapping = {
        "en": "en-US",
        "en-us": "en-US",
        "en-gb": "en-GB",
        "en-au": "en-AU",
        "fr": "fr-FR",
        "de": "de-DE",
        "es": "es-ES",
        "pt": "pt-BR",
        "ar": "ar-SA",
        "zh": "zh-CN",
        "ja": "ja-JP",
        "ko": "ko-KR",
        "hi": "hi-IN",
        "it": "it-IT",
        "nl": "nl-NL",
        "pl": "pl-PL",
        "tr": "tr-TR",
        "vi": "vi-VN",
        "yo": "en-US",  # Yoruba - fallback to English
        "pcm": "en-US",  # Nigerian Pidgin - fallback to English
        "multi": "multi",  # Multilingual
    }
    return mapping.get(lang_code.lower(), "en-US")


def _build_system_prompt(
    clinic: Dict[str, Any],
    doctors: List[Dict[str, Any]],
    appointment_types: List[Dict[str, Any]],
) -> str:
    """
    Build a comprehensive system prompt for the Retell agent.
    
    Key principles:
    - Explicit function-calling instructions
    - Dynamic data via function calls (doctors, availability)
    - No hallucination of data
    - Clear workflow steps
    """
    
    return f"""You are the voice assistant for {clinic['name']}, a medical clinic located in {clinic.get('city', 'Nigeria')}.

CLINIC INFORMATION:
- Name: {clinic['name']}
- Address: {clinic.get('address', 'Not specified')}, {clinic.get('city', '')}, {clinic.get('country', 'Nigeria')}
- Language: {clinic.get('default_language', 'English')}

═══════════════════════════════════════════════════════════════
CRITICAL RULES - YOU MUST FOLLOW THESE:
═══════════════════════════════════════════════════════════════

1. ALWAYS USE FUNCTIONS TO GET DATA
   - To get doctors list: CALL get_clinic_info("doctors") - NEVER guess!
   - To get appointment types/services: CALL get_appointment_types() 
   - To get available times: CALL check_availability(doctor_id, date) - NEVER invent times!
   - To get clinic hours: CALL get_clinic_info("hours")
   - To get clinic address: CALL get_clinic_info("address")

2. NEVER MAKE UP INFORMATION
   - Do NOT invent doctor names - call get_clinic_info("doctors")
   - Do NOT invent appointment times - call check_availability()
   - Do NOT guess availability - always check first
   - If a function fails, apologize and ask to try again

3. FUNCTION CALLING IS MANDATORY
   - When patient asks about doctors: CALL get_clinic_info("doctors") FIRST
   - When patient wants to book: CALL check_availability() FIRST
   - When booking: CALL book_appointment() with complete details
   - When patient gives phone: CALL lookup_patient() to check history

4. COLLECT COMPLETE INFORMATION
   Before booking, you MUST have:
   - Patient's full name (first and last)
   - Patient's phone number (10+ digits)
   - Which doctor they want to see (from get_clinic_info response)
   - Preferred date
   - Selected time from AVAILABLE slots (from check_availability response)

═══════════════════════════════════════════════════════════════
BOOKING WORKFLOW - FOLLOW THESE STEPS:
═══════════════════════════════════════════════════════════════

STEP 1: GREET & UNDERSTAND
- Say hello and ask how you can help
- Listen for: "appointment", "book", "schedule", "see doctor"

STEP 2: IDENTIFY DOCTOR
- Call get_clinic_info("doctors") to get the list
- Read the doctor names from the response
- Let patient choose which doctor
- REMEMBER the exact doctor name they chose (you'll need it for check_availability)

STEP 3: COLLECT PATIENT DETAILS
- Ask: "May I have your full name please?"
- Wait for complete response
- Ask: "And your phone number?"
- Validate it has 10+ digits

STEP 4: GET DATE
- Ask: "What date would you like to come in?"
- Accept natural language: "tomorrow", "next Monday", "January 15th"
- MUST convert to YYYY-MM-DD format (e.g., "tomorrow" → "2026-01-09")

STEP 5: CHECK AVAILABILITY (CRITICAL!)
- Extract TWO values from conversation history:
  * Doctor name patient wants (exact name, e.g. "Abdelaziz Azouhri")
  * Date they prefer (convert to YYYY-MM-DD: today=Jan 8 2026, tomorrow=2026-01-09, Jan 10=2026-01-10)
- THEN call: check_availability(doctor_name="EXTRACTED_NAME", date="YYYY-MM-DD")
- NEVER call without BOTH parameters filled - if missing, ask patient first!
- Present ONLY the returned times
- Example: "I have 9:00 AM, 10:30 AM, and 2:00 PM available. Which works for you?"
- If no slots: "I'm sorry, that date is fully booked. Would you like to try another date?"

STEP 6: CONFIRM & BOOK
- Repeat back: "Let me confirm: [Name], appointment with [Doctor] on [Date] at [Time]"
- Wait for confirmation
- Call: book_appointment() with all details

STEP 7: CLOSING
- Confirm booking was successful
- Mention they'll receive an SMS confirmation
- Ask if there's anything else
- Use end_call to hang up gracefully

═══════════════════════════════════════════════════════════════
HANDLING OTHER REQUESTS:
═══════════════════════════════════════════════════════════════

FOR CLINIC INFO:
- Hours: Call get_clinic_info("hours")
- Address: Call get_clinic_info("address")
- Services: Call get_clinic_info("services")
- Doctors: Call get_clinic_info("doctors")

FOR EXISTING PATIENTS:
- If they mention past visits, call lookup_patient() with their phone
- You can see their appointment history

FOR ISSUES YOU CAN'T HANDLE:
- Say: "I'll need to connect you with our staff for that. One moment please."
- Use transfer_call if configured, or take a message

═══════════════════════════════════════════════════════════════
CONVERSATION STYLE:
═══════════════════════════════════════════════════════════════
- Be warm, professional, and concise
- Use the patient's name after they provide it
- Be patient with elderly callers
- If you don't understand, ask them to repeat
- Avoid long pauses - acknowledge you're working on it
- End calls politely with well-wishes

Remember: You represent {clinic['name']}. Every interaction reflects on the clinic.
"""


def _build_tools_config_with_webhook(webhook_base_url: str, clinic_id: UUID) -> List[Dict[str, Any]]:
    """
    Build the tools/functions configuration for Retell LLM.
    
    One agent per clinic architecture:
    - clinic_id is embedded in the function URL
    - No metadata lookup needed - explicit and clean!
    - Each function URL includes the clinic_id path parameter
    """
    return [
        {
            "type": "end_call",
            "name": "end_call",
            "description": "End the call politely after the conversation is complete.",
        },
        {
            "type": "custom",
            "name": "get_clinic_info",
            "description": "Get clinic information. Use info_type='doctors' for doctor list, 'services' for services, 'hours' for hours, 'address' for location. ALWAYS call with info_type='doctors' first before booking.",
            "url": f"{webhook_base_url}/functions/{clinic_id}/get_clinic_info",
            "speak_during_execution": True,
            "speak_after_execution": True,
            "execution_message_description": "Let me check that information for you.",
            "parameters": {
                "type": "object",
                "properties": {
                    "info_type": {
                        "type": "string",
                        "enum": ["doctors", "services", "hours", "address"],
                        "description": "REQUIRED: Specify which information to get - 'doctors' for available doctors, 'services' for services offered, 'hours' for opening hours, 'address' for clinic location"
                    }
                },
                "required": ["info_type"]
            }
        },
        {
            "type": "custom",
            "name": "get_appointment_types",
            "description": "Get the list of available appointment types and services offered by the clinic with their durations and prices.",
            "url": f"{webhook_base_url}/functions/{clinic_id}/get_appointment_types",
            "speak_during_execution": True,
            "speak_after_execution": True,
            "execution_message_description": "Let me get our available services for you.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        },
        {
            "type": "custom",
            "name": "check_availability",
            "description": "Check available appointment time slots for a specific doctor on a date. Call this after patient chooses a doctor from the list.",
            "url": f"{webhook_base_url}/functions/{clinic_id}/check_availability",
            "speak_during_execution": True,
            "speak_after_execution": True,
            "execution_message_description": "Let me check what times are available.",
            "parameters": {
                "type": "object",
                "required": ["doctor_name", "date"],
                "properties": {
                    "doctor_name": {
                        "type": "string",
                        "description": "REQUIRED STRING - Extract from conversation: the doctor's name that patient wants to see. If patient said 'Dr. Abdelaziz Azouhri' then pass 'Abdelaziz Azouhri'. If patient said 'tomorrow', extract the doctor name they mentioned earlier in the conversation."
                    },
                    "date": {
                        "type": "string",
                        "description": "REQUIRED STRING in YYYY-MM-DD format - Extract and convert patient's date preference: Today is January 8, 2026. 'tomorrow' becomes '2026-01-09'. 'next week' becomes '2026-01-15'. 'January 10' becomes '2026-01-10'. Always use YYYY-MM-DD format."
                    }
                }
            }
        },
        {
            "type": "custom",
            "name": "book_appointment",
            "description": "Book an appointment after collecting all required information and confirming with patient.",
            "url": f"{webhook_base_url}/webhook",
            "speak_during_execution": True,
            "speak_after_execution": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "doctor_id": {"type": "string", "description": "UUID of the doctor"},
                    "date": {"type": "string", "description": "Date in YYYY-MM-DD format"},
                    "time": {"type": "string", "description": "Time in HH:MM format"},
                    "patient_name": {"type": "string", "description": "Patient's full name"},
                    "patient_phone": {"type": "string", "description": "Patient's phone number"},
                    "reason": {"type": "string", "description": "Reason for visit (optional)"}
                },
                "required": ["doctor_id", "date", "time", "patient_name", "patient_phone"]
            }
        },
        {
            "type": "custom",
            "name": "lookup_patient",
            "description": "Look up an existing patient by phone number to see their history.",
            "url": f"{webhook_base_url}/webhook",
            "speak_during_execution": True,
            "speak_after_execution": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "phone": {"type": "string", "description": "Patient's phone number"}
                },
                "required": ["phone"]
            }
        },
        {
            "type": "custom",
            "name": "cancel_appointment",
            "description": "Cancel an existing appointment.",
            "url": f"{webhook_base_url}/webhook",
            "speak_during_execution": True,
            "speak_after_execution": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "appointment_id": {"type": "string", "description": "UUID of appointment"},
                    "reason": {"type": "string", "description": "Reason for cancellation"}
                },
                "required": ["appointment_id"]
            }
        },
        {
            "type": "custom",
            "name": "reschedule_appointment",
            "description": "Reschedule an appointment to a new date/time.",
            "url": f"{webhook_base_url}/webhook",
            "speak_during_execution": True,
            "speak_after_execution": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "appointment_id": {"type": "string", "description": "UUID of appointment"},
                    "new_date": {"type": "string", "description": "New date in YYYY-MM-DD format"},
                    "new_time": {"type": "string", "description": "New time in HH:MM format"}
                },
                "required": ["appointment_id", "new_date", "new_time"]
            }
        },
    ]


def _build_tools_config() -> List[Dict[str, Any]]:
    """Build the tools/functions configuration for Retell agent (legacy, without webhook)"""
    return [
        {
            "type": "end_call",
            "name": "end_call",
            "description": "End the call politely after the conversation is complete.",
        },
        {
            "type": "custom",
            "name": "get_clinic_info",
            "description": "Get clinic information. Use this for: doctors list, services offered, operating hours, or clinic address.",
            "parameters": {
                "type": "object",
                "properties": {
                    "info_type": {
                        "type": "string",
                        "enum": ["doctors", "services", "hours", "address"],
                        "description": "Type of information to retrieve"
                    }
                },
                "required": ["info_type"]
            }
        },
        {
            "type": "custom",
            "name": "check_availability",
            "description": "Check available appointment time slots for a doctor on a specific date. ALWAYS call this before suggesting times to the patient.",
            "parameters": {
                "type": "object",
                "properties": {
                    "doctor_id": {
                        "type": "string",
                        "description": "UUID of the doctor (from get_clinic_info doctors response)"
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
            "type": "custom",
            "name": "book_appointment",
            "description": "Book an appointment. Call this only after: 1) getting patient name and phone, 2) checking availability, 3) patient confirms the slot.",
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
                        "description": "Time in HH:MM format (24-hour, from availability check)"
                    },
                    "patient_name": {
                        "type": "string",
                        "description": "Patient's full name"
                    },
                    "patient_phone": {
                        "type": "string",
                        "description": "Patient's phone number (10+ digits)"
                    },
                    "reason": {
                        "type": "string",
                        "description": "Reason for visit (optional)"
                    }
                },
                "required": ["doctor_id", "date", "time", "patient_name", "patient_phone"]
            }
        },
        {
            "type": "custom",
            "name": "lookup_patient",
            "description": "Look up an existing patient by their phone number to see their history and past appointments.",
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
            "type": "custom",
            "name": "cancel_appointment",
            "description": "Cancel an existing appointment for a patient.",
            "parameters": {
                "type": "object",
                "properties": {
                    "appointment_id": {
                        "type": "string",
                        "description": "UUID of the appointment to cancel"
                    },
                    "reason": {
                        "type": "string",
                        "description": "Reason for cancellation (optional)"
                    }
                },
                "required": ["appointment_id"]
            }
        },
        {
            "type": "custom",
            "name": "reschedule_appointment",
            "description": "Reschedule an existing appointment to a new date/time.",
            "parameters": {
                "type": "object",
                "properties": {
                    "appointment_id": {
                        "type": "string",
                        "description": "UUID of the appointment to reschedule"
                    },
                    "new_date": {
                        "type": "string",
                        "description": "New date in YYYY-MM-DD format"
                    },
                    "new_time": {
                        "type": "string",
                        "description": "New time in HH:MM format"
                    }
                },
                "required": ["appointment_id", "new_date", "new_time"]
            }
        },
    ]


# =============================================================================
# OUTBOUND CALLS
# =============================================================================

async def make_outbound_call(
    clinic_id: UUID,
    to_number: str,
    purpose: str = "reminder",
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Make an outbound call (e.g., appointment reminders).
    
    Args:
        clinic_id: Clinic UUID
        to_number: Patient phone number to call
        purpose: Purpose of call (reminder, followup, etc.)
        metadata: Additional call metadata
        
    Returns:
        Dict with 'success', 'call_id'
    """
    try:
        # Get clinic's agent and phone number
        clinic_response = (
            supabase.table("clinics")
            .select("retell_agent_id, phone_number")
            .eq("id", str(clinic_id))
            .single()
            .execute()
        )
        
        if not clinic_response.data:
            return {"success": False, "error": "Clinic not found"}
        
        clinic = clinic_response.data
        agent_id = clinic.get("retell_agent_id")
        from_number = clinic.get("phone_number")
        
        if not agent_id or not from_number:
            return {"success": False, "error": "Clinic not configured for outbound calls"}
        
        call_metadata = {
            "clinic_id": str(clinic_id),
            "purpose": purpose,
            **(metadata or {}),
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{RETELL_API_BASE}/create-phone-call",
                headers=_get_headers(),
                json={
                    "agent_id": agent_id,
                    "from_number": from_number,
                    "to_number": to_number,
                    "metadata": call_metadata,
                },
                timeout=30.0,
            )
            
            if response.status_code >= 400:
                logger.error(f"Failed to create outbound call: {response.text}")
                return {"success": False, "error": response.text}
            
            result = response.json()
            logger.info(f"Initiated outbound call {result.get('call_id')} for clinic {clinic_id}")
            
            return {
                "success": True,
                "call_id": result.get("call_id"),
            }
            
    except Exception as e:
        logger.error(f"Error making outbound call: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
