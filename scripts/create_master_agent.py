"""
One-time script to create the master Retell conversation agent.
Run this ONCE during platform setup, not per clinic.

Usage:
    python backend/scripts/create_master_agent.py

Output:
    Prints the master agent ID to console.
    Add this to your environment: RETELL_MASTER_AGENT_ID=agent_xxx
"""

import asyncio
import httpx
import os
import sys

RETELL_API_BASE = "https://api.retellai.com"


async def create_master_agent():
    """Create master conversation flow agent that serves ALL clinics"""
    
    # Get API key from environment
    api_key = os.getenv("RETELL_API_KEY")
    if not api_key:
        print("ERROR: RETELL_API_KEY environment variable not set")
        print("Please set RETELL_API_KEY in backend/.env file")
        sys.exit(1)
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # 1. Create LLM configuration with multi-tenant prompt
            print("Creating LLM configuration...")
            llm_response = await client.post(
                f"{RETELL_API_BASE}/create-retell-llm",
                headers=headers,
                json={
                    "general_prompt": """You are a helpful medical receptionist for {{clinic_name}}.

Your role is to:
1. Greet patients warmly in their language
2. Help them book, cancel, or reschedule appointments
3. Provide information about doctors and clinic hours
4. Transfer urgent cases to clinic staff

Clinic Information (injected dynamically per call):
- Clinic Name: {{clinic_name}}
- Address: {{clinic_address}}
- Phone: {{clinic_phone}}
- Hours: {{business_hours}}

Available Doctors:
{{available_doctors}}

IMPORTANT RULES:
- Always confirm appointment details before booking
- Ask for patient name and phone number
- Be polite, professional, and patient
- If you don't understand, ask for clarification
- For emergencies, immediately offer to transfer to staff

Language Support:
- Detect the patient's language automatically
- Respond in the same language throughout the call
- Supported languages: English, Nigerian Pidgin, Yoruba, French, Arabic

Custom Greeting (if provided):
{{greeting_custom}}""",
                    "enable_backchannel": True,
                    "model": "gpt-4o",
                    "fallback_model": "gpt-3.5-turbo",
                },
            )
            
            if llm_response.status_code >= 400:
                print(f"ERROR creating LLM: {llm_response.text}")
                return None
            
            llm_data = llm_response.json()
            llm_id = llm_data["llm_id"]
            print(f"[OK] LLM created: {llm_id}")
            
            # 2. Create agent with multilingual support
            print("Creating agent...")
            agent_response = await client.post(
                f"{RETELL_API_BASE}/create-agent",
                headers=headers,
                json={
                    "response_engine": {
                        "type": "retell-llm",
                        "llm_id": llm_id
                    },
                    "voice_id": "openai-Alloy",  # OpenAI voice
                    "language": "en-US",  # English US as default
                    "enable_backchannel": True,
                    "responsiveness": 0.8,  # Slightly conservative
                    "interruption_sensitivity": 0.5,  # Moderate interruption
                    "reminder_trigger_ms": 10000,  # Remind after 10s silence
                    "boosted_keywords": [
                        "appointment", "doctor", "available",
                        "cancel", "reschedule", "emergency"
                    ],
                },
            )
            
            if agent_response.status_code >= 400:
                print(f"ERROR creating agent: {agent_response.text}")
                return None
            
            agent_data = agent_response.json()
            agent_id = agent_data["agent_id"]
            print(f"[OK] Agent created: {agent_id}")
            
            return agent_id
    
    except httpx.RequestError as e:
        print(f"ERROR: Network error connecting to Retell API: {e}")
        return None
    except Exception as e:
        print(f"ERROR: Unexpected error: {e}")
        return None


if __name__ == "__main__":
    print("="*60)
    print("Creating Master Retell Conversation Agent")
    print("="*60)
    print()
    
    agent_id = asyncio.run(create_master_agent())
    
    if agent_id:
        print()
        print("="*60)
        print("SUCCESS! Master agent created.")
        print("="*60)
        print()
        print("Add this to your environment variables:")
        print()
        print(f"RETELL_MASTER_AGENT_ID={agent_id}")
        print()
        print("This agent will serve ALL clinics.")
        print("="*60)
    else:
        print()
        print("Failed to create master agent.")
        sys.exit(1)

