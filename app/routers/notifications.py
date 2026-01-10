"""API router for notification testing and management"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Literal
import logging

from app.services.notifications import send_sms, send_whatsapp

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class TestNotificationRequest(BaseModel):
    phone: str
    channel: Literal["sms", "whatsapp"]
    clinic_name: str = "Curavoice"


@router.post("/test")
async def test_notification(request: TestNotificationRequest):
    """
    Send a test notification (SMS or WhatsApp).
    
    This endpoint is used by the frontend to test notification configuration.
    """
    try:
        # Build test message
        message = f"""🧪 Test Notification from {request.clinic_name}

Hi! This is a test message to verify your notification setup is working correctly.

If you received this message, your {request.channel.upper()} notifications are configured properly! ✅

Have a great day!"""

        # Get clinic name for sender ID (max 11 characters for Termii)
        sender_name = request.clinic_name[:11]

        # Send via selected channel
        if request.channel == "sms":
            result = await send_sms(request.phone, message, sender_id=sender_name)
        elif request.channel == "whatsapp":
            result = await send_whatsapp(request.phone, message)
        else:
            raise HTTPException(status_code=400, detail="Invalid channel")

        if not result.get("success"):
            raise HTTPException(
                status_code=500,
                detail=result.get("error", "Failed to send notification")
            )

        return {
            "success": True,
            "message": f"Test {request.channel} sent successfully",
            "message_id": result.get("message_id"),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending test notification: {e}")
        raise HTTPException(status_code=500, detail=str(e))

