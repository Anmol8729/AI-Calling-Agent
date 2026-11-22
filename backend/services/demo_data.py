"""
Clarivo Local Demo Data & Fixtures.

Provides rich, structured demo data matching the Stitch 'Clarivo Precision'
design system when testing without a live Supabase database.
"""

from datetime import datetime, timedelta

DEMO_USER_ID = "00000000-0000-0000-0000-000000000001"
DEMO_CLINIC_ID = "00000000-0000-0000-0000-000000000001"

DEMO_USER = {
    "id": DEMO_USER_ID,
    "email": "demo@clarivo.io",
    "name": "Dr. Sarah Patel",
    "role": "doctor",
    "clinic_id": DEMO_CLINIC_ID,
    "tenant_status": "active",
    "is_superadmin": True,
    "email_verified": True,
    "token_version": 0,
}

DEMO_CLINIC = {
    "id": DEMO_CLINIC_ID,
    "name": "Clarivo",
    "industry": "healthcare",
    "phone": "+91 98765 43210",
    "system_prompt": "You are Clarivo, a warm and professional AI voice receptionist.",
    "initial_greeting": "Hello! Thank you for calling Clarivo. How may I assist you today?",
    "status": "active",
    "subscription": "pro",
    "monthly_call_limit": 500,
    "number_limit": 2,
    "notify_email": "demo@clarivo.io",
    "whatsapp_template_lang": "en_US",
}

def get_demo_overview():
    now = datetime.utcnow()
    return {
        "total_calls": 142,
        "today": 18,
        "completed": 134,
        "missed": 8,
        "todayChangePct": 12.5,
        "avg_duration": 138,
        "resolution_rate": 94.4,
        "liveNow": 0,
        "inbound_by_day": [
            {"day": "Mon", "calls": 24, "completed": 22},
            {"day": "Tue", "calls": 28, "completed": 26},
            {"day": "Wed", "calls": 31, "completed": 29},
            {"day": "Thu", "calls": 22, "completed": 21},
            {"day": "Fri", "calls": 27, "completed": 25},
            {"day": "Sat", "calls": 14, "completed": 13},
            {"day": "Sun", "calls": 10, "completed": 9},
        ],
        "hourly_volume": [
            {"hour": "09:00", "count": 4},
            {"hour": "10:00", "count": 7},
            {"hour": "11:00", "count": 12},
            {"hour": "12:00", "count": 8},
            {"hour": "13:00", "count": 5},
            {"hour": "14:00", "count": 9},
            {"hour": "15:00", "count": 11},
            {"hour": "16:00", "count": 6},
        ],
        "recent_calls": get_demo_calls()[:5],
    }

def get_demo_onboarding():
    return {
        "progress": 75,
        "percentage": 75,
        "steps": [
            {"id": "phone", "title": "Connect phone line (SIP trunk)", "done": True, "description": "SIP trunk active and routing inbound calls"},
            {"id": "greeting", "title": "Customize greeting and voice persona", "done": True, "description": "Warm medical receptionist persona configured"},
            {"id": "whatsapp", "title": "Configure automated WhatsApp confirmation", "done": True, "description": "Instant appointment SMS/WhatsApp active"},
            {"id": "live_test", "title": "Run end-to-end test call", "done": False, "description": "Call your Clarivo number to verify reception"}
        ]
    }

def get_demo_calls():
    now = datetime.utcnow()
    return [
        {
            "id": "call-1",
            "caller_name": "Aarav Sharma",
            "caller_phone": "+91 98201 12345",
            "created_at": (now - timedelta(minutes=15)).isoformat(),
            "duration": 145,
            "status": "completed",
            "direction": "inbound",
            "reason": "Appointment Booking",
            "transcript": [
                {"role": "assistant", "content": "Hello! Thank you for calling Clarivo Clinic. How may I help you today?"},
                {"role": "user", "content": "Hi, I'd like to book an appointment with Dr. Patel for tomorrow afternoon."},
                {"role": "assistant", "content": "Certainly! I have a slot available at 2:30 PM or 4:00 PM tomorrow. Which works better for you?"},
                {"role": "user", "content": "2:30 PM is perfect, thank you."},
                {"role": "assistant", "content": "Great, I've booked your appointment for tomorrow at 2:30 PM. A confirmation message has been sent to your WhatsApp."}
            ]
        },
        {
            "id": "call-2",
            "caller_name": "Pooja Verma",
            "caller_phone": "+91 98450 67890",
            "created_at": (now - timedelta(minutes=45)).isoformat(),
            "duration": 182,
            "status": "completed",
            "direction": "inbound",
            "reason": "Consultation Inquiry",
            "transcript": [
                {"role": "assistant", "content": "Welcome to Clarivo Clinic. How can I assist you?"},
                {"role": "user", "content": "Hello, do you offer cardiology consultations on Saturdays?"},
                {"role": "assistant", "content": "Yes, our cardiology department is open on Saturdays from 9 AM to 1 PM. Would you like to schedule a slot?"},
                {"role": "user", "content": "Yes, please. I will check my schedule and call back."},
                {"role": "assistant", "content": "Sounds good! Have a wonderful day."}
            ]
        },
        {
            "id": "call-3",
            "caller_name": "Rohan Gupta",
            "caller_phone": "+91 98199 45678",
            "created_at": (now - timedelta(hours=2, minutes=10)).isoformat(),
            "duration": 95,
            "status": "completed",
            "direction": "inbound",
            "reason": "Prescription Refill",
            "transcript": [
                {"role": "assistant", "content": "Clarivo Clinic, how may I help you?"},
                {"role": "user", "content": "I need a refill on my blood pressure prescription from Dr. Patel."},
                {"role": "assistant", "content": "I have noted your refill request for Dr. Patel's review. You will receive an SMS once it is approved."},
                {"role": "user", "content": "Thank you so much!"}
            ]
        },
        {
            "id": "call-4",
            "caller_name": "Sneha Kulkarni",
            "caller_phone": "+91 97654 32109",
            "created_at": (now - timedelta(hours=3, minutes=30)).isoformat(),
            "duration": 0,
            "status": "missed",
            "direction": "inbound",
            "reason": "Missed Call",
            "transcript": []
        },
        {
            "id": "call-5",
            "caller_name": "Vikram Singh",
            "caller_phone": "+91 99887 76655",
            "created_at": (now - timedelta(hours=5)).isoformat(),
            "duration": 160,
            "status": "completed",
            "direction": "inbound",
            "reason": "Dental Cleaning",
            "transcript": [
                {"role": "assistant", "content": "Hello! Thank you for calling Clarivo Clinic."},
                {"role": "user", "content": "I would like to book a dental checkup."},
                {"role": "assistant", "content": "I have booked you for Thursday at 11:00 AM with Dr. Sarah Patel."},
                {"role": "user", "content": "Great, thanks!"}
            ]
        }
    ]

def get_demo_patients():
    return [
        {"id": "p-1", "name": "Aarav Sharma", "phone": "+91 98201 12345", "email": "aarav.sharma@gmail.com", "age": 34, "gender": "Male", "created_at": "2026-11-15T10:30:00Z", "history": ["General Checkup", "Blood Panel"], "source": "agent"},
        {"id": "p-2", "name": "Pooja Verma", "phone": "+91 98450 67890", "email": "pooja.v@outlook.com", "age": 29, "gender": "Female", "created_at": "2026-11-16T14:15:00Z", "history": ["Dental Consultation"], "source": "agent"},
        {"id": "p-3", "name": "Rohan Gupta", "phone": "+91 98199 45678", "email": "rohan.g@gmail.com", "age": 42, "gender": "Male", "created_at": "2026-11-18T11:00:00Z", "history": ["Follow-up"], "source": "agent"},
        {"id": "p-4", "name": "Sneha Kulkarni", "phone": "+91 97654 32109", "email": "sneha.k@yahoo.com", "age": 38, "gender": "Female", "created_at": "2026-11-19T16:45:00Z", "history": [], "source": "manual"},
        {"id": "p-5", "name": "Vikram Singh", "phone": "+91 99887 76655", "email": "vikram.singh@gmail.com", "age": 45, "gender": "Male", "created_at": "2026-11-20T09:15:00Z", "history": ["Dental Cleaning"], "source": "agent"},
    ]

def get_demo_appointments():
    now = datetime.utcnow()
    return [
        {"id": "a-1", "patient_name": "Aarav Sharma", "patient_phone": "+91 98201 12345", "appointment_at": (now + timedelta(days=1, hours=2)).isoformat(), "reason": "General Checkup", "status": "scheduled", "source": "agent"},
        {"id": "a-2", "patient_name": "Pooja Verma", "patient_phone": "+91 98450 67890", "appointment_at": (now + timedelta(days=1, hours=4)).isoformat(), "reason": "Dental Cleaning", "status": "scheduled", "source": "agent"},
        {"id": "a-3", "patient_name": "Vikram Singh", "patient_phone": "+91 99887 76655", "appointment_at": (now + timedelta(days=2)).isoformat(), "reason": "Dental Checkup", "status": "scheduled", "source": "agent"},
        {"id": "a-4", "patient_name": "Rohan Gupta", "patient_phone": "+91 98199 45678", "appointment_at": (now - timedelta(days=1)).isoformat(), "reason": "Follow-up", "status": "completed", "source": "agent"},
    ]

def get_demo_messages():
    now = datetime.utcnow()
    return [
        {"id": "m-1", "recipient": "+91 98201 12345", "type": "whatsapp", "status": "delivered", "message": "Your appointment with Dr. Sarah Patel is confirmed for tomorrow at 2:30 PM. Location: Clarivo Medical Suites.", "created_at": (now - timedelta(minutes=14)).isoformat()},
        {"id": "m-2", "recipient": "+91 98450 67890", "type": "whatsapp", "status": "delivered", "message": "Appointment reminder: Consultation scheduled for tomorrow at 4:00 PM.", "created_at": (now - timedelta(minutes=44)).isoformat()},
        {"id": "m-3", "recipient": "+91 99887 76655", "type": "sms", "status": "delivered", "message": "Dental appointment confirmed for Thursday 11:00 AM.", "created_at": (now - timedelta(hours=4, minutes=58)).isoformat()},
    ]

def get_demo_billing():
    now = datetime.utcnow()
    return {
        "plan": "pro",
        "plan_name": "Clarivo Pro (Scale)",
        "status": "active",
        "current_period_end": (now + timedelta(days=22)).isoformat(),
        "minutes_used": 184,
        "minutes_limit": 500,
        "rate_per_min": 1.25,
        "amount": 2999,
        "currency": "INR",
    }

def get_demo_staff():
    return [
        {"id": DEMO_USER_ID, "name": "Dr. Sarah Patel", "email": "demo@clarivo.io", "role": "doctor", "is_active": True},
        {"id": "staff-2", "name": "Neha Joshi", "email": "reception@clarivo.io", "role": "receptionist", "is_active": True},
        {"id": "staff-3", "name": "Dr. Amit Roy", "email": "amit.roy@clarivo.io", "role": "doctor", "is_active": True},
    ]

def get_demo_phone_numbers():
    return [
        {"id": "pn-1", "phone_number": "+91 11 4084 5678", "status": "active", "trunk_name": "Clarivo Primary Trunk", "created_at": "2026-11-01T00:00:00Z"},
        {"id": "pn-2", "phone_number": "+91 22 6982 1234", "status": "active", "trunk_name": "Vobiz Secondary Direct", "created_at": "2026-11-05T00:00:00Z"},
    ]
