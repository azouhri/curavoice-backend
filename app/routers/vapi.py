"""Vapi.ai webhook handlers"""

import logging
from datetime import date, time, datetime
from uuid import UUID
from fastapi import APIRouter, Request, HTTPException, Header
from typing import Optional, Dict, Any
from app.config import settings, supabase
from app.services.availability import check_doctor_availability
from app.services.appointments import (
    book_appointment,
    cancel_appointment,
    reschedule_appointment,
    get_patient_appointments,
)
from app.services.patients import lookup_patient_by_phone
from app.services.call_logs import create_call_log
from app.services.vapi import create_clinic_assistant
from app.models.schemas import AppointmentCreate

logger = logging.getLogger(__name__)

router = APIRouter()


def verify_webhook_secret(secret: Optional[str]) -> bool:
    """Verify webhook secret matches configured secret"""
    if not settings.vapi_webhook_secret:
        logger.warning("Vapi webhook secret not configured")
        return False
    
    return secret == settings.vapi_webhook_secret


async def handle_function_call(
    function_name: str,
    parameters: Dict[str, Any],
    clinic_id: UUID,
) -> Dict[str, Any]:
    """
    Handle Vapi function call.
    
    Args:
        function_name: Name of the function being called
        parameters: Function parameters
        clinic_id: Clinic UUID from call metadata
        
    Returns:
        Function result dict
    """
    try:
        if function_name == "check_availability":
            doctor_id = UUID(parameters["doctor_id"])
            target_date = date.fromisoformat(parameters["date"])
            
            result = await check_doctor_availability(doctor_id, target_date, clinic_id)
            return result
            
        elif function_name == "book_appointment":
            appointment_data = AppointmentCreate(
                clinic_id=clinic_id,
                doctor_id=UUID(parameters["doctor_id"]),
                patient_name=parameters["patient_name"],
                patient_phone=parameters["patient_phone"],
                date=date.fromisoformat(parameters["date"]),
                time=time.fromisoformat(parameters["time"]),
                reason=parameters.get("reason"),
                appointment_type_id=UUID(parameters["appointment_type_id"]) if parameters.get("appointment_type_id") else None,
                duration_minutes=parameters.get("duration_minutes", 30),
            )
            
            result = await book_appointment(appointment_data)
            return result
            
        elif function_name == "lookup_patient":
            phone = parameters["phone"]
            
            result = await lookup_patient_by_phone(clinic_id, phone)
            
            # Also get patient's upcoming appointments
            appointments_result = await get_patient_appointments(clinic_id, phone)
            result["appointments"] = appointments_result.get("appointments", [])
            result["appointment_count"] = appointments_result.get("count", 0)
            
            return result
            
        elif function_name == "cancel_appointment":
            appointment_id = UUID(parameters["appointment_id"])
            cancellation_reason = parameters.get("reason")
            
            result = await cancel_appointment(
                clinic_id=clinic_id,
                appointment_id=appointment_id,
                cancellation_reason=cancellation_reason,
            )
            return result
            
        elif function_name == "reschedule_appointment":
            appointment_id = UUID(parameters["appointment_id"])
            new_date = date.fromisoformat(parameters["new_date"])
            new_time = time.fromisoformat(parameters["new_time"])
            
            result = await reschedule_appointment(
                clinic_id=clinic_id,
                appointment_id=appointment_id,
                new_date=new_date,
                new_time=new_time,
            )
            return result
            
        elif function_name == "get_clinic_info":
            info_type = parameters["info_type"]
            
            # Get clinic info
            clinic_response = (
                supabase.table("clinics")
                .select("*")
                .eq("id", str(clinic_id))
                .execute()
            )
            
            if not clinic_response.data or len(clinic_response.data) == 0:
                return {
                    "info_type": info_type,
                    "data": {},
                    "message": "Clinic not found",
                }
            
            clinic = clinic_response.data[0]
            
            if info_type == "hours":
                # Get doctor working hours
                doctors_response = (
                    supabase.table("doctors")
                    .select("working_hours")
                    .eq("clinic_id", str(clinic_id))
                    .eq("is_active", True)
                    .execute()
                )
                
                return {
                    "info_type": info_type,
                    "data": {
                        "working_hours": doctors_response.data[0]["working_hours"] if doctors_response.data else {},
                    },
                    "message": "Clinic hours retrieved",
                }
                
            elif info_type == "address":
                return {
                    "info_type": info_type,
                    "data": {
                        "address": clinic.get("address"),
                        "city": clinic.get("city"),
                        "country": clinic.get("country"),
                    },
                    "message": "Clinic address retrieved",
                }
                
            elif info_type == "services":
                # Get appointment types
                services_response = (
                    supabase.table("appointment_types")
                    .select("name, name_pidgin, name_yoruba, name_french, name_arabic, duration_minutes, price")
                    .eq("clinic_id", str(clinic_id))
                    .eq("is_active", True)
                    .execute()
                )
                
                return {
                    "info_type": info_type,
                    "data": {
                        "services": services_response.data or [],
                    },
                    "message": "Clinic services retrieved",
                }
                
            elif info_type == "doctors":
                # Get active doctors
                doctors_response = (
                    supabase.table("doctors")
                    .select("name, title, specialty")
                    .eq("clinic_id", str(clinic_id))
                    .eq("is_active", True)
                    .execute()
                )
                
                return {
                    "info_type": info_type,
                    "data": {
                        "doctors": doctors_response.data or [],
                    },
                    "message": "Clinic doctors retrieved",
                }
            
            return {
                "info_type": info_type,
                "data": {},
                "message": f"Unknown info type: {info_type}",
            }
            
        else:
            logger.warning(f"Unknown function: {function_name}")
            return {
                "error": f"Unknown function: {function_name}",
                "message": "Function not implemented",
            }
            
    except Exception as e:
        logger.error(f"Error handling function call {function_name}: {e}")
        return {
            "error": str(e),
            "message": f"Error processing {function_name}",
        }


async def handle_call_ended(
    call_data: Dict[str, Any],
    clinic_id: UUID,
) -> Dict[str, Any]:
    """
    Handle call ended event.
    
    Args:
        call_data: Call data from Vapi webhook
        clinic_id: Clinic UUID from call metadata
        
    Returns:
        Success status
    """
    try:
        vapi_call_id = call_data.get("id")
        from_number = call_data.get("from")
        to_number = call_data.get("to")
        started_at_str = call_data.get("startedAt")
        ended_at_str = call_data.get("endedAt")
        duration = call_data.get("duration")
        
        started_at = datetime.fromisoformat(started_at_str.replace("Z", "+00:00")) if started_at_str else None
        ended_at = datetime.fromisoformat(ended_at_str.replace("Z", "+00:00")) if ended_at_str else None
        
        # Create call log
        await create_call_log(
            clinic_id=clinic_id,
            vapi_call_id=vapi_call_id,
            from_number=from_number,
            to_number=to_number,
            started_at=started_at,
            ended_at=ended_at,
            duration_seconds=duration,
            transcript=call_data.get("transcript"),
            summary=call_data.get("summary"),
            detected_language=call_data.get("detected_language"),
            outcome=call_data.get("outcome"),
            cost_usd=call_data.get("cost"),
        )
        
        logger.info(f"Call ended logged: {vapi_call_id} for clinic {clinic_id}")
        
        return {"status": "ok", "message": "Call log created"}
        
    except Exception as e:
        logger.error(f"Error handling call ended: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/webhook")
async def handle_vapi_webhook(
    request: Request,
    x_vapi_secret: Optional[str] = Header(None, alias="x-vapi-secret"),
):
    """
    Handle webhook events from Vapi.ai
    
    Events:
    - function-call: AI assistant calls a function
    - end-of-call-report: Call ended, includes transcript and summary
    """
    # Verify webhook secret
    if not verify_webhook_secret(x_vapi_secret):
        logger.warning(f"Invalid webhook secret from {request.client.host}")
        raise HTTPException(status_code=401, detail="Invalid webhook secret")
    
    try:
        body = await request.json()
        message = body.get("message", {})
        message_type = message.get("type")
        
        # Extract clinic_id from call metadata or assistant_id lookup
        call_data = message.get("call", {})
        metadata = call_data.get("metadata", {})
        clinic_id_str = metadata.get("clinic_id")
        
        # If no clinic_id in metadata, lookup by assistant_id
        if not clinic_id_str:
            assistant_id = call_data.get("assistantId")
            if assistant_id:
                logger.info(f"Looking up clinic_id from assistant_id: {assistant_id}")
                clinic_response = (
                    supabase.table("clinics")
                    .select("id")
                    .eq("vapi_assistant_id", assistant_id)
                    .maybe_single()
                    .execute()
                )
                if clinic_response.data:
                    clinic_id_str = clinic_response.data["id"]
                    logger.info(f"Found clinic_id: {clinic_id_str}")
                else:
                    logger.error(f"No clinic found for assistant_id: {assistant_id}")
                    return {"status": "error", "message": "Clinic not found for this assistant"}
            else:
                logger.error("Missing both clinic_id and assistant_id in webhook")
                return {"status": "error", "message": "Missing clinic identification"}
        
        clinic_id = UUID(clinic_id_str)
        
        if message_type == "function-call":
            function_call = message.get("functionCall", {})
            function_name = function_call.get("name")
            
            # CRITICAL FIX: Vapi prefixes function names with "run-"
            if function_name and function_name.startswith("run-"):
                function_name = function_name[4:]  # Remove "run-" prefix
                logger.info(f"Stripped 'run-' prefix from function name: {function_name}")
            
            parameters = function_call.get("parameters", {})
            
            logger.info(f"Function call: {function_name} for clinic {clinic_id}")
            
            result = await handle_function_call(function_name, parameters, clinic_id)
            
            return {
                "status": "ok",
                "result": result,
            }
            
        elif message_type == "end-of-call-report":
            logger.info(f"Call ended for clinic {clinic_id}")
            
            result = await handle_call_ended(call_data, clinic_id)
            
            return {
                "status": "ok",
                "result": result,
            }
            
        else:
            logger.warning(f"Unknown message type: {message_type}")
            return {
                "status": "ok",
                "message": f"Unknown message type: {message_type}",
            }
            
    except Exception as e:
        logger.error(f"Error processing webhook: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error processing webhook: {str(e)}")


@router.post("/assistants/create/{clinic_id}")
async def create_assistant_for_clinic(clinic_id: UUID):
    """
    Create a Vapi AI assistant for a clinic.
    
    This endpoint will:
    1. Fetch clinic data from database
    2. Generate customized system prompt
    3. Create Vapi assistant via API
    4. Store assistant_id in clinic record
    
    Args:
        clinic_id: UUID of the clinic
        
    Returns:
        Success status and assistant_id
    """
    try:
        result = await create_clinic_assistant(clinic_id)
        
        if not result.get("success"):
            raise HTTPException(
                status_code=400, 
                detail=result.get("error", "Failed to create assistant")
            )
        
        return {
            "success": True,
            "assistant_id": result.get("assistant_id"),
            "message": f"Vapi assistant created successfully for clinic {clinic_id}",
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating assistant for clinic {clinic_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error creating assistant: {str(e)}"
        )


@router.post("/assistants/update/{clinic_id}")
async def update_assistant_for_clinic(clinic_id: UUID):
    """
    Update a Vapi AI assistant for a clinic when settings change.
    
    This endpoint will:
    1. Fetch clinic data from database
    2. Generate updated system prompt
    3. Update Vapi assistant via API
    
    Args:
        clinic_id: UUID of the clinic
        
    Returns:
        Success status
    """
    try:
        # Get clinic data
        clinic_response = (
            supabase.table("clinics")
            .select("*")
            .eq("id", str(clinic_id))
            .execute()
        )
        
        if not clinic_response.data or len(clinic_response.data) == 0:
            raise HTTPException(status_code=404, detail="Clinic not found")
        
        clinic = clinic_response.data[0]
        assistant_id = clinic.get("vapi_assistant_id")
        
        if not assistant_id:
            # No assistant exists yet, create one instead
            return await create_assistant_for_clinic(clinic_id)
        
        # Generate updated system prompt
        from app.services.vapi import generate_system_prompt
        system_prompt = await generate_system_prompt(clinic_id)
        
        # Update assistant via Vapi API
        url = f"https://api.vapi.ai/assistant/{assistant_id}"
        headers = {
            "Authorization": f"Bearer {settings.vapi_api_key}",
            "Content-Type": "application/json",
        }
        
        assistant_config = {
            "firstMessage": clinic.get("greeting_template") or f"Hello! Welcome to {clinic['name']}. How can I help you today?",
            "systemPrompt": system_prompt,
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.patch(url, json=assistant_config, headers=headers, timeout=30.0)
            response.raise_for_status()
        
        logger.info(f"Updated Vapi assistant {assistant_id} for clinic {clinic_id}")
        
        return {
            "success": True,
            "message": f"Vapi assistant updated successfully for clinic {clinic_id}",
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating assistant for clinic {clinic_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error updating assistant: {str(e)}"
        )
