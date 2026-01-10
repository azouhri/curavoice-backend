"""
Retell AI webhook handler for multi-tenant voice calls.

Routing Logic:
1. Inbound call comes to a clinic's phone number
2. Retell sends webhook with to_number (clinic phone) and from_number (patient)
3. We look up clinic_id from the to_number
4. All function calls are scoped to that clinic

This architecture supports:
- Multiple clinics with different phone numbers
- One shared agent handling all clinics
- Per-clinic data isolation
"""

import json
import logging
import re
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, Optional
from uuid import UUID
from fastapi import APIRouter, Request, HTTPException
from app.config import supabase
from app.services.availability import check_doctor_availability
from app.services.appointments import (
    book_appointment,
    cancel_appointment,
    reschedule_appointment,
    get_patient_appointments,
)
from app.services.patients import lookup_patient_by_phone
from app.services.retell import get_clinic_by_phone
from app.models.schemas import AppointmentCreate
from dateutil.parser import parse as dateutil_parse

logger = logging.getLogger(__name__)
router = APIRouter()


# =============================================================================
# SIGNATURE VERIFICATION
# =============================================================================

def verify_retell_signature(body: bytes, signature: str, api_key: str) -> bool:
    """
    Verify Retell webhook signature using HMAC-SHA256.
    
    Args:
        body: Raw request body as bytes
        signature: Signature from X-Retell-Signature header
        api_key: Retell API key (used as HMAC secret)
    
    Returns:
        True if signature is valid, False otherwise
    """
    import hmac
    import hashlib
    import base64
    
    if not signature or not api_key:
        return False
    
    try:
        # Compute expected signature
        expected = hmac.new(
            key=api_key.encode('utf-8'),
            msg=body,
            digestmod=hashlib.sha256
        ).digest()
        
        # Encode as base64
        expected_b64 = base64.b64encode(expected).decode('utf-8')
        
        # Timing-safe comparison to prevent timing attacks
        return hmac.compare_digest(expected_b64, signature)
    except Exception as e:
        logger.error(f"Error verifying signature: {e}")
        return False


# =============================================================================
# INBOUND WEBHOOK (Multi-Tenant Conversation Flow)
# =============================================================================

@router.post("/inbound/{clinic_id}")
async def retell_inbound_webhook(
    clinic_id: str,
    request: Request,
):
    """
    Handle inbound call webhook from Retell.
    Called BEFORE conversation starts to inject clinic-specific dynamic variables.
    
    This enables multi-tenant architecture where ONE master agent serves ALL clinics.
    
    Flow:
    1. Patient calls clinic's phone number
    2. Retell receives call and hits this webhook
    3. Webhook identifies clinic from clinic_id in URL
    4. Webhook returns master agent ID + dynamic variables (clinic data)
    5. Conversation starts with variables already loaded
    
    Performance: Must respond in < 200ms to avoid call delays
    """
    from app.config import settings
    from app.services.retell import get_clinic_by_phone
    
    # Verify signature for security (production-ready)
    signature = request.headers.get("x-retell-signature", "")
    body_bytes = await request.body()
    if settings.retell_api_key and signature:
        if not verify_retell_signature(body_bytes, signature, settings.retell_api_key):
            logger.warning(f"Invalid Retell signature for clinic {clinic_id}")
            raise HTTPException(status_code=401, detail="Invalid signature")
    
    try:
        # Parse request
        call_data = json.loads(body_bytes.decode('utf-8'))
        call_id = call_data.get("call_id", "unknown")
        from_number = call_data.get("from_number", "unknown")
        to_number = call_data.get("to_number", "unknown")
        
        logger.info(f"Inbound webhook called for clinic {clinic_id}, call_id: {call_id}, from: {from_number}, to: {to_number}")
        
        # Try to fetch clinic by ID first
        clinic_response = None
        try:
            clinic_response = (
                supabase.table("clinics")
                .select("id, name, address, phone_number, greeting_template, default_language, supported_languages")
                .eq("id", clinic_id)
                .single()
                .execute()
            )
        except Exception as e:
            logger.warning(f"Clinic {clinic_id} not found by ID: {e}")
        
        # Fallback: Try to find clinic by phone number (to_number)
        if not clinic_response or not clinic_response.data:
            logger.info(f"Attempting clinic lookup by phone: {to_number}")
            clinic_data = await get_clinic_by_phone(to_number)
            if clinic_data:
                clinic_id = str(clinic_data['id'])
                logger.info(f"Clinic resolved by phone: {clinic_id}")
                clinic_response = type('obj', (object,), {'data': clinic_data})()
        
        if not clinic_response or not clinic_response.data:
            # Return fallback data instead of 404 (graceful degradation)
            logger.error(f"Clinic {clinic_id} not found after all attempts, using fallback")
            return {
                "agent_id": settings.retell_master_agent_id or "agent_fallback",
                "retell_llm_dynamic_variables": {
                    "clinic_id": clinic_id,
                    "clinic_name": "Our Medical Clinic",
                    "clinic_address": "",
                    "clinic_phone": "",
                    "available_doctors": "Please hold while I connect you to our staff.",
                    "doctor_id_map": "{}",
                    "business_hours": "",
                    "language": "en",
                    "greeting_custom": "",
                    "error_mode": "true"
                }
            }
        
        clinic = clinic_response.data
        logger.info(f"Inbound webhook processing for clinic: {clinic['name']} ({clinic_id})")
        
        # Fetch clinic data from Supabase
        clinic_response = (
            supabase.table("clinics")
            .select("id, name, address, phone_number, greeting_template, default_language, supported_languages")
            .eq("id", clinic_id)
            .single()
            .execute()
        )
        
        if not clinic_response.data:
            # Return fallback data instead of 404 (graceful degradation)
            logger.error(f"Clinic {clinic_id} not found, using fallback")
            return {
                "agent_id": settings.retell_master_agent_id or "agent_fallback",
                "retell_llm_dynamic_variables": {
                    "clinic_id": clinic_id,
                    "clinic_name": "Our Medical Clinic",
                    "clinic_address": "",
                    "clinic_phone": "",
                    "available_doctors": "Please hold while I connect you to our staff.",
                    "doctor_id_map": "{}",
                    "business_hours": "",
                    "language": "en",
                    "greeting_custom": "",
                    "error_mode": "true"
                }
            }
        
        clinic = clinic_response.data
        
        # Fetch doctors for this clinic (limit to 20 for size constraint)
        doctors_response = (
            supabase.table("doctors")
            .select("id, name, title, specialty")
            .eq("clinic_id", clinic_id)
            .eq("is_active", True)
            .limit(20)
            .execute()
        )
        
        doctors = doctors_response.data or []
        
        # Format doctor list for AI
        doctors_formatted = "\n".join([
            f"{i+1}. {doc.get('title', 'Dr.')} {doc['name']} - {doc.get('specialty', 'General')}"
            for i, doc in enumerate(doctors)
        ])
        
        if len(doctors) == 20:
            # Note if list was truncated
            doctors_formatted += "\n... and more doctors available. Ask me for a specific specialty."
        
        # Create doctor ID mapping (for function calls)
        doctor_id_map = {
            f"{doc.get('title', 'Dr.')} {doc['name']}": doc['id']
            for doc in doctors
        }
        
        # Return agent ID and dynamic variables
        response = {
            "agent_id": settings.retell_master_agent_id or "agent_placeholder",
            "retell_llm_dynamic_variables": {
                "clinic_id": str(clinic['id']),
                "clinic_name": clinic['name'],
                "clinic_address": clinic.get('address', ''),
                "clinic_phone": clinic.get('phone_number', ''),
                "available_doctors": doctors_formatted,
                "doctor_id_map": json.dumps(doctor_id_map),
                "business_hours": "Monday-Friday: 8am-6pm",  # TODO: Get from clinic settings
                "language": clinic.get('default_language', 'en'),
                "greeting_custom": clinic.get('greeting_template', ''),
                "max_appointment_days": "30",
                "accepts_walk_ins": "false"
            }
        }
        
        logger.info(f"Inbound webhook successful for clinic {clinic_id}, returned {len(doctors)} doctors")
        return response
        
    except Exception as e:
        logger.error(f"Error in inbound webhook for clinic {clinic_id}: {e}", exc_info=True)
        # Return fallback instead of raising exception
        return {
            "agent_id": settings.retell_master_agent_id or "agent_fallback",
            "retell_llm_dynamic_variables": {
                "clinic_id": clinic_id,
                "clinic_name": "Our Medical Clinic",
                "clinic_address": "",
                "clinic_phone": "",
                "available_doctors": "I apologize, I'm having trouble accessing our schedule. Let me connect you to our staff.",
                "doctor_id_map": "{}",
                "business_hours": "",
                "language": "en",
                "error_mode": "true"
            }
        }


# =============================================================================
# MULTI-TENANT FUNCTION WEBHOOKS (Master Agent)
# =============================================================================
# These endpoints extract clinic_id from function arguments (dynamic variables)
# instead of URL path. Used with the master agent architecture.

@router.post("/functions/check_availability")
async def function_check_availability_multitenant(request: Request):
    """
    Multi-tenant check_availability function.
    Extracts clinic_id from args (injected as dynamic variable).
    """
    try:
        body = await request.json()
        args = body.get("args", {}) or body.get("arguments", {})
        
        # Extract clinic_id from dynamic variable
        clinic_id_str = args.get("clinic_id")
        if not clinic_id_str:
            return {"result": "I'm having trouble accessing clinic information right now."}
        
        clinic_id = UUID(clinic_id_str)
        doctor_id_str = args.get("doctor_id")
        date_str = args.get("date")
        language = args.get("language", "en")
        
        logger.info(f"check_availability (multi-tenant) - clinic: {clinic_id}, doctor: {doctor_id_str}, date: {date_str}")
        
        if not doctor_id_str or not date_str:
            return {"result": "I need to know which doctor and what date you'd like to check availability for."}
        
        # Parse date string
        from datetime import datetime
        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return {"result": "I didn't understand that date. Could you provide it in the format YYYY-MM-DD?"}
        
        # Query availability
        result = await check_doctor_availability(
            doctor_id=UUID(doctor_id_str),
            target_date=target_date,
            clinic_id=clinic_id
        )
        
        if not result.get("available"):
            return {"result": result.get("message", "No slots are available on that date.")}
        
        slots = result.get("slots", [])
        if not slots:
            return {"result": "I'm sorry, no slots are available on that date. Would you like to try another date?"}
        
        slots_text = ", ".join(slots[:5])  # Limit to first 5 slots
        return {
            "result": f"Available times: {slots_text}. Which time works best for you?",
            "metadata": {"available_slots": slots}
        }
        
    except Exception as e:
        logger.error(f"Error in check_availability (multi-tenant): {e}", exc_info=True)
        return {"result": "I'm having trouble checking availability right now."}


@router.post("/functions/book_appointment")
async def function_book_appointment_multitenant(request: Request):
    """
    Multi-tenant book_appointment function.
    Extracts clinic_id from args (injected as dynamic variable).
    """
    try:
        body = await request.json()
        args = body.get("args", {}) or body.get("arguments", {})
        
        # Extract all parameters
        clinic_id_str = args.get("clinic_id")
        doctor_id_str = args.get("doctor_id")
        date_str = args.get("date")
        time_str = args.get("time")
        patient_name = args.get("patient_name")
        patient_phone = args.get("patient_phone")
        reason = args.get("reason", "")
        language = args.get("language", "en")
        
        if not all([clinic_id_str, doctor_id_str, date_str, time_str, patient_name, patient_phone]):
            return {"result": "I need the patient's name, phone number, doctor, date, and time to book the appointment."}
        
        logger.info(f"book_appointment (multi-tenant) - clinic: {clinic_id_str}, doctor: {doctor_id_str}, date: {date_str}, time: {time_str}")
        
        # Parse date and time
        from datetime import datetime
        try:
            appointment_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            appointment_time = datetime.strptime(time_str, "%H:%M").time()
        except ValueError as e:
            return {"result": "I didn't understand the date or time format. Please provide date as YYYY-MM-DD and time as HH:MM."}
        
        # Create AppointmentCreate object
        from app.models.schemas import AppointmentCreate
        appointment_data = AppointmentCreate(
            clinic_id=UUID(clinic_id_str),
            doctor_id=UUID(doctor_id_str),
            patient_name=patient_name,
            patient_phone=patient_phone,
            date=appointment_date,
            time=appointment_time,
            reason=reason
        )
        
        # Book appointment
        result = await book_appointment(appointment_data)
        
        if result.get("success"):
            return {
                "result": f"Perfect! I've booked your appointment with the doctor on {date_str} at {time_str}. You'll receive an SMS confirmation shortly. Is there anything else I can help you with?",
                "metadata": {"appointment_id": str(result.get("appointment_id"))}
            }
        else:
            error = result.get("message", "unknown error")
            if "already booked" in error.lower() or "conflict" in error.lower():
                return {"result": "I'm sorry, that time slot was just booked by another patient. Let me check other available times for you."}
            else:
                return {"result": "I'm having trouble booking the appointment right now. Let me connect you to our staff who can help."}
        
    except Exception as e:
        logger.error(f"Error in book_appointment (multi-tenant): {e}", exc_info=True)
        return {"result": "I apologize, I'm having trouble booking the appointment right now."}


@router.post("/functions/get_patient_appointments")
async def function_get_patient_appointments_multitenant(request: Request):
    """
    Multi-tenant get_patient_appointments function.
    Extracts clinic_id from args.
    """
    try:
        body = await request.json()
        args = body.get("args", {}) or body.get("arguments", {})
        
        clinic_id_str = args.get("clinic_id")
        patient_phone = args.get("patient_phone")
        language = args.get("language", "en")
        
        if not clinic_id_str or not patient_phone:
            return {"result": "I need your phone number to look up your appointments."}
        
        logger.info(f"get_patient_appointments (multi-tenant) - clinic: {clinic_id_str}, phone: {patient_phone}")
        
        # Lookup appointments
        result = await get_patient_appointments(
            clinic_id=UUID(clinic_id_str),
            patient_phone=patient_phone
        )
        
        appointments = result.get("appointments", [])
        
        if not appointments:
            return {"result": "I don't see any upcoming appointments for this phone number. Would you like to book a new appointment?"}
        
        # Format appointment details
        appt = appointments[0]  # Most recent
        return {
            "result": f"You have an appointment on {appt['date']} at {appt['time']}. Would you like to cancel or reschedule it?",
            "metadata": {"appointments": appointments}
        }
        
    except Exception as e:
        logger.error(f"Error in get_patient_appointments (multi-tenant): {e}", exc_info=True)
        return {"result": "I'm having trouble looking up appointments right now."}


@router.post("/functions/cancel_appointment")
async def function_cancel_appointment_multitenant(request: Request):
    """
    Multi-tenant cancel_appointment function.
    Extracts clinic_id from args.
    """
    try:
        body = await request.json()
        args = body.get("args", {}) or body.get("arguments", {})
        
        clinic_id_str = args.get("clinic_id")
        appointment_id_str = args.get("appointment_id")
        reason = args.get("reason", "")
        language = args.get("language", "en")
        
        if not clinic_id_str or not appointment_id_str:
            return {"result": "I need the appointment details to cancel it."}
        
        logger.info(f"cancel_appointment (multi-tenant) - clinic: {clinic_id_str}, appointment: {appointment_id_str}")
        
        # Cancel appointment
        result = await cancel_appointment(
            clinic_id=UUID(clinic_id_str),
            appointment_id=UUID(appointment_id_str),
            cancellation_reason=reason
        )
        
        if result.get("success"):
            return {
                "result": "Your appointment has been cancelled. You'll receive an SMS confirmation. Is there anything else I can help you with?",
                "metadata": {"cancelled": True}
            }
        else:
            return {"result": "I'm having trouble cancelling the appointment. Let me connect you to our staff."}
        
    except Exception as e:
        logger.error(f"Error in cancel_appointment (multi-tenant): {e}", exc_info=True)
        return {"result": "I'm having trouble cancelling the appointment right now."}


@router.post("/functions/get_clinic_info")
async def function_get_clinic_info_multitenant(request: Request):
    """
    Multi-tenant get_clinic_info function.
    Extracts clinic_id from args.
    """
    try:
        body = await request.json()
        args = body.get("args", {}) or body.get("arguments", {})
        
        clinic_id_str = args.get("clinic_id")
        info_type = args.get("info_type", "hours")
        
        if not clinic_id_str:
            return {"result": "I'm having trouble accessing clinic information."}
        
        logger.info(f"get_clinic_info (multi-tenant) - clinic: {clinic_id_str}, type: {info_type}")
        
        clinic_id = UUID(clinic_id_str)
        
        # Get clinic info
        data = await _fn_get_clinic_info(clinic_id, {"info_type": info_type})
        return {"result": data.get("message", str(data))}
        
    except Exception as e:
        logger.error(f"Error in get_clinic_info (multi-tenant): {e}", exc_info=True)
        return {"result": "I apologize, I encountered an error."}


# =============================================================================
# DEDICATED FUNCTION WEBHOOKS (Legacy - per-clinic agents)
# =============================================================================
# These are the original endpoints with clinic_id in URL path.
# Kept for backward compatibility with per-clinic agents.

@router.post("/functions/{clinic_id}/get_clinic_info")
async def function_get_clinic_info(clinic_id: str, request: Request):
    """
    Dedicated webhook for get_clinic_info custom function.
    Clinic ID is passed directly in the URL path - no metadata lookup needed!
    Each clinic has its own agent with functions pointing to its specific clinic_id.
    """
    try:
        body = await request.json()
        # Retell can send arguments in different places
        arguments = body.get("arguments", {}) or body.get("function_call", {}).get("arguments", {})
        
        logger.info(f"get_clinic_info called for clinic {clinic_id} with args: {arguments}")
        
        clinic_id = UUID(clinic_id)
        info_type = arguments.get("info_type", "doctors")
        
        # Call function handler
        data = await _fn_get_clinic_info(clinic_id, {"info_type": info_type})
        
        # Return just the message for Retell to speak
        return {"result": data.get("message", str(data))}
        
    except Exception as e:
        logger.error(f"Error in get_clinic_info: {e}", exc_info=True)
        return {"result": "I apologize, I encountered an error retrieving that information."}


@router.post("/functions/{clinic_id}/get_appointment_types")
async def function_get_appointment_types(clinic_id: str, request: Request):
    """
    Dedicated webhook for get_appointment_types custom function.
    Clinic ID is passed directly in the URL path.
    """
    try:
        logger.info(f"get_appointment_types called for clinic {clinic_id}")
        
        clinic_id = UUID(clinic_id)
        
        # Call function handler
        data = await _fn_get_appointment_types(clinic_id, {})
        
        # Return just the message for Retell to speak
        return {"result": data.get("message", str(data))}
        
    except Exception as e:
        logger.error(f"Error in get_appointment_types: {e}", exc_info=True)
        return {"result": "I apologize, I encountered an error."}


# =============================================================================
# HELPER FUNCTIONS FOR ARGUMENT EXTRACTION
# =============================================================================

MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


def _extract_last_user_text(body: Dict[str, Any]) -> Optional[str]:
    """
    Try to pull the latest user utterance from common Retell payload fields.
    """
    candidates = (
        body.get("messages")
        or body.get("transcript_with_tool_calls")
        or body.get("transcript_object")
        or []
    )

    if isinstance(candidates, list):
        for msg in reversed(candidates):
            if not isinstance(msg, dict):
                continue
            if msg.get("role") != "user":
                continue
            content = msg.get("content")
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                parts = []
                for c in content:
                    if isinstance(c, dict):
                        parts.append(c.get("text") or c.get("content") or "")
                joined = " ".join(parts).strip()
                if joined:
                    return joined
    return None


async def _infer_doctor_from_text(clinic_id: UUID, text: str) -> Optional[str]:
    """
    Try to match a doctor name from clinic roster against the user text.
    """
    text_lower = text.lower()
    resp = (
        supabase.table("doctors")
        .select("name")
        .eq("clinic_id", str(clinic_id))
        .eq("is_active", True)
        .execute()
    )
    doctors = resp.data or []

    # Exact substring match
    for d in doctors:
        name = d.get("name") or ""
        if name and name.lower() in text_lower:
            return name

    # All tokens match
    for d in doctors:
        name = d.get("name") or ""
        tokens = [t for t in name.lower().split() if t]
        if tokens and all(token in text_lower for token in tokens):
            return name

    return None


def _extract_date_from_text(text: str) -> Optional[str]:
    """
    Very lightweight natural language to YYYY-MM-DD conversion.
    Handles:
    - today / tomorrow
    - explicit YYYY-MM-DD
    - month name + day (current year, or next year if already passed)
    - numeric M/D or D/M (assume M/D)
    """
    text_lower = text.lower()
    today = date.today()

    if "tomorrow" in text_lower:
        return str(today + timedelta(days=1))
    if "today" in text_lower:
        return str(today)

    # YYYY-MM-DD
    m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    if m:
        return m.group(1)

    # Month name + day (e.g., January 10)
    m = re.search(r"\b([a-zA-Z]+)\s+(\d{1,2})\b", text)
    if m:
        month_name, day_str = m.groups()
        month = MONTHS.get(month_name.lower())
        if month:
            day_int = int(day_str)
            year = today.year
            try:
                candidate = date(year, month, day_int)
            except ValueError:
                candidate = None
            if candidate:
                if candidate < today:
                    try:
                        candidate = date(year + 1, month, day_int)
                    except ValueError:
                        candidate = None
                if candidate:
                    return str(candidate)

    # M/D or M-D
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})\b", text)
    if m:
        month_int = int(m.group(1))
        day_int = int(m.group(2))
        year = today.year
        try:
            candidate = date(year, month_int, day_int)
        except ValueError:
            candidate = None
        if candidate:
            if candidate < today:
                try:
                    candidate = date(year + 1, month_int, day_int)
                except ValueError:
                    candidate = None
            if candidate:
                return str(candidate)

    return None


@router.post("/functions/{clinic_id}/check_availability")
async def function_check_availability(clinic_id: str, request: Request):
    """
    Dedicated webhook for check_availability custom function.
    Clinic ID is passed directly in the URL path.
    """
    try:
        body = await request.json()
        arguments = body.get("arguments", {}) or body.get("function_call", {}).get("arguments", {}) or {}
        
        # DEBUG: Log the ENTIRE webhook payload to understand what Retell sends
        logger.info(f"check_availability FULL PAYLOAD: {json.dumps(body, indent=2)}")
        logger.info(f"check_availability called for clinic {clinic_id} with args: {arguments}")

        # Try to auto-extract doctor name and date from the latest user utterance
        user_text = _extract_last_user_text(body)

        if not arguments.get("doctor_name") and user_text:
            inferred_doctor = await _infer_doctor_from_text(UUID(clinic_id), user_text)
            if inferred_doctor:
                arguments["doctor_name"] = inferred_doctor
                logger.info(f"[auto-extract] doctor_name inferred as '{inferred_doctor}' from user text: {user_text}")

        if not arguments.get("date") and user_text:
            inferred_date = _extract_date_from_text(user_text)
            if inferred_date:
                arguments["date"] = inferred_date
                logger.info(f"[auto-extract] date inferred as '{inferred_date}' from user text: {user_text}")
        
        clinic_id = UUID(clinic_id)
        
        # Call function handler
        data = await _fn_check_availability(clinic_id, arguments)
        
        return {"result": data.get("message", str(data))}
        
    except Exception as e:
        logger.error(f"Error in check_availability: {e}", exc_info=True)
        return {"result": "I'm having trouble checking availability right now."}


# =============================================================================
# MAIN WEBHOOK HANDLER
# =============================================================================

@router.post("/webhook")
async def retell_webhook(request: Request):
    """
    Handle all Retell AI webhook events.
    
    Events:
    - call_started: New call initiated
    - call_ended: Call completed
    - call_analyzed: Post-call analysis ready
    - function_call: Agent needs to execute a function
    """
    try:
        body = await request.json()
        event = body.get("event")
        call = body.get("call", {})
        
        logger.info(f"Retell webhook: {event}")
        
        # Determine clinic from the call context
        clinic_id = await _resolve_clinic_id(call, body)
        
        if not clinic_id:
            logger.error("Could not determine clinic for call")
            return {"response_type": "error", "response": "Clinic not found"}
        
        # Route to appropriate handler
        if event == "function_call":
            return await _handle_function_call(body, clinic_id)
        
        elif event == "call_started":
            return await _handle_call_started(call, clinic_id)
        
        elif event == "call_ended":
            return await _handle_call_ended(call, clinic_id)
        
        elif event == "call_analyzed":
            return await _handle_call_analyzed(call, clinic_id)
        
        else:
            logger.debug(f"Unhandled Retell event: {event}")
            return {"status": "ok"}
            
    except Exception as e:
        logger.error(f"Error in Retell webhook: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# CLINIC RESOLUTION
# =============================================================================

async def _resolve_clinic_id(call: Dict[str, Any], body: Dict[str, Any]) -> Optional[UUID]:
    """
    Determine which clinic this call belongs to.
    
    Resolution order:
    1. Explicit clinic_id in call metadata
    2. Look up by to_number (clinic's phone number)
    3. Look up by agent_id
    """
    
    # 1. Check metadata
    metadata = call.get("metadata", {})
    if metadata.get("clinic_id"):
        logger.info(f"Clinic from metadata: {metadata['clinic_id']}")
        return UUID(metadata["clinic_id"])
    
    # 2. Look up by phone number (most reliable for inbound)
    to_number = call.get("to_number")
    if to_number:
        clinic = await get_clinic_by_phone(to_number)
        if clinic:
            logger.info(f"Clinic from phone {to_number}: {clinic['id']}")
            return UUID(clinic["id"])
    
    # 3. Fallback to agent_id lookup
    agent_id = call.get("agent_id")
    if agent_id:
        result = (
            supabase.table("clinics")
            .select("id")
            .eq("retell_agent_id", agent_id)
            .maybe_single()
            .execute()
        )
        if result.data:
            logger.info(f"Clinic from agent {agent_id}: {result.data['id']}")
            return UUID(result.data["id"])
    
    return None


# =============================================================================
# FUNCTION CALL HANDLER
# =============================================================================

async def _handle_function_call(body: Dict[str, Any], clinic_id: UUID) -> Dict[str, Any]:
    """
    Execute a function requested by the Retell agent.
    
    All functions are scoped to the resolved clinic_id.
    """
    function_call = body.get("function_call", {})
    function_name = function_call.get("name")
    arguments = function_call.get("arguments", {})
    
    logger.info(f"Function call: {function_name} for clinic {clinic_id}")
    logger.debug(f"Arguments: {arguments}")
    
    try:
        # Route to function handler
        if function_name == "get_clinic_info":
            result = await _fn_get_clinic_info(clinic_id, arguments)
        
        elif function_name == "get_appointment_types":
            result = await _fn_get_appointment_types(clinic_id, arguments)
        
        elif function_name == "check_availability":
            result = await _fn_check_availability(clinic_id, arguments)
        
        elif function_name == "book_appointment":
            result = await _fn_book_appointment(clinic_id, arguments)
        
        elif function_name == "lookup_patient":
            result = await _fn_lookup_patient(clinic_id, arguments)
        
        elif function_name == "cancel_appointment":
            result = await _fn_cancel_appointment(clinic_id, arguments)
        
        elif function_name == "reschedule_appointment":
            result = await _fn_reschedule_appointment(clinic_id, arguments)
        
        else:
            logger.warning(f"Unknown function: {function_name}")
            result = {"error": f"Unknown function: {function_name}"}
        
        logger.info(f"Function {function_name} result: {result}")
        
        # Retell expects the response in a specific format for custom functions
        # The 'result' field should contain a string that the agent will speak
        # or an object with a 'response' field
        response_text = result.get("message", str(result)) if isinstance(result, dict) else str(result)
        
        return {
            "response": response_text,
            "information": result  # Include full data for agent context
        }
        
    except Exception as e:
        logger.error(f"Error in function {function_name}: {e}", exc_info=True)
        return {
            "response": f"I apologize, I encountered an error: {str(e)}. Please try again."
        }


# =============================================================================
# FUNCTION IMPLEMENTATIONS
# =============================================================================

async def _fn_get_appointment_types(clinic_id: UUID, args: Dict[str, Any]) -> Dict[str, Any]:
    """Get available appointment types for the clinic"""
    try:
        types_response = (
            supabase.table("appointment_types")
            .select("id, name, duration_minutes, price, currency, description")
            .eq("clinic_id", str(clinic_id))
            .eq("is_active", True)
            .order("sort_order")
            .execute()
        )
        appointment_types = types_response.data or []
        
        if not appointment_types:
            return {
                "message": "We currently offer general consultations. Our staff can provide more details about specific services.",
                "appointment_types": []
            }
        
        # Format for voice
        type_descriptions = []
        for apt_type in appointment_types:
            desc = f"{apt_type['name']}, {apt_type['duration_minutes']} minutes"
            if apt_type.get('price') and apt_type.get('price') > 0:
                desc += f", {apt_type['price']} {apt_type.get('currency', 'NGN')}"
            type_descriptions.append(desc)
        
        return {
            "message": f"We offer these appointment types: {', '.join(type_descriptions)}",
            "appointment_types": appointment_types
        }
    except Exception as e:
        logger.error(f"Error getting appointment types: {e}")
        return {
            "message": "I'm having trouble retrieving our service list. Our staff can provide this information.",
            "appointment_types": []
        }


async def _fn_get_clinic_info(clinic_id: UUID, args: Dict[str, Any]) -> Dict[str, Any]:
    """Get clinic information by type"""
    info_type = args.get("info_type", "")
    
    if info_type == "doctors":
        doctors_response = (
            supabase.table("doctors")
            .select("id, name, title, specialty")
            .eq("clinic_id", str(clinic_id))
            .eq("is_active", True)
            .execute()
        )
        doctors = doctors_response.data or []
        
        if not doctors:
            return {
                "message": "There are currently no doctors available.",
                "doctors": []
            }
        
        # Format for voice
        doctor_list = []
        for d in doctors:
            name = f"{d['title']} {d['name']}"
            if d.get('specialty'):
                name += f", specializing in {d['specialty']}"
            doctor_list.append(name)
        
        return {
            "message": f"Our available doctors are: {', '.join(doctor_list)}",
            "doctors": doctors  # Include raw data with IDs for booking
        }
    
    elif info_type == "services":
        types_response = (
            supabase.table("appointment_types")
            .select("id, name, duration_minutes, price, currency")
            .eq("clinic_id", str(clinic_id))
            .eq("is_active", True)
            .execute()
        )
        services = types_response.data or []
        
        if not services:
            return {
                "message": "We offer general consultations.",
                "services": []
            }
        
        service_names = [s["name"] for s in services]
        return {
            "message": f"We offer the following services: {', '.join(service_names)}",
            "services": services
        }
    
    elif info_type == "hours":
        # For now, return default hours - could be made dynamic
        return {
            "message": "We're open Monday through Friday, from 9 AM to 5 PM. We're closed on weekends and public holidays."
        }
    
    elif info_type == "address":
        clinic_response = (
            supabase.table("clinics")
            .select("name, address, city, country")
            .eq("id", str(clinic_id))
            .single()
            .execute()
        )
        if clinic_response.data:
            c = clinic_response.data
            address_parts = [c.get("address"), c.get("city"), c.get("country")]
            address = ", ".join([p for p in address_parts if p])
            return {
                "message": f"We're located at {address}" if address else "Address not available"
            }
    
    return {"message": "I don't have that information available."}


async def _fn_check_availability(clinic_id: UUID, args: Dict[str, Any]) -> Dict[str, Any]:
    """Check doctor availability for a date"""
    try:
        doctor_name = args.get("doctor_name")
        doctor_id = args.get("doctor_id")  # Fallback to ID if provided
        date_str = args.get("date")
        
        if (not doctor_name and not doctor_id) or not date_str:
            return {
                "available": False,
                "slots": [],
                "message": "I need both the doctor and date to check availability."
            }
        
        # If doctor_name provided, look up the doctor_id
        if doctor_name and not doctor_id:
            doctor_lookup = (
                supabase.table("doctors")
                .select("id")
                .eq("clinic_id", str(clinic_id))
                .ilike("name", f"%{doctor_name}%")
                .eq("is_active", True)
                .maybe_single()
                .execute()
            )
            
            if not doctor_lookup.data:
                return {
                    "available": False,
                    "slots": [],
                    "message": f"I couldn't find a doctor named {doctor_name}. Could you please confirm the doctor's name?"
                }
            
            doctor_id = doctor_lookup.data["id"]
        
        # Parse date
        try:
            target_date = date.fromisoformat(date_str)
        except ValueError:
            return {
                "available": False,
                "slots": [],
                "message": f"I couldn't understand the date '{date_str}'. Please use format like 2026-01-15."
            }
        
        # Check if date is in the past
        today = datetime.now().date()
        if target_date < today:
            return {
                "available": False,
                "slots": [],
                "message": "That date has already passed. Would you like to try a future date?"
            }
        
        result = await check_doctor_availability(
            doctor_id=UUID(doctor_id),
            target_date=target_date,
            clinic_id=clinic_id,
        )
        
        if result.get("available") and result.get("slots"):
            slots = result["slots"]
            # Format times for voice readability
            formatted_slots = []
            for slot in slots[:6]:  # Limit to 6 options for voice
                hour, minute = map(int, slot.split(":"))
                if hour < 12:
                    formatted = f"{hour}:{minute:02d} AM"
                elif hour == 12:
                    formatted = f"12:{minute:02d} PM"
                else:
                    formatted = f"{hour-12}:{minute:02d} PM"
                formatted_slots.append(formatted)
            
            return {
                "available": True,
                "slots": slots,  # Keep original format for booking
                "formatted_slots": formatted_slots,
                "message": f"I have these times available: {', '.join(formatted_slots)}. Which one works for you?"
            }
        else:
            return {
                "available": False,
                "slots": [],
                "message": result.get("message", "No available slots on that date. Would you like to try another date?")
            }
            
    except Exception as e:
        logger.error(f"Error checking availability: {e}")
        return {
            "available": False,
            "slots": [],
            "message": "I'm having trouble checking availability. Let me try again."
        }


async def _fn_book_appointment(clinic_id: UUID, args: Dict[str, Any]) -> Dict[str, Any]:
    """Book an appointment"""
    try:
        # Validate required fields
        required = ["doctor_id", "date", "time", "patient_name", "patient_phone"]
        missing = [f for f in required if not args.get(f)]
        
        if missing:
            return {
                "success": False,
                "message": f"I still need: {', '.join(missing)} to complete the booking."
            }
        
        # Parse date and time
        try:
            appt_date = date.fromisoformat(args["date"])
            appt_time = time.fromisoformat(args["time"])
        except ValueError as e:
            return {
                "success": False,
                "message": "I couldn't understand the date or time format. Let's try again."
            }
        
        # Create appointment
        appointment_data = AppointmentCreate(
            clinic_id=clinic_id,
            doctor_id=UUID(args["doctor_id"]),
            patient_name=args["patient_name"],
            patient_phone=args["patient_phone"],
            date=appt_date,
            time=appt_time,
            reason=args.get("reason"),
            duration_minutes=30,
        )
        
        result = await book_appointment(appointment_data)
        
        if result.get("success"):
            # Get doctor name for confirmation message
            doctor_response = (
                supabase.table("doctors")
                .select("name, title")
                .eq("id", args["doctor_id"])
                .single()
                .execute()
            )
            doctor_name = "the doctor"
            if doctor_response.data:
                doctor_name = f"{doctor_response.data['title']} {doctor_response.data['name']}"
            
            # Format date and time for voice
            formatted_date = appt_date.strftime("%A, %B %d")
            hour = appt_time.hour
            minute = appt_time.minute
            if hour < 12:
                formatted_time = f"{hour}:{minute:02d} AM"
            elif hour == 12:
                formatted_time = f"12:{minute:02d} PM"
            else:
                formatted_time = f"{hour-12}:{minute:02d} PM"
            
            return {
                "success": True,
                "appointment_id": result.get("appointment_id"),
                "message": f"Your appointment is confirmed with {doctor_name} on {formatted_date} at {formatted_time}. You'll receive a confirmation SMS shortly. Is there anything else I can help you with?"
            }
        else:
            return {
                "success": False,
                "message": result.get("message", "I couldn't complete the booking. The time slot may have just been taken. Would you like to try another time?")
            }
            
    except Exception as e:
        logger.error(f"Error booking appointment: {e}")
        return {
            "success": False,
            "message": "I'm having trouble booking the appointment. Let me try again."
        }


async def _fn_lookup_patient(clinic_id: UUID, args: Dict[str, Any]) -> Dict[str, Any]:
    """Look up patient by phone number"""
    try:
        phone = args.get("phone", "").strip()
        
        if not phone or len(phone) < 10:
            return {
                "found": False,
                "message": "I need a valid phone number to look up the patient."
            }
        
        result = await lookup_patient_by_phone(clinic_id, phone)
        
        if result.get("found"):
            patient = result["patient"]
            
            # Get upcoming appointments
            appointments_result = await get_patient_appointments(clinic_id, phone)
            upcoming = appointments_result.get("appointments", [])
            
            message = f"I found {patient['name']} in our system."
            
            if upcoming:
                next_appt = upcoming[0]
                appt_date = date.fromisoformat(next_appt["date"]).strftime("%B %d")
                message += f" They have an upcoming appointment on {appt_date}."
            
            return {
                "found": True,
                "patient": patient,
                "upcoming_appointments": upcoming,
                "message": message
            }
        else:
            return {
                "found": False,
                "message": "I don't see that phone number in our records. This may be a new patient."
            }
            
    except Exception as e:
        logger.error(f"Error looking up patient: {e}")
        return {
            "found": False,
            "message": "I'm having trouble looking up the patient records."
        }


async def _fn_cancel_appointment(clinic_id: UUID, args: Dict[str, Any]) -> Dict[str, Any]:
    """Cancel an appointment"""
    try:
        appointment_id = args.get("appointment_id")
        reason = args.get("reason")
        
        if not appointment_id:
            return {
                "success": False,
                "message": "I need the appointment ID to cancel it."
            }
        
        result = await cancel_appointment(
            clinic_id=clinic_id,
            appointment_id=UUID(appointment_id),
            cancellation_reason=reason,
        )
        
        if result.get("success"):
            return {
                "success": True,
                "message": "The appointment has been cancelled. You'll receive a confirmation SMS. Would you like to reschedule?"
            }
        else:
            return {
                "success": False,
                "message": result.get("message", "I couldn't cancel that appointment.")
            }
            
    except Exception as e:
        logger.error(f"Error cancelling appointment: {e}")
        return {
            "success": False,
            "message": "I'm having trouble cancelling the appointment."
        }


async def _fn_reschedule_appointment(clinic_id: UUID, args: Dict[str, Any]) -> Dict[str, Any]:
    """Reschedule an appointment"""
    try:
        appointment_id = args.get("appointment_id")
        new_date = args.get("new_date")
        new_time = args.get("new_time")
        
        if not all([appointment_id, new_date, new_time]):
            return {
                "success": False,
                "message": "I need the appointment ID, new date, and new time to reschedule."
            }
        
        result = await reschedule_appointment(
            clinic_id=clinic_id,
            appointment_id=UUID(appointment_id),
            new_date=date.fromisoformat(new_date),
            new_time=time.fromisoformat(new_time),
        )
        
        if result.get("success"):
            formatted_date = date.fromisoformat(new_date).strftime("%A, %B %d")
            return {
                "success": True,
                "message": f"Your appointment has been rescheduled to {formatted_date} at {new_time}. You'll receive a confirmation SMS."
            }
        else:
            return {
                "success": False,
                "message": result.get("message", "I couldn't reschedule. The new time slot may not be available.")
            }
            
    except Exception as e:
        logger.error(f"Error rescheduling appointment: {e}")
        return {
            "success": False,
            "message": "I'm having trouble rescheduling the appointment."
        }


# =============================================================================
# CALL LIFECYCLE HANDLERS
# =============================================================================

async def _handle_call_started(call: Dict[str, Any], clinic_id: UUID) -> Dict[str, Any]:
    """Handle call started event"""
    call_id = call.get("call_id")
    from_number = call.get("from_number")
    to_number = call.get("to_number")
    
    logger.info(f"Call started: {call_id} | From: {from_number} | To: {to_number} | Clinic: {clinic_id}")
    
    # Optionally: Pre-fetch patient data if from_number matches
    # This could be used to personalize the greeting
    
    return {"status": "ok"}


async def _handle_call_ended(call: Dict[str, Any], clinic_id: UUID) -> Dict[str, Any]:
    """Handle call ended event - log the call"""
    try:
        call_log_data = {
            "clinic_id": str(clinic_id),
            "retell_call_id": call.get("call_id"),
            "vapi_call_id": call.get("call_id"),  # Keeping for compatibility
            "channel": "voice",
            "direction": "inbound" if call.get("direction") == "inbound" else "outbound",
            "from_number": call.get("from_number"),
            "to_number": call.get("to_number"),
            "started_at": call.get("start_timestamp"),
            "ended_at": call.get("end_timestamp"),
            "duration_seconds": call.get("duration_seconds"),
            "outcome": _map_disconnect_reason(call.get("disconnection_reason")),
        }
        
        # Insert call log
        result = supabase.table("call_logs").insert(call_log_data).execute()
        
        logger.info(f"Call ended and logged: {call.get('call_id')} for clinic {clinic_id}")
        
        return {"status": "ok"}
        
    except Exception as e:
        logger.error(f"Error logging call end: {e}")
        return {"status": "error", "error": str(e)}


async def _handle_call_analyzed(call: Dict[str, Any], clinic_id: UUID) -> Dict[str, Any]:
    """Handle post-call analysis event"""
    try:
        call_id = call.get("call_id")
        transcript = call.get("transcript")
        summary = call.get("call_summary")
        sentiment = call.get("user_sentiment")
        
        # Update call log with analysis
        update_data = {}
        if transcript:
            update_data["transcript"] = transcript
        if summary:
            update_data["summary"] = summary
        
        if update_data:
            supabase.table("call_logs").update(update_data).eq(
                "retell_call_id", call_id
            ).execute()
        
        logger.info(f"Call analysis saved for: {call_id}")
        
        return {"status": "ok"}
        
    except Exception as e:
        logger.error(f"Error saving call analysis: {e}")
        return {"status": "error", "error": str(e)}


def _map_disconnect_reason(reason: Optional[str]) -> str:
    """Map Retell disconnect reason to our outcome types"""
    if not reason:
        return "missed"
    
    reason_lower = reason.lower()
    
    if "agent_ended" in reason_lower or "completed" in reason_lower:
        return "info_provided"  # Default success outcome
    elif "user_ended" in reason_lower or "hangup" in reason_lower:
        return "info_provided"
    elif "no_answer" in reason_lower or "busy" in reason_lower:
        return "missed"
    elif "error" in reason_lower or "failed" in reason_lower:
        return "missed"
    else:
        return "info_provided"


# =============================================================================
# ADMIN ENDPOINTS
# =============================================================================

@router.post("/agents/create/{clinic_id}")
async def create_retell_agent_endpoint(clinic_id: UUID):
    """Create a Retell AI agent for a clinic"""
    from app.services.retell import create_clinic_agent
    
    result = await create_clinic_agent(clinic_id)
    
    if result.get("success"):
        return {
            "success": True,
            "agent_id": result["agent_id"],
            "message": f"Retell agent created for clinic {clinic_id}"
        }
    else:
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to create agent"))


@router.post("/phone/provision/{clinic_id}")
async def provision_phone_endpoint(clinic_id: UUID, area_code: str = "234"):
    """Provision a phone number for a clinic"""
    from app.services.retell import provision_phone_number
    
    result = await provision_phone_number(clinic_id, area_code)
    
    if result.get("success"):
        return {
            "success": True,
            "phone_number": result["phone_number"],
            "phone_id": result["phone_id"],
            "message": f"Phone number provisioned for clinic {clinic_id}"
        }
    else:
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to provision phone"))


@router.post("/agents/update/{clinic_id}")
async def update_retell_agent_endpoint(clinic_id: UUID):
    """Update a clinic's Retell agent (refresh prompt with new doctors/services)"""
    from app.services.retell import update_clinic_agent
    
    result = await update_clinic_agent(clinic_id)
    
    if result.get("success"):
        return {
            "success": True,
            "agent_id": result["agent_id"],
            "message": f"Retell agent updated for clinic {clinic_id}"
        }
    else:
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to update agent"))


@router.delete("/agents/{clinic_id}")
async def delete_retell_agent_endpoint(clinic_id: UUID):
    """Delete a clinic's Retell agent and release phone numbers"""
    from app.services.retell import delete_clinic_agent
    
    result = await delete_clinic_agent(clinic_id)
    
    if result.get("success"):
        return {
            "success": True,
            "message": f"Retell resources deleted for clinic {clinic_id}"
        }
    else:
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to delete resources"))


@router.get("/phone/{clinic_id}")
async def get_clinic_phone_numbers_endpoint(clinic_id: UUID):
    """Get all phone numbers for a clinic"""
    from app.services.retell import list_clinic_phone_numbers
    
    phone_numbers = await list_clinic_phone_numbers(clinic_id)
    
    return {
        "clinic_id": str(clinic_id),
        "phone_numbers": phone_numbers
    }
