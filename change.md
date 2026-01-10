TL;DR: Use ONE Conversation Flow for All Clinics
✅ ONE master conversation flow template
✅ Different phone numbers per clinic
✅ Dynamic variables to customize per clinic
✅ Clinic identification via phone number or clinic_id

Architecture Overview
How It Works:
Clinic A (Phone: +1234567890) ──┐
Clinic B (Phone: +0987654321) ──┼──→ [Same Conversation Flow] ──→ Customized via dynamic variables
Clinic C (Phone: +1122334455) ──┘
Key Concept: The conversation flow logic is the same for all clinics, but the data (doctors, availability, clinic name) is different and injected dynamically.

Step-by-Step Implementation
1. Create ONE Master Conversation Flow
Build a single, reusable conversation flow that works for ANY clinic:
Example Structure:
[Start] → "Hello, you've reached {{clinic_name}}"
   ↓
[Conversation: Ask how to help]
   ↓
[Function: get_available_doctors]
   - Pass: clinic_id
   ↓
[Present doctors for THIS clinic]
   ↓
[Extract: doctor_id, doctor_name]
   ↓
[Function: check_availability]
   - Pass: clinic_id, doctor_id
   ↓
[Book appointment]
   ↓
[SMS confirmation to {{clinic_phone}}]
IMPORTANT: Notice {{clinic_name}}, {{clinic_id}}, {{clinic_phone}} - these are dynamic variables!

2. Register Unique Phone Numbers per Clinic
During onboarding:
Python Example:
pythonfrom retell import Retell

retell = Retell(api_key=os.environ["RETELL_API_KEY"])

async def onboard_clinic(clinic_data):
    # 1. Save clinic to your database
    clinic = await db.clinics.create({
        "name": clinic_data["name"],
        "address": clinic_data["address"],
        "doctors": clinic_data["doctors"],
        # ... other clinic details
    })
    
    # 2. Purchase/Register phone number with Retell
    phone_number = await retell.phone_number.create(
        area_code=clinic_data["area_code"],  # e.g., 229 for Benin
        # Retell will assign a number
    )
    
    # 3. Update clinic with phone number
    clinic.phone_number = phone_number.number
    await clinic.save()
    
    # 4. Link phone number to your MASTER agent
    await retell.phone_number.update(
        phone_number=phone_number.number,
        agent_id=MASTER_AGENT_ID,  # Same agent for all clinics!
        
        # CRITICAL: Set inbound webhook to inject clinic_id
        inbound_webhook_url=f"https://yoursaas.com/webhooks/retell/inbound/{clinic.id}"
    )
    
    return clinic

3. Use Inbound Webhook to Inject Clinic Data
When a call comes in, Retell hits your webhook. This is where you identify the clinic and inject dynamic variables.
Your Webhook Endpoint:
pythonfrom fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI()

@app.post("/webhooks/retell/inbound/{clinic_id}")
async def handle_inbound_call(clinic_id: str, request: Request):
    """
    Retell calls this when someone calls a clinic's number
    """
    
    # 1. Get clinic details from your database
    clinic = await db.clinics.get(clinic_id)
    
    if not clinic:
        return JSONResponse(
            status_code=404,
            content={"error": "Clinic not found"}
        )
    
    # 2. Get doctors for this clinic
    doctors = await db.doctors.filter(clinic_id=clinic_id)
    
    # 3. Format doctors for the agent
    doctors_list = "\n".join([
        f"- Dr. {doc.name} ({doc.specialty}) - ID: {doc.id}"
        for doc in doctors
    ])
    
    # 4. Return dynamic variables to Retell
    return JSONResponse(
        status_code=200,
        content={
            "agent_id": MASTER_AGENT_ID,  # Your master conversation flow agent
            
            # INJECT CLINIC-SPECIFIC DATA
            "retell_llm_dynamic_variables": {
                "clinic_id": clinic_id,
                "clinic_name": clinic.name,
                "clinic_address": clinic.address,
                "clinic_phone": clinic.phone_number,
                "available_doctors": doctors_list,
                "business_hours": clinic.business_hours,
                "language": clinic.preferred_language  # "fr" for Francophone
            }
        }
    )
```

**What Happens:**
1. Patient calls `+229 12345678` (Clinic A's number)
2. Retell receives call and hits: `https://yoursaas.com/webhooks/retell/inbound/clinic_a_id`
3. Your webhook returns clinic A's specific data as dynamic variables
4. The SAME conversation flow runs, but with Clinic A's data

---

### **4. Use Dynamic Variables in Conversation Flow**

**In your Conversation Flow nodes:**

**Node 1: Greeting**
```
Instruction (Prompt):
"Greet the caller warmly and say: 
'Hello, you've reached {{clinic_name}}. How can I help you today?'"
```

**Node 2: List Doctors**
```
Instruction (Prompt):
"Say: 'We have the following doctors available:
{{available_doctors}}

Which doctor would you like to see?'"
```

**Node 3: Custom Function - Get Availability**
```
Function: check_doctor_availability
Parameters:
{
  "type": "object",
  "required": ["clinic_id", "doctor_id"],
  "properties": {
    "clinic_id": {
      "type": "string",
      "const": "{{clinic_id}}"
    },
    "doctor_id": {
      "type": "string",
      "const": "{{chosen_doctor_id}}"
    },
    "date": {
      "type": "string",
      "description": "Requested appointment date"
    }
  }
}

5. Custom Functions Use clinic_id
Your custom functions identify which clinic's data to fetch:
check_doctor_availability Endpoint:
python@app.post("/api/check-availability")
async def check_availability(request: Request):
    # Verify Retell signature
    if not Retell.verify(
        json.dumps(await request.json()),
        os.environ["RETELL_API_KEY"],
        request.headers.get("X-Retell-Signature")
    ):
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    
    data = await request.json()
    args = data["args"]
    
    # Extract parameters
    clinic_id = args["clinic_id"]  # ← From dynamic variable
    doctor_id = args["doctor_id"]
    date = args["date"]
    
    # Query YOUR database for THIS clinic's availability
    slots = await db.appointments.get_available_slots(
        clinic_id=clinic_id,
        doctor_id=doctor_id,
        date=date
    )
    
    if not slots:
        return JSONResponse(
            status_code=200,
            content={
                "message": f"Sorry, no slots available on {date}. Would you like to try another date?"
            }
        )
    
    # Format slots
    slots_text = ", ".join([slot.time for slot in slots])
    
    return JSONResponse(
        status_code=200,
        content={
            "message": f"Available times: {slots_text}. Which time works best?",
            "available_slots": [slot.dict() for slot in slots]
        }
    )

Complete Onboarding Flow
python# 1. When clinic registers on your SaaS
async def onboard_new_clinic(clinic_data):
    
    # Step 1: Create clinic in YOUR database
    clinic = await create_clinic_in_db(clinic_data)
    
    # Step 2: Purchase phone number from Retell
    phone = await purchase_retell_number(
        area_code=clinic_data["country_code"]
    )
    
    # Step 3: Link phone to MASTER agent with webhook
    await retell.phone_number.update(
        phone_number=phone.number,
        agent_id=MASTER_AGENT_ID,  # SAME agent for all
        inbound_webhook_url=f"https://yoursaas.com/webhooks/retell/inbound/{clinic.id}"
    )
    
    # Step 4: Update clinic with phone number
    clinic.phone_number = phone.number
    await clinic.save()
    
    # Step 5: Send confirmation to clinician
    await send_email(
        to=clinic.owner_email,
        subject="Your AI Receptionist is Ready!",
        body=f"Your clinic phone number: {phone.number}"
    )
    
    return {
        "clinic_id": clinic.id,
        "phone_number": phone.number,
        "agent_id": MASTER_AGENT_ID,
        "status": "active"
    }

Benefits of This Architecture
✅ Single Source of Truth

ONE conversation flow to maintain
Update once, applies to all clinics
No duplication

✅ Scalability

Add 1,000 clinics without creating 1,000 agents
Each clinic gets unique phone number
Same infrastructure

✅ Easy Updates

Improve conversation flow → all clinics benefit
Fix a bug → fixed for everyone
Add new feature → available to all

✅ Cost Effective

One agent configuration
Pay per phone number + usage
No per-agent fees

✅ Data Isolation

Each clinic's data stays separate in YOUR database
clinic_id ensures correct data fetched
HIPAA/GDPR compliant architecture


Important Considerations
1. Agent Creation Strategy
Option A: Create Master Agent Once (RECOMMENDED)
python# Run this ONCE when setting up your SaaS
MASTER_AGENT_ID = await create_master_conversation_flow()
# Store this ID in your environment variables
```

**Option B: Create Per Clinic (NOT RECOMMENDED)**
- Creates maintenance nightmare
- 1000 clinics = 1000 agents to update
- Don't do this!

---

### **2. Phone Number Management**

**Inbound Calls:**
```
Phone number → Retell receives → Calls your webhook with phone # → 
You identify clinic → Return dynamic variables → Call proceeds
Outbound Calls:
python# When making outbound appointment reminder
await retell.call.create_phone_call(
    from_number=clinic.phone_number,  # Each clinic's unique number
    to_number=patient.phone_number,
    agent_id=MASTER_AGENT_ID,
    retell_llm_dynamic_variables={
        "clinic_id": clinic.id,
        "clinic_name": clinic.name,
        "patient_name": patient.name,
        "appointment_time": appointment.time
    }
)

3. Language Handling
For Francophone markets:
In Dynamic Variables:
json{
  "clinic_id": "clinic_123",
  "clinic_name": "Clinique Benin",
  "language": "fr"
}
In Global Settings:
python# When creating master agent
conversation_flow = await retell.conversationFlow.create({
    "language": "french",  # or "multilingual"
    "voice_id": "french_voice_id",
    # ... rest of config
})

4. Testing Strategy
python# Test with different clinic IDs
test_cases = [
    {"clinic_id": "clinic_a", "expected_doctors": ["Dr. Smith", "Dr. Jones"]},
    {"clinic_id": "clinic_b", "expected_doctors": ["Dr. Ahmed", "Dr. Hassan"]},
]

for test in test_cases:
    response = await simulate_call(
        agent_id=MASTER_AGENT_ID,
        dynamic_variables={"clinic_id": test["clinic_id"]}
    )
    assert_doctors_match(response, test["expected_doctors"])

Database Schema Suggestion
sql-- Clinics table
CREATE TABLE clinics (
    id UUID PRIMARY KEY,
    name VARCHAR(255),
    phone_number VARCHAR(20) UNIQUE,
    retell_agent_id VARCHAR(100),  -- MASTER_AGENT_ID for all
    country_code VARCHAR(10),
    language VARCHAR(10),
    created_at TIMESTAMP
);

-- Doctors table
CREATE TABLE doctors (
    id UUID PRIMARY KEY,
    clinic_id UUID REFERENCES clinics(id),
    name VARCHAR(255),
    specialty VARCHAR(100),
    email VARCHAR(255)
);

-- Appointments table
CREATE TABLE appointments (
    id UUID PRIMARY KEY,
    clinic_id UUID REFERENCES clinics(id),
    doctor_id UUID REFERENCES doctors(id),
    patient_name VARCHAR(255),
    patient_phone VARCHAR(20),
    appointment_date DATE,
    appointment_time TIME,
    status VARCHAR(50)
);
```

---

## **Summary: Your SaaS Architecture**
```
┌──────────────────────────────────────────────┐
│         Your SaaS Platform                   │
│  ┌────────────────────────────────────────┐  │
│  │  Clinic A                              │  │
│  │  Phone: +229-1234-5678                 │  │
│  │  Doctors: Dr. Smith, Dr. Ahmed         │  │
│  └────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────┐  │
│  │  Clinic B                              │  │
│  │  Phone: +229-9876-5432                 │  │
│  │  Doctors: Dr. Jones, Dr. Hassan        │  │
│  └────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────┐  │
│  │  Clinic C (100+ more...)               │  │
│  └────────────────────────────────────────┘  │
└──────────────────┬───────────────────────────┘
                   │
                   ↓
        ┌──────────────────────┐
        │  Inbound Webhook     │
        │  /webhooks/retell/   │
        │  inbound/{clinic_id} │
        └──────────┬───────────┘
                   │
                   ↓ Inject dynamic variables
        ┌──────────────────────┐
        │   Retell AI          │
        │  SINGLE MASTER AGENT │
        │  (Conversation Flow) │
        └──────────┬───────────┘
                   │
                   ↓ Custom functions with clinic_id
        ┌──────────────────────┐
        │  Your API Endpoints  │
        │  - Get doctors       │
        │  - Check availability│
        │  - Book appointment  │
        └──────────────────────┘

Answer to your question:

✅ ONE conversation flow for all clinics
✅ Different phone numbers per clinic
✅ Clinic identified via inbound webhook
✅ Dynamic variables customize each call
✅ Custom functions use clinic_id to fetch correct data

Need help with the specific webhook implementation or conversation flow setup?To run code, enable code execution and file creation in Settings > Capabilities.Still I didn’t get one thing when the patient call how the conversation flow will now the clinic so the first flow should be to call a function before responding or what12:39 PMElucidated webhook mechanism for clinic identification before conversation initiation.Ah, this is THE KEY question! The user is asking: "When a patient calls, how does the conversation flow know which clinic they're calling?"
This is answered by the Inbound Webhook mechanism in Retell AI. Let me clarify this step-by-step because it's crucial for understanding.
The flow is:

Patient calls clinic's phone number (e.g., +229-1234-5678)
Retell receives the call
BEFORE starting the conversation flow, Retell calls YOUR webhook
Your webhook identifies the clinic based on the phone number
Your webhook returns dynamic variables (clinic_id, clinic_name, etc.)
THEN the conversation flow starts with those variables already available

So the conversation flow ALREADY KNOWS the clinic from the very first node because the variables were injected via the inbound webhook BEFORE the conversation started.
Let me explain this clearly with a diagram and examples.PERFECT question! This is the KEY piece. Let me clarify exactly how this works:

The Flow: What Happens When Patient Calls
Step 1: Patient dials +229-1234-5678 (Clinic A's number)
   ↓
Step 2: Retell receives the call
   ↓
Step 3: BEFORE starting conversation, Retell calls YOUR webhook
   ↓
Step 4: Your webhook identifies clinic from phone number
   ↓
Step 5: Your webhook returns clinic data as dynamic variables
   ↓
Step 6: NOW conversation flow starts WITH clinic data already loaded
   ↓
Step 7: First node says "Hello, you've reached {{clinic_name}}"
IMPORTANT: The conversation flow already knows the clinic BEFORE the first word is spoken!

How Retell Knows Which Clinic
Method 1: Inbound Webhook (RECOMMENDED)
When you register a phone number with Retell, you provide a webhook URL:
During Clinic Onboarding:
python# When Clinic A registers
await retell.phone_number.update(
    phone_number="+229-1234-5678",  # Clinic A's number
    agent_id=MASTER_AGENT_ID,
    
    # THIS IS THE KEY! 
    # Include clinic_id in the webhook URL
    inbound_webhook_url=f"https://yoursaas.com/webhooks/retell/inbound/clinic_a_id"
)

# When Clinic B registers
await retell.phone_number.update(
    phone_number="+229-9876-5432",  # Clinic B's number
    agent_id=MASTER_AGENT_ID,
    
    # Different clinic_id in URL
    inbound_webhook_url=f"https://yoursaas.com/webhooks/retell/inbound/clinic_b_id"
)
```

**What Happens When Patient Calls:**

1. **Patient calls +229-1234-5678**
2. **Retell receives call and IMMEDIATELY calls:**
```
   POST https://yoursaas.com/webhooks/retell/inbound/clinic_a_id

Your webhook receives the clinic_id from the URL path
You return clinic data

Your Webhook Implementation:
pythonfrom fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

@app.post("/webhooks/retell/inbound/{clinic_id}")
async def handle_inbound_call(clinic_id: str, request: Request):
    """
    This runs BEFORE the conversation starts
    The clinic_id is already in the URL path!
    """
    
    # Get the call details from Retell
    call_data = await request.json()
    
    # call_data contains:
    # {
    #   "from_number": "+229-8888-9999",  # Patient's phone
    #   "to_number": "+229-1234-5678",    # Clinic's phone
    #   "call_id": "call_xxxxx",
    #   ...
    # }
    
    # Fetch clinic from YOUR database using clinic_id from URL
    clinic = await db.clinics.get(id=clinic_id)
    
    if not clinic:
        return JSONResponse(
            status_code=404,
            content={"error": "Clinic not found"}
        )
    
    # Get doctors for this clinic
    doctors = await db.doctors.filter(clinic_id=clinic_id)
    doctors_formatted = "\n".join([
        f"Dr. {doc.name} - {doc.specialty}"
        for doc in doctors
    ])
    
    # RETURN THE DYNAMIC VARIABLES
    # These are available from the FIRST node of conversation flow
    return JSONResponse(
        status_code=200,
        content={
            "agent_id": MASTER_AGENT_ID,
            
            # THESE VARIABLES ARE NOW AVAILABLE IN THE CONVERSATION!
            "retell_llm_dynamic_variables": {
                "clinic_id": clinic.id,
                "clinic_name": clinic.name,
                "clinic_address": clinic.address,
                "clinic_phone": clinic.phone_number,
                "available_doctors": doctors_formatted,
                "business_hours": clinic.business_hours,
                "language": clinic.language
            }
        }
    )

Method 2: Lookup from Phone Number (Alternative)
If you prefer, you can also identify the clinic by looking up the phone number:
Your Webhook:
python@app.post("/webhooks/retell/inbound")  # No clinic_id in URL
async def handle_inbound_call(request: Request):
    call_data = await request.json()
    
    # Get the clinic's phone number from the call
    clinic_phone = call_data["to_number"]  # +229-1234-5678
    
    # Look up clinic in YOUR database by phone number
    clinic = await db.clinics.get(phone_number=clinic_phone)
    
    if not clinic:
        return JSONResponse(
            status_code=404,
            content={"error": "Clinic not found"}
        )
    
    # Rest is the same...
    doctors = await db.doctors.filter(clinic_id=clinic.id)
    
    return JSONResponse(
        status_code=200,
        content={
            "agent_id": MASTER_AGENT_ID,
            "retell_llm_dynamic_variables": {
                "clinic_id": clinic.id,
                "clinic_name": clinic.name,
                # ... etc
            }
        }
    )
```

---

## **Timeline: From Call to First Word**
```
Time: 0.00s - Patient presses "Call" on +229-1234-5678
         ↓
Time: 0.10s - Retell receives call
         ↓
Time: 0.15s - Retell calls YOUR webhook:
              POST https://yoursaas.com/webhooks/retell/inbound/clinic_a_id
         ↓
Time: 0.35s - Your webhook:
              1. Receives clinic_id from URL
              2. Queries database for Clinic A
              3. Gets doctors list
              4. Returns dynamic variables
         ↓
Time: 0.40s - Retell receives variables:
              {
                "clinic_id": "clinic_a_id",
                "clinic_name": "Clinique Benin",
                "available_doctors": "Dr. Smith\nDr. Ahmed"
              }
         ↓
Time: 0.45s - Conversation Flow starts with variables loaded
         ↓
Time: 0.80s - First node executes:
              "Hello, you've reached {{clinic_name}}"
              Becomes: "Hello, you've reached Clinique Benin"
         ↓
Time: 0.80s - Patient hears greeting
```

**Total time: Less than 1 second!**

---

## **Your Conversation Flow (First Few Nodes)**

The conversation flow **does NOT need to call a function first** to get clinic info. It's **already there**!
```
┌─────────────────────────────────────────────┐
│ [START NODE]                                │
│ Variables already available:                │
│ - clinic_id = "clinic_a_id"                 │
│ - clinic_name = "Clinique Benin"            │
│ - available_doctors = "Dr. Smith\nDr. Ahmed"│
└────────────────┬────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────┐
│ [CONVERSATION NODE: Greeting]               │
│ Instruction:                                │
│ "Say: Hello, you've reached {{clinic_name}}.│
│  How can I help you today?"                 │
└────────────────┬────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────┐
│ [CONVERSATION NODE: Ask Need]               │
│ Instruction:                                │
│ "Listen to what the patient needs"          │
└────────────────┬────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────┐
│ [LOGIC SPLIT: What do they need?]           │
│ Edge 1: "Patient wants to book appointment" │
│ Edge 2: "Patient has a question"            │
│ Edge 3: "Emergency"                         │
└─────┬───────────────────┬──────────────┬────┘
      │                   │              │
      ▼                   ▼              ▼
   [Book Flow]      [Answer Flow]  [Transfer]

Detailed Example: Complete Call Flow
Scenario: Patient calls Clinic A
1. Patient dials +229-1234-5678
2. Retell calls your webhook:
httpPOST https://yoursaas.com/webhooks/retell/inbound/clinic_a_id
Content-Type: application/json

{
  "from_number": "+229-8888-9999",
  "to_number": "+229-1234-5678",
  "call_id": "call_abc123"
}
3. Your webhook responds:
json{
  "agent_id": "agent_master_flow_xyz",
  "retell_llm_dynamic_variables": {
    "clinic_id": "clinic_a_id",
    "clinic_name": "Clinique Benin",
    "clinic_address": "123 Rue Cotonou",
    "available_doctors": "1. Dr. Smith - Cardiology\n2. Dr. Ahmed - General"
  }
}
```

**4. Conversation starts with these variables:**

**Node 1: Greeting**
```
Agent: "Bonjour, vous avez appelé Clinique Benin. Comment puis-je vous aider?"
(Hello, you've reached Clinique Benin. How can I help you?)

Patient: "Je voudrais prendre un rendez-vous"
(I would like to make an appointment)
```

**Node 2: Present Doctors**
```
Agent: "Nous avons les médecins suivants disponibles:
1. Dr. Smith - Cardiology
2. Dr. Ahmed - General
Quel médecin préférez-vous?"
(We have the following doctors available... Which doctor do you prefer?)

Patient: "Dr. Ahmed"
```

**Node 3: Extract Doctor Choice**
```
[Extract Dynamic Variable Node]
Variable: chosen_doctor_name = "Dr. Ahmed"
```

**Node 4: Custom Function - Get Availability**
```
[Function Node: check_availability]

Parameters sent to YOUR API:
{
  "clinic_id": "clinic_a_id",  ← From webhook!
  "doctor_name": "Dr. Ahmed"   ← Just extracted
}
Your API receives:
python@app.post("/api/check-availability")
async def check_availability(request: Request):
    data = await request.json()
    args = data["args"]
    
    # clinic_id is already here!
    clinic_id = args["clinic_id"]  # "clinic_a_id"
    doctor_name = args["doctor_name"]  # "Dr. Ahmed"
    
    # Query YOUR database for Clinic A's Dr. Ahmed
    slots = await db.get_available_slots(
        clinic_id=clinic_id,
        doctor_name=doctor_name
    )
    
    return {"available_slots": ["09:00", "14:00", "16:30"]}
```

---

## **Key Insight: The Magic is in the Inbound Webhook**
```
❌ WRONG APPROACH:
[Start] → [Function: identify_clinic] → [Get clinic details] → [Greet]
          (Wastes time, adds complexity)

✅ CORRECT APPROACH:
[Webhook injects clinic data] → [Start with clinic data available] → [Greet using {{clinic_name}}]
                                 (Fast, clean, efficient)

Configuration Checklist
✅ Step 1: Create Master Agent (Once)
python# Run once when setting up your SaaS
master_agent = await retell.agent.create(
    response_engine={
        "type": "conversation-flow",
        "conversation_flow_id": your_flow_id
    },
    voice_id="french_voice",
    language="french"
)

MASTER_AGENT_ID = master_agent.agent_id
# Save this to environment: RETELL_MASTER_AGENT_ID=agent_xxx
✅ Step 2: For Each New Clinic
pythonasync def onboard_clinic(clinic_data):
    # 1. Create in your DB
    clinic = await db.clinics.create(clinic_data)
    
    # 2. Get phone number from Retell
    phone = await retell.phone_number.create(
        area_code=clinic_data["area_code"]
    )
    
    # 3. Link phone to master agent WITH webhook
    await retell.phone_number.update(
        phone_number=phone.number,
        agent_id=MASTER_AGENT_ID,  # Same for all!
        
        # Include clinic ID in webhook URL
        inbound_webhook_url=f"https://yoursaas.com/webhooks/retell/inbound/{clinic.id}"
    )
    
    # 4. Save phone to clinic
    clinic.phone_number = phone.number
    await clinic.save()
    
    return clinic
✅ Step 3: Webhook Endpoint
python@app.post("/webhooks/retell/inbound/{clinic_id}")
async def handle_inbound(clinic_id: str, request: Request):
    # Fetch clinic
    clinic = await db.clinics.get(id=clinic_id)
    
    # Fetch doctors
    doctors = await db.doctors.filter(clinic_id=clinic_id)
    
    # Return variables
    return JSONResponse(
        status_code=200,
        content={
            "agent_id": MASTER_AGENT_ID,
            "retell_llm_dynamic_variables": {
                "clinic_id": clinic.id,
                "clinic_name": clinic.name,
                "available_doctors": format_doctors(doctors)
            }
        }
    )

Summary: Direct Answer to Your Question
Q: "How does the conversation flow know the clinic?"
A: The conversation flow knows the clinic because:

✅ Phone number is unique per clinic
✅ Each phone is linked to an inbound webhook URL with clinic_id
✅ BEFORE the conversation starts, Retell calls your webhook
✅ Your webhook returns clinic data as dynamic variables
✅ Variables are available from the FIRST node

You do NOT need to:

❌ Call a function in the first node to identify clinic
❌ Ask the patient which clinic they're calling
❌ Have any "identify clinic" logic in the conversation flow

The clinic is identified AUTOMATICALLY by the phone number and injected BEFORE any conversation happens!

Does this clarify how it works? The webhook is the key piece that makes multi-tenancy work seamlessly!To run code, enable code execution and file creation in Settings > Capabilities.sumarise the action needed as a propmt to claude code6:39 PMArchitected multi-tenant SaaS implementation framework with Retell AI integration.The user wants a summary of all the actions needed to implement this multi-tenant SaaS architecture with Retell AI, formatted as a prompt for Claude Code (the coding assistant).
Let me create a clear, actionable prompt that covers:

Database schema
Master agent creation
Clinic onboarding flow
Inbound webhook implementation
Custom function endpoints
Conversation flow configuration

I'll make it concise but comprehensive, with clear file structure and code examples.Here's a comprehensive prompt for Claude Code:
markdown# Build Multi-Tenant Medical Clinic SaaS with Retell AI Integration

## Project Overview
Build a SaaS platform where clinicians register their clinics and get an AI voice receptionist powered by Retell AI. Each clinic gets a unique phone number but uses ONE master conversation flow agent customized via dynamic variables.

## Architecture Requirements

### Database Schema (PostgreSQL)
```sql
-- Create these tables:

CREATE TABLE clinics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    address TEXT,
    phone_number VARCHAR(20) UNIQUE,
    country_code VARCHAR(10),
    language VARCHAR(10) DEFAULT 'fr',
    business_hours JSONB,
    owner_email VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE doctors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clinic_id UUID REFERENCES clinics(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    specialty VARCHAR(100),
    email VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE appointments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clinic_id UUID REFERENCES clinics(id),
    doctor_id UUID REFERENCES doctors(id),
    patient_name VARCHAR(255),
    patient_phone VARCHAR(20),
    appointment_date DATE,
    appointment_time TIME,
    status VARCHAR(50) DEFAULT 'scheduled',
    created_at TIMESTAMP DEFAULT NOW()
);
```

## Implementation Tasks

### Task 1: Create Master Retell Conversation Flow Agent (One-Time Setup)
**File**: `scripts/setup_master_agent.py`

Requirements:
- Use Retell SDK to create ONE master conversation flow agent
- Save agent_id to environment variable: RETELL_MASTER_AGENT_ID
- Conversation flow should support French language
- Flow structure:
  1. Greeting node: "Bonjour, vous avez appelé {{clinic_name}}. Comment puis-je vous aider?"
  2. Ask need node: Listen to patient request
  3. Logic split: Booking vs Question vs Emergency
  4. For booking flow:
     - Present doctors: "{{available_doctors}}"
     - Extract doctor choice (name and ID)
     - Ask for date
     - Custom function: check_availability (pass clinic_id, doctor_id,To run code, enable code execution and file creation in Settings > Capabilities.no the progress is already there, just this last fucntionality about the converstinal flow and the changes needed6:40 PMSynthesized multi-tenant conversation flow implementation requirements.The user wants a focused prompt for Claude Code about just implementing the multi-tenant conversation flow functionality - not building the entire SaaS from scratch. They already have progress and just need the specific changes for making one conversation flow work for multiple clinics with dynamic variables.
Let me create a concise, actionable prompt focused on:

Setting up the inbound webhook to inject clinic data
Modifying phone number registration to include clinic_id in webhook URL
Using dynamic variables in conversation flow
Updating custom functions to use clinic_id parameter
markdown# Implement Multi-Tenant Conversation Flow for Retell AI

## Context
You have a working medical clinic SaaS. Need to make ONE Retell conversation flow work for ALL clinics by:
1. Injecting clinic-specific data via inbound webhook before conversation starts
2. Using dynamic variables throughout the conversation flow
3. Passing clinic_id to all custom functions

## Required Changes

### Change 1: Update Phone Number Registration
**File**: Wherever you register Retell phone numbers during clinic onboarding

**Current (probably):**
```python
await retell.phone_number.update(
    phone_number=clinic.phone_number,
    agent_id=some_agent_id
)
```

**New:**
```python
# Include clinic_id in the webhook URL path
await retell.phone_number.update(
    phone_number=clinic.phone_number,
    agent_id=MASTER_AGENT_ID,  # Same agent for ALL clinics
    inbound_webhook_url=f"https://yourdomain.com/api/retell/inbound/{clinic.id}"
)
```

### Change 2: Create Inbound Webhook Endpoint
**File**: `app/api/retell/inbound/[clinic_id]/route.py` (or your framework equivalent)
```python
from fastapi import Request
from fastapi.responses import JSONResponse

@app.post("/api/retell/inbound/{clinic_id}")
async def retell_inbound_webhook(clinic_id: str, request: Request):
    """
    Called by Retell BEFORE conversation starts.
    Returns clinic-specific data as dynamic variables.
    """
    
    # 1. Get clinic from database
    clinic = await db.clinics.get(id=clinic_id)
    if not clinic:
        return JSONResponse(status_code=404, content={"error": "Clinic not found"})
    
    # 2. Get doctors for this clinic
    doctors = await db.doctors.filter(clinic_id=clinic_id)
    
    # 3. Format doctors list for agent
    doctors_formatted = "\n".join([
        f"{i+1}. Dr. {doc.name} - {doc.specialty} (ID: {doc.id})"
        for i, doc in enumerate(doctors)
    ])
    
    # 4. Create doctor ID mapping for extraction
    doctor_id_map = {
        f"Dr. {doc.name}": doc.id 
        for doc in doctors
    }
    
    # 5. Return dynamic variables to Retell
    return JSONResponse(
        status_code=200,
        content={
            "agent_id": os.getenv("RETELL_MASTER_AGENT_ID"),
            "retell_llm_dynamic_variables": {
                "clinic_id": str(clinic.id),
                "clinic_name": clinic.name,
                "clinic_address": clinic.address or "",
                "clinic_phone": clinic.phone_number,
                "available_doctors": doctors_formatted,
                "doctor_id_map": json.dumps(doctor_id_map),
                "business_hours": clinic.business_hours or "9h-17h",
                "language": clinic.language or "fr"
            }
        }
    )
```

### Change 3: Update Custom Functions to Accept clinic_id
**Files**: All your custom function endpoints (check_availability, book_appointment, etc.)

**For check_doctor_availability function:**

**In Retell Conversation Flow - Function Parameters:**
```json
{
  "type": "object",
  "required": ["clinic_id", "doctor_id", "date"],
  "properties": {
    "clinic_id": {
      "type": "string",
      "description": "Clinic identifier",
      "const": "{{clinic_id}}"
    },
    "doctor_id": {
      "type": "string",
      "description": "Doctor identifier",
      "const": "{{chosen_doctor_id}}"
    },
    "date": {
      "type": "string",
      "description": "Appointment date requested by user"
    }
  }
}
```

**In Your API Endpoint:**
```python
@app.post("/api/check-doctor-availability")
async def check_doctor_availability(request: Request):
    # Verify Retell signature
    if not Retell.verify(
        json.dumps(await request.json()),
        os.getenv("RETELL_API_KEY"),
        request.headers.get("X-Retell-Signature")
    ):
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    
    data = await request.json()
    args = data["args"]
    
    # Extract parameters
    clinic_id = args["clinic_id"]  # ← Injected from webhook
    doctor_id = args["doctor_id"]  # ← Extracted during conversation
    date = args["date"]
    
    # Query YOUR database with clinic_id
    slots = await db.appointments.get_available_slots(
        clinic_id=clinic_id,
        doctor_id=doctor_id,
        date=date
    )
    
    if not slots:
        return JSONResponse(
            status_code=200,
            content={
                "message": f"Désolé, aucun créneau disponible le {date}. Voulez-vous essayer une autre date?",
                "available_slots": []
            }
        )
    
    slots_text = ", ".join([slot.time for slot in slots])
    
    return JSONResponse(
        status_code=200,
        content={
            "message": f"Créneaux disponibles: {slots_text}. Quelle heure vous convient?",
            "available_slots": [{"time": s.time, "id": s.id} for s in slots]
        }
    )
```

### Change 4: Update Conversation Flow in Retell Dashboard

**Node 1: Greeting**
- Instruction: `Say: "Bonjour, vous avez appelé {{clinic_name}}. Comment puis-je vous aider?"`

**Node 2: Present Doctors**
- Instruction: `Say: "Nous avons les médecins suivants disponibles: {{available_doctors}}. Quel médecin souhaitez-vous consulter?"`

**Node 3: Extract Doctor Choice** (Extract Dynamic Variable Node)
- Variable 1 Name: `chosen_doctor_name`
  - Type: Text
  - Description: "The name of the doctor mentioned by the user"

- Variable 2 Name: `chosen_doctor_id`
  - Type: Text
  - Description: "Extract the doctor ID using this mapping: {{doctor_id_map}}. For example, if user chose 'Dr. Smith', return the ID from the mapping."

**Node 4: Confirm Doctor**
- Instruction: `Say: "Parfait, vous avez choisi {{chosen_doctor_name}}. Pour quelle date souhaitez-vous un rendez-vous?"`

**Node 5: Extract Date**
- Variable: `appointment_date`
  - Type: Text
  - Description: "The appointment date requested by user in YYYY-MM-DD format"

**Node 6: Check Availability** (Custom Function Node)
- Function: `check_doctor_availability`
- Parameters: (see Change 3 above)

## Key Points

1. **Webhook is called BEFORE conversation starts** - clinic data is available from first node
2. **Use `const: "{{variable_name}}"` in function parameters** - passes dynamic variables to functions
3. **All custom functions receive `clinic_id`** - query correct clinic's data
4. **ONE master agent for ALL clinics** - no need to create agent per clinic

## Testing Steps

1. Create test webhook endpoint locally (use ngrok)
2. Register test clinic with phone number pointing to your webhook
3. Call the number
4. Verify webhook receives correct clinic_id
5. Verify conversation uses correct clinic name
6. Verify custom functions receive correct clinic_id

## Environment Variables Needed
```
RETELL_API_KEY=your_api_key
RETELL_MASTER_AGENT_ID=agent_xxx  # Created once, same for all clinics
```

## Files to Modify
1. Phone number registration code (add inbound_webhook_url)
2. Create new webhook endpoint: `/api/retell/inbound/{clinic_id}`
3. Update all custom function endpoints to use clinic_id parameter
4. Update conversation flow in Retell dashboard to use {{dynamic