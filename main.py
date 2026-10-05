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
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="admin_session",
    max_age=60 * 60 * 8,  # 8 hours
    same_site="lax",
)


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
