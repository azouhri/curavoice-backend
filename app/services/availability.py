"""Availability service for checking doctor availability"""

import logging
from datetime import date, time, timedelta
from uuid import UUID
from typing import List, Dict, Any
from app.config import supabase

logger = logging.getLogger(__name__)


def _time_to_minutes(t: time) -> int:
    """Convert time to minutes since midnight"""
    return t.hour * 60 + t.minute


def _minutes_to_time(minutes: int) -> time:
    """Convert minutes since midnight to time"""
    hours = minutes // 60
    mins = minutes % 60
    return time(hours, mins)


async def check_doctor_availability(
    doctor_id: UUID,
    target_date: date,
    clinic_id: UUID,
) -> Dict[str, Any]:
    """
    Check available appointment slots for a doctor on a specific date.
    
    Args:
        doctor_id: Doctor UUID
        target_date: Date to check availability
        clinic_id: Clinic UUID
        
    Returns:
        Dict with 'available' (bool), 'slots' (list of time strings), and 'message' (str)
    """
    try:
        # Get doctor info
        doctor_response = (
            supabase.table("doctors")
            .select("*")
            .eq("id", str(doctor_id))
            .eq("clinic_id", str(clinic_id))
            .execute()
        )
        
        if not doctor_response.data or len(doctor_response.data) == 0:
            return {
                "available": False,
                "slots": [],
                "message": "Doctor not found",
            }
        
        doctor = doctor_response.data[0]
        
        if not doctor.get("is_active", True):
            return {
                "available": False,
                "slots": [],
                "message": "Doctor is not active",
            }
        
        # Get working hours for the day of week
        day_name = target_date.strftime("%A").lower()
        working_hours = doctor.get("working_hours", {})
        day_schedule = working_hours.get(day_name, {})
        
        if not day_schedule.get("enabled", False):
            return {
                "available": False,
                "slots": [],
                "message": f"Doctor not available on {day_name}",
            }
        
        start_time_str = day_schedule.get("start", "09:00")
        end_time_str = day_schedule.get("end", "17:00")
        
        # Parse times
        start_hour, start_min = map(int, start_time_str.split(":"))
        end_hour, end_min = map(int, end_time_str.split(":"))
        start_time = time(start_hour, start_min)
        end_time = time(end_hour, end_min)
        
        slot_duration = doctor.get("slot_duration", 30)
        buffer_time = doctor.get("buffer_time", 5)
        
        # Get existing appointments for this date
        appointments_response = (
            supabase.table("appointments")
            .select("time, duration_minutes")
            .eq("doctor_id", str(doctor_id))
            .eq("date", target_date.isoformat())
            .in_("status", ["scheduled", "confirmed"])
            .execute()
        )
        
        booked_slots = []
        for apt in appointments_response.data or []:
            apt_time = time.fromisoformat(apt["time"])
            duration = apt.get("duration_minutes", slot_duration)
            booked_slots.append({
                "start": _time_to_minutes(apt_time),
                "end": _time_to_minutes(apt_time) + duration,
            })
        
        # Get break times
        break_times = doctor.get("break_times", [])
        break_slots = []
        for break_time in break_times:
            break_start = time.fromisoformat(break_time["start"])
            break_end = time.fromisoformat(break_time["end"])
            break_slots.append({
                "start": _time_to_minutes(break_start),
                "end": _time_to_minutes(break_end),
            })
        
        # Get blocked times
        blocked_response = (
            supabase.table("blocked_times")
            .select("start_datetime, end_datetime")
            .eq("clinic_id", str(clinic_id))
            .or_(f"doctor_id.eq.{doctor_id},doctor_id.is.null")
            .gte("start_datetime", target_date.isoformat())
            .lte("end_datetime", (target_date + timedelta(days=1)).isoformat())
            .execute()
        )
        
        blocked_slots = []
        for blocked in blocked_response.data or []:
            start_dt = blocked["start_datetime"]
            end_dt = blocked["end_datetime"]
            # Convert to minutes for the target date
            # Simplified - assumes blocked time is on the same date
            blocked_slots.append({
                "start": _time_to_minutes(time.fromisoformat(start_dt.split("T")[1][:5])),
                "end": _time_to_minutes(time.fromisoformat(end_dt.split("T")[1][:5])),
            })
        
        # Calculate available slots
        available_slots = []
        start_minutes = _time_to_minutes(start_time)
        end_minutes = _time_to_minutes(end_time)
        current_minutes = start_minutes
        
        while current_minutes + slot_duration <= end_minutes:
            slot_start = current_minutes
            slot_end = current_minutes + slot_duration
            
            # Check if slot conflicts with booked appointments
            conflicts = False
            for booked in booked_slots + break_slots + blocked_slots:
                if not (slot_end <= booked["start"] or slot_start >= booked["end"]):
                    conflicts = True
                    break
            
            if not conflicts:
                available_slots.append(_minutes_to_time(slot_start))
            
            current_minutes += slot_duration + buffer_time
        
        return {
            "available": len(available_slots) > 0,
            "slots": [t.strftime("%H:%M") for t in available_slots],
            "message": f"Found {len(available_slots)} available slots" if available_slots else "No available slots",
        }
        
    except Exception as e:
        logger.error(f"Error in check_doctor_availability: {e}")
        return {
            "available": False,
            "slots": [],
            "message": f"Error checking availability: {str(e)}",
        }

