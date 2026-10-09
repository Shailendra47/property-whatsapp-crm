import html
import logging
import os
import re
import secrets
import smtplib
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

from bson import ObjectId
from bson.errors import InvalidId
from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field, field_validator
from pymongo import AsyncMongoClient
from pymongo.errors import PyMongoError
from starlette.middleware.sessions import SessionMiddleware

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
MONGODB_URI = os.getenv("MONGODB_URI")
DB_NAME = os.getenv("DB_NAME", "property_db")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "contacts")
ENQUIRY_COLLECTION_NAME = os.getenv("ENQUIRY_COLLECTION_NAME", "property_leads")

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SENDER_NAME = os.getenv("SENDER_NAME", "Property Team")
AGENT_PHONE = os.getenv("AGENT_PHONE", "")
CALENDLY_URL = os.getenv("CALENDLY_URL", "https://calendly.com/shailendra-profilent/30min")

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
WHATSAPP_BUSINESS_NUMBER = os.getenv("WHATSAPP_BUSINESS_NUMBER", "")
IST = timezone(timedelta(hours=5, minutes=30))

logger = logging.getLogger("uvicorn.error")

SESSION_SECRET = os.getenv("SESSION_SECRET")
if not SESSION_SECRET:
    SESSION_SECRET = secrets.token_hex(32)
    logger.warning(
        "SESSION_SECRET is not set in .env - using a random one for this run. "
        "Admin logins will be forgotten every time the server restarts. "
        "Set SESSION_SECRET in .env to keep people logged in across restarts."
    )

from whatsapp_bot import router as whatsapp_router, start_questionnaire, whatsapp_configuration
import traceback


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not MONGODB_URI:
        raise RuntimeError("MONGODB_URI is missing. Add it to your .env file.")
    client = AsyncMongoClient(MONGODB_URI, tz_aware=True)
    app.state.client = client
    app.state.contacts = client[DB_NAME][COLLECTION_NAME]
    app.state.enquiries = client[DB_NAME][ENQUIRY_COLLECTION_NAME]
    app.state.whatsapp_conversations = client[DB_NAME]["whatsapp_conversations"]
    yield
    await client.close()


app = FastAPI(title="Property Contact Form", lifespan=lifespan)
app.include_router(whatsapp_router)
# app.add_middleware(
#     SessionMiddleware,
#     secret_key=SESSION_SECRET,
#     session_cookie="admin_session",
#     max_age=60 * 60 * 8,  # 8 hours
#     same_site="lax",
# )
@app.middleware("http")
async def debug_requests(request: Request, call_next):
    print("REQUEST RECEIVED:", request.method, request.url)
    
    response = await call_next(request)
    
    print("RESPONSE STATUS:", response.status_code)
    return response


class ContactForm(BaseModel):
    full_name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    contact_number: str
    requirement: str = Field(default="", max_length=1000)
    whatsapp_opt_in: bool = False

    @field_validator("full_name")
    @classmethod
    def strip_text(cls, v: str) -> str:
        return v.strip()

    @field_validator("contact_number")
    @classmethod
    def valid_phone(cls, v: str) -> str:
        v = v.strip()
        if not re.fullmatch(r"\+?[0-9\s\-]{7,17}", v):
            raise ValueError("Enter a valid contact number")
        return v


def send_confirmation_email(name: str, to_email: str, property_address: str) -> None:
    """Send the buyer-inquiry reply. Runs in the background; failures are logged, not raised."""
    if not (SMTP_USER and SMTP_PASSWORD):
        logger.warning("SMTP_USER / SMTP_PASSWORD not set - confirmation email skipped.")
        return

    text_parts = [
        f"Dear {name},",
        f"Thank you for your interest in {property_address}. I would be happy to provide "
        "more details or schedule a private viewing at your convenience.",
    ]
    html_parts = [
        f"<p>Dear {html.escape(name)},</p>",
        f"<p>Thank you for your interest in <strong>{html.escape(property_address)}</strong>. "
        "I would be happy to provide more details or schedule a private viewing at your "
        "convenience.</p>",
    ]

    if CALENDLY_URL:
        text_parts.append(f"Book a meeting at a time that suits you:\n{CALENDLY_URL}")
        html_parts.append(
            "<p>Book a meeting at a time that suits you:</p>"
            f'<p><a href="{html.escape(CALENDLY_URL, quote=True)}" '
            'style="display:inline-block;background:#333333;color:#ffffff;padding:12px 24px;'
            'border-radius:6px;text-decoration:none;font-weight:600;">Schedule a Meeting</a></p>'
        )

    if AGENT_PHONE:
        tel = re.sub(r"[^\d+]", "", AGENT_PHONE)
        text_parts.append(f"Prefer to talk? Call our salesperson directly at {AGENT_PHONE}.")
        html_parts.append(
            "<p>Prefer to talk? Call our salesperson directly at "
            f'<a href="tel:{tel}"><strong>{html.escape(AGENT_PHONE)}</strong></a>.</p>'
        )

    text_parts.append(f"Warm regards,\n{SENDER_NAME}")
    html_parts.append(f"<p>Warm regards,<br>{html.escape(SENDER_NAME)}</p>")

    body = "\n\n".join(text_parts)
    body_html = "".join(html_parts)

    msg = EmailMessage()
    msg["Subject"] = "Thank you for your property enquiry"
    msg["From"] = f"{SENDER_NAME} <{SMTP_USER}>"
    msg["To"] = to_email
    msg.set_content(body)
    msg.add_alternative(body_html, subtype="html")

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
    except Exception:
        logger.exception("Could not send confirmation email to %s", to_email)


@app.post("/api/contact", status_code=201)
async def create_contact(form: ContactForm, background_tasks: BackgroundTasks):
    doc = form.model_dump()
    if not doc.get("requirement"):
        doc.pop("requirement", None)
    whatsapp_phone = re.sub(r"[\s()-]", "", form.contact_number)
    if not re.fullmatch(r"\+[1-9][0-9]{7,14}", whatsapp_phone):
        raise HTTPException(
            status_code=422,
            detail="Enter the WhatsApp number in international format, e.g. +919876543210.",
        )
    doc["contact_number"] = whatsapp_phone
    doc["created_at"] = datetime.now(timezone.utc)
    if form.whatsapp_opt_in:
        doc["whatsapp_opt_in_source"] = "contact_us_checkbox"
        doc["whatsapp_opt_in_at"] = datetime.now(timezone.utc)
    try:
        result = await app.state.contacts.insert_one(doc)
    except PyMongoError:
        raise HTTPException(status_code=500, detail="Could not save your details. Please try again.")
    background_tasks.add_task(send_confirmation_email, form.full_name, form.email, "our properties")
    whatsapp_result = (
        await start_questionnaire(
            app.state.whatsapp_conversations,
            phone=whatsapp_phone,
            contact_id=str(result.inserted_id),
            background_tasks=background_tasks,
            full_name=form.full_name,
            email=str(form.email),
        )
        if form.whatsapp_opt_in
        else {"started": False, "status": "not_requested"}
    )
    return {
        "message": "Thank you! We will contact you shortly.",
        "whatsapp_started": whatsapp_result["started"],
        "whatsapp_status": whatsapp_result["status"],
        "whatsapp_missing_settings": whatsapp_result.get("missing", []),
        "id": str(result.inserted_id),
    }


CHOICES = {
    "planning_to_buy": [
        "Immediately", "Within 1 Month", "Within 3 Months", "Within 6 Months",
        "Within 12 Months", "More Than 1 Year", "Just Exploring / Researching",
    ],
    "budget_range": [
        "Up to 25 lakh", "25 lakh - 50 lakh", "50 lakh - 1 crore",
        "1 crore - 2 crore", "Above 2 crore",
    ],
    "payment_option": [
        "Bank Finance with EMI", "Full Cash Payment", "Home Loan (Mortgage)",
        "Down Payment Plan", "Construction-Linked Payment Plan (CLP)",
        "Possession-Linked Payment Plan (PLP)", "Installment Payment Plan",
        "Developer Financing", "Rent-to-Own Scheme", "Part Cash + Home Loan",
        "Part Payment with Balance at Registration", "Flexible Payment Plan",
        "Subvention Scheme (Developer Pays Pre-EMI)",
        "Joint Home Loan (Co-applicant Financing)",
        "NRI Payment Plan (for Overseas Buyers)",
    ],
    "bhk_preference": [
        "1 RK", "1 BHK", "2 BHK", "2.5 BHK", "3 BHK", "3.5 BHK",
        "4 BHK", "5 BHK+", "Villa", "Penthouse",
    ],
}


class EnquiryForm(BaseModel):
    first_name: str = Field(min_length=2, max_length=50)
    last_name: str = Field(default="", max_length=50)
    email: EmailStr
    mobile_number: str
    location_preference: str = Field(min_length=2, max_length=150)
    planning_to_buy: str
    budget_range: str
    payment_option: str
    bhk_preference: str
    remarks: str = Field(default="", max_length=1000)

    @field_validator("first_name", "last_name", "location_preference", "remarks")
    @classmethod
    def strip_text(cls, v: str) -> str:
        return v.strip()

    @field_validator("mobile_number")
    @classmethod
    def valid_mobile(cls, v: str) -> str:
        cleaned = re.sub(r"[\s-]", "", v)
        if not re.fullmatch(r"\+?[0-9]{10,15}", cleaned):
            raise ValueError("Enter a valid mobile number")
        return cleaned

    @field_validator("planning_to_buy", "budget_range", "payment_option", "bhk_preference")
    @classmethod
    def valid_choice(cls, v: str, info) -> str:
        if v not in CHOICES[info.field_name]:
            raise ValueError("Select a valid option")
        return v


@app.post("/api/enquiry", status_code=201)
async def create_enquiry(form: EnquiryForm, background_tasks: BackgroundTasks):
    doc = form.model_dump()
    doc["created_at"] = datetime.now(timezone.utc)
    try:
        result = await app.state.enquiries.insert_one(doc)
    except PyMongoError:
        raise HTTPException(status_code=500, detail="Could not save your enquiry. Please try again.")
    full_name = f"{form.first_name} {form.last_name}".strip()
    background_tasks.add_task(
        send_confirmation_email, full_name, form.email, f"properties in {form.location_preference}"
    )
    return {"message": "Thank you! Your enquiry has been submitted. We will contact you shortly.", "id": str(result.inserted_id)}


# ---------------------------------------------------------------- Admin auth
class AdminLogin(BaseModel):
    username: str
    password: str


def require_admin(request: Request) -> None:
    if not ADMIN_PASSWORD:
        raise HTTPException(status_code=503, detail="Set ADMIN_PASSWORD in your .env file to use the admin panel.")
    if not request.session.get("admin"):
        raise HTTPException(status_code=401, detail="Not logged in")


@app.get("/admin/login", include_in_schema=False)
async def admin_login_page():
    return FileResponse(BASE_DIR / "admin" / "login.html")


@app.post("/admin/login")
async def admin_login(data: AdminLogin, request: Request):
    if not ADMIN_PASSWORD:
        raise HTTPException(status_code=503, detail="Set ADMIN_PASSWORD in your .env file to use the admin panel.")
    user_ok = secrets.compare_digest(data.username.strip().encode(), ADMIN_USERNAME.encode())
    pass_ok = secrets.compare_digest(data.password.encode(), ADMIN_PASSWORD.encode())
    if not (user_ok and pass_ok):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    request.session["admin"] = True
    return {"message": "ok"}


@app.post("/admin/logout")
async def admin_logout(request: Request):
    request.session.clear()
    return {"message": "ok"}


@app.get("/admin", include_in_schema=False)
async def admin_page(request: Request):
    if not request.session.get("admin"):
        return RedirectResponse("/admin/login")
    return FileResponse(BASE_DIR / "admin" / "admin.html")


# ------------------------------------------------------------- Admin: leads
def oid(lead_id: str) -> ObjectId:
    try:
        return ObjectId(lead_id)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail="Invalid lead id")


async def latest_docs(collection, limit: int = 500):
    docs = await collection.find().sort("created_at", -1).limit(limit).to_list()
    for d in docs:
        d["id"] = str(d.pop("_id"))
        d["created_at"] = d["created_at"].isoformat()
    return docs


@app.get("/api/admin/summary", dependencies=[Depends(require_admin)])
async def admin_summary():
    start = datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0)
    today = {"created_at": {"$gte": start}}
    contacts, enquiries = app.state.contacts, app.state.enquiries
    contacts_total = await contacts.count_documents({})
    enquiries_total = await enquiries.count_documents({})
    cursor = await enquiries.aggregate(
        [{"$group": {"_id": "$bhk_preference", "count": {"$sum": 1}}}, {"$sort": {"count": -1}}]
    )
    bhk = {d["_id"]: d["count"] for d in await cursor.to_list()}
    return {
        "total": contacts_total + enquiries_total,
        "cards": {
            "new_today": await contacts.count_documents(today) + await enquiries.count_documents(today),
            "contacts_total": contacts_total,
            "enquiries_total": enquiries_total,
            "immediate": await enquiries.count_documents({"planning_to_buy": {"$in": ["Immediately", "Within 1 Month"]}}),
            "cash": await enquiries.count_documents({"payment_option": "Full Cash Payment"}),
            "high_budget": await enquiries.count_documents({"budget_range": {"$in": ["1 crore - 2 crore", "Above 2 crore"]}}),
        },
        "bhk": bhk,
        "whatsapp": whatsapp_configuration(),
    }


# Contact Us leads - full CRUD
@app.get("/api/admin/contacts", dependencies=[Depends(require_admin)])
async def admin_list_contacts():
    return await latest_docs(app.state.contacts)


@app.post("/api/admin/contacts", status_code=201, dependencies=[Depends(require_admin)])
async def admin_create_contact(form: ContactForm):
    doc = form.model_dump()
    doc["created_at"] = datetime.now(timezone.utc)
    result = await app.state.contacts.insert_one(doc)
    return {"id": str(result.inserted_id)}


@app.put("/api/admin/contacts/{lead_id}", dependencies=[Depends(require_admin)])
async def admin_update_contact(lead_id: str, form: ContactForm):
    result = await app.state.contacts.update_one({"_id": oid(lead_id)}, {"$set": form.model_dump()})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Lead not found")
    return {"message": "Lead updated"}


@app.delete("/api/admin/contacts/{lead_id}", dependencies=[Depends(require_admin)])
async def admin_delete_contact(lead_id: str):
    result = await app.state.contacts.delete_one({"_id": oid(lead_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Lead not found")
    return {"message": "Lead deleted"}


# Property Enquiries - full CRUD
@app.get("/api/admin/enquiries", dependencies=[Depends(require_admin)])
async def admin_list_enquiries():
    return await latest_docs(app.state.enquiries)


@app.post("/api/admin/enquiries", status_code=201, dependencies=[Depends(require_admin)])
async def admin_create_enquiry(form: EnquiryForm):
    doc = form.model_dump()
    doc["created_at"] = datetime.now(timezone.utc)
    result = await app.state.enquiries.insert_one(doc)
    return {"id": str(result.inserted_id)}


@app.put("/api/admin/enquiries/{lead_id}", dependencies=[Depends(require_admin)])
async def admin_update_enquiry(lead_id: str, form: EnquiryForm):
    result = await app.state.enquiries.update_one({"_id": oid(lead_id)}, {"$set": form.model_dump()})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Lead not found")
    return {"message": "Lead updated"}


@app.delete("/api/admin/enquiries/{lead_id}", dependencies=[Depends(require_admin)])
async def admin_delete_enquiry(lead_id: str):
    result = await app.state.enquiries.delete_one({"_id": oid(lead_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Lead not found")
    return {"message": "Lead deleted"}


app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/", include_in_schema=False)
async def home():
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/enquiry", include_in_schema=False)
async def enquiry_page():
    return FileResponse(BASE_DIR / "static" / "enquiry.html")


@app.get("/whatsapp", include_in_schema=False)
async def start_whatsapp_chat():
    # The user sends the first message themselves, so the bot can reply without
    # an outbound template. Set WHATSAPP_BUSINESS_NUMBER in international format.
    number = re.sub(r"\D", "", WHATSAPP_BUSINESS_NUMBER)
    if not number:
        raise HTTPException(status_code=503, detail="WhatsApp chat is not configured")
    return RedirectResponse(
        f"https://wa.me/{number}?text=Hi",
        status_code=307,
    )

@app.post("/webhooks/whatsapp")
async def whatsapp_webhook(request: Request, background_tasks: BackgroundTasks):
    print("here")
    
    form = await request.form()
    params = dict(form)
    if not TWILIO_AUTH_TOKEN or not PUBLIC_BASE_URL:
        raise HTTPException(status_code=503, detail="Twilio webhook is not configured")
    signature = request.headers.get("X-Twilio-Signature", "")
    webhook_url = f"{PUBLIC_BASE_URL}/webhooks/whatsapp"
    try:
        print("========== WHATSAPP WEBHOOK ==========")
        print("URL:", webhook_url)
        print("PARAMS:", params)
        print("SIGNATURE:", repr(signature))
        print("AUTH TOKEN EXISTS:", bool(TWILIO_AUTH_TOKEN))

        valid = RequestValidator(TWILIO_AUTH_TOKEN).validate(
            webhook_url,
            params,
            signature,
        )

        print("SIGNATURE VALID:", valid)

        if not valid:
            raise RuntimeError("Twilio signature validation failed")

    except Exception:
        print("========== EXCEPTION ==========")
        traceback.print_exc()
        raise

    sender = str(form.get("From", ""))

    # ...rest of your existing code
    # if not RequestValidator(TWILIO_AUTH_TOKEN).validate(webhook_url, params, signature):
    #     raise HTTPException(status_code=403, detail="Invalid Twilio signature")
    try:
        if not RequestValidator(TWILIO_AUTH_TOKEN).validate(
            webhook_url, params, signature
        ):
            raise ValueError("Twilio signature validation failed")

    except Exception:
        traceback.print_exc()
        raise

    sender = str(form.get("From", ""))
    if not sender.startswith("whatsapp:"):
        raise HTTPException(status_code=400, detail="Expected a WhatsApp message")
    phone = sender.removeprefix("whatsapp:")
    text = str(form.get("Body", "")).strip()
    conversations = request.app.state.whatsapp_conversations
    conversation = await conversations.find_one({"phone": phone})
    if not conversation:
        # This also lets the existing wa.me link start a customer-initiated chat.
        await conversations.insert_one({
            "phone": phone,
            "stage": "q1_first_name",
            "answers": {},
            "status": "in_progress",
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        })
        return twiml(TEXT_PROMPTS["q1_first_name"])

    if text.upper() == "STOP":
        await conversations.update_one(
            {"phone": phone},
            {"$set": {"status": "stopped", "updated_at": datetime.now(timezone.utc)}},
        )
        return twiml("You have been opted out of this WhatsApp conversation.")
    if conversation.get("status") == "stopped":
        return twiml()
    if conversation.get("status") == "complete":
        return twiml("Your answers have already been recorded. Our team will contact you shortly.")

    stage = conversation.get("stage", "q1_first_name")
    answers = conversation.get("answers", {})
    answer = text

    list_stage = find_list_stage(stage)
    if list_stage:
        selected = list_choice(list_stage, form)
        if selected is None:
            return twiml(menu_fallback(list_stage))
        _, stored_value = selected
        if stage == "q8_category":
            category_stages = {
                "Loan / Bank Finance": "q8_loan",
                "Cash / Down Payment": "q8_cash",
                "Developer Plans": "q8_developer",
            }
            if stored_value == "NRI Payment Plan (for Overseas Buyers)":
                answers["payment_option"] = stored_value
                next_stage = "q9_bhk"
            else:
                next_stage = category_stages[stored_value]
        elif stage == "q6_planning":
            answers["planning_to_buy"] = stored_value
            next_stage = "q7_budget"
        elif stage == "q7_budget":
            answers["budget_range"] = stored_value
            next_stage = "q8_category"
        elif stage == "q9_bhk":
            answers["bhk_preference"] = stored_value
            next_stage = "q10_remarks"
        else:
            answers["payment_option"] = stored_value
            next_stage = next_after_preferences(stage)
        await conversations.update_one(
            {"phone": phone},
            {"$set": {"answers": answers, "stage": next_stage, "updated_at": datetime.now(timezone.utc)}},
        )
        return twiml(dispatch_stage(next_stage, phone, answers, background_tasks))

    if stage == "q1_first_name":
        candidate = text.strip()
        if len(candidate) < 2 or not candidate.isalpha():
            return twiml("Please enter your first name using letters only (at least 2 letters).\n\n" + TEXT_PROMPTS[stage])
        answers["first_name"] = candidate
        next_stage = "q2_last_name"
    elif stage == "q2_last_name":
        answers["last_name"] = "" if text.casefold() == "skip" else text[:100]
        next_stage = "q3_email"
    elif stage == "q3_email":
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", text):
            return twiml(TEXT_PROMPTS["q3_email_invalid"])
        answers["email"] = text
        next_stage = "q4_mobile"
    elif stage == "q4_mobile":
        button_payload = str(form.get("ButtonPayload", "")).strip()
        button_text = str(form.get("ButtonText", "")).strip()
        response = (button_payload or button_text or text).casefold()
        if response in {"mobile_same", "yes, same number", "yes", "same number"}:
            answers["mobile_number"] = phone
            next_stage = "q5_location"
        elif response in {"mobile_other", "use another number"}:
            next_stage = "q4_mobile_other"
        else:
            digits = re.sub(r"\D", "", text)
            if len(digits) == 10:
                answers["mobile_number"] = digits
                next_stage = "q5_location"
            else:
                fallback = f"Is *{phone}* the best number to reach you? Reply *Yes*, or type another 10-digit number."
                return twiml(fallback)
    elif stage == "q4_mobile_other":
        digits = re.sub(r"\D", "", text)
        if len(digits) != 10:
            return twiml(TEXT_PROMPTS[stage])
        answers["mobile_number"] = digits
        next_stage = "q5_location"
    elif stage == "q5_location":
        if len(text) < 2:
            return twiml("Please enter a city or area name.\n\n" + TEXT_PROMPTS[stage])
        answers["location_preference"] = text[:150]
        next_stage = "q6_planning"
    elif stage == "q10_remarks":
        answers["remarks"] = "" if text.casefold() == "skip" else text[:1000]
        conversation_id = str(conversation["_id"])
        lead = {
            "first_name": answers.get("first_name", ""),
            "last_name": answers.get("last_name", ""),
            "email": answers.get("email", ""),
            "mobile_number": answers.get("mobile_number", phone),
            "location_preference": answers.get("location_preference", ""),
            "planning_to_buy": answers.get("planning_to_buy", ""),
            "budget_range": answers.get("budget_range", ""),
            "payment_option": answers.get("payment_option", ""),
            "bhk_preference": answers.get("bhk_preference", ""),
            "remarks": answers.get("remarks", ""),
            "whatsapp_number": phone,
            "whatsapp_conversation_id": conversation_id,
            "source": "contact_us_whatsapp",
            "created_at": conversation.get("created_at", datetime.now(timezone.utc)),
            "completed_at": datetime.now(timezone.utc),
        }
        try:
            lead_result = await request.app.state.enquiries.update_one(
                {"whatsapp_conversation_id": conversation_id},
                {"$set": lead},
                upsert=True,
            )
        except Exception:
            logger.exception("Could not save WhatsApp questionnaire to property_leads")
            return twiml("Sorry, I couldn't save your answers just now. Please send your remarks again.")

        contact_id = conversation.get("contact_id")
        if contact_id:
            try:
                await request.app.state.contacts.update_one(
                    {"_id": ObjectId(contact_id)},
                    {"$set": {"whatsapp_answers": answers, "whatsapp_flow_status": "complete"}},
                )
            except Exception:
                logger.exception("Could not attach WhatsApp answers to contact %s", contact_id)
        await conversations.update_one(
            {"phone": phone},
            {"$set": {
                "answers": answers,
                "status": "complete",
                "stage": "complete",
                "property_lead_id": str(lead_result.upserted_id) if lead_result.upserted_id else None,
                "updated_at": datetime.now(timezone.utc),
            }},
        )
        first_name = answers.get("first_name", "there")
        return twiml(f"✅ Thank you, {first_name}! Our team will contact you shortly with matching options.")
    else:
        return twiml("Sorry, I couldn't match that answer. Please reply START to restart.")

    await conversations.update_one(
        {"phone": phone},
        {"$set": {"answers": answers, "stage": next_stage, "status": "in_progress", "updated_at": datetime.now(timezone.utc)}},
    )
    return twiml(dispatch_stage(next_stage, phone, answers, background_tasks))
