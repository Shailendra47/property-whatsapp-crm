"""Twilio WhatsApp questionnaire for Contact Us submissions."""



import json

import logging

import os

import re

from datetime import datetime, timezone



from bson import ObjectId

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from fastapi.responses import Response

from starlette.concurrency import run_in_threadpool

from twilio.request_validator import RequestValidator

from twilio.rest import Client

from twilio.twiml.messaging_response import MessagingResponse



logger = logging.getLogger("uvicorn.error")

router = APIRouter()



TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")

TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")

TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM", "")

PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")

START_TEMPLATE_SID = os.getenv("TWILIO_WHATSAPP_START_TEMPLATE_SID", "")

START_TEMPLATE_VARIABLES = os.getenv("TWILIO_WHATSAPP_START_TEMPLATE_VARIABLES", "").strip()





def start_template_variables() -> dict | None:

    """Load optional WhatsApp template variables without storing them in code."""

    if not START_TEMPLATE_VARIABLES:

        return None

    try:

        variables = json.loads(START_TEMPLATE_VARIABLES)

    except json.JSONDecodeError:

        logger.error("TWILIO_WHATSAPP_START_TEMPLATE_VARIABLES must be valid JSON.")

        return None

    if not isinstance(variables, dict):

        logger.error("TWILIO_WHATSAPP_START_TEMPLATE_VARIABLES must be a JSON object.")

        return None

    return {str(key): str(value) for key, value in variables.items()}





def whatsapp_configuration() -> dict:

    public_origin = PUBLIC_BASE_URL.casefold()

    public_https_ready = (

        public_origin.startswith("https\://")

        and "localhost" not in public_origin

        and "127.0.0.1" not in public_origin

    )

    settings = (

        ("TWILIO_ACCOUNT_SID", bool(re.fullmatch(r"AC[0-9a-fA-F]{32}", TWILIO_ACCOUNT_SID or ""))),

        ("TWILIO_AUTH_TOKEN", bool(TWILIO_AUTH_TOKEN and "replace_with" not in TWILIO_AUTH_TOKEN.casefold() and "<" not in TWILIO_AUTH_TOKEN)),

        ("TWILIO_WHATSAPP_FROM", bool(re.fullmatch(r"\\+[1-9][0-9]{7,14}", TWILIO_WHATSAPP_FROM or ""))),

        ("TWILIO_WHATSAPP_START_TEMPLATE_SID", bool(re.fullmatch(r"HX[0-9a-fA-F]{32}", START_TEMPLATE_SID or ""))),

    )

    missing = [name for name, configured in settings if not configured]

    return {

        "outbound_configured": not missing,

        "inbound_webhook_configured": bool(TWILIO_AUTH_TOKEN and public_https_ready),

        "missing_outbound_settings": missing,

        "inbound_webhook_url": f"{PUBLIC_BASE_URL}/webhooks/whatsapp" if PUBLIC_BASE_URL else "",

    }



LISTS = {

    "q6_planning": {

        "sid": os.getenv("TWILIO_LIST_PLANNING_SID", ""),

        "question": "When are you planning to buy?",

        "rows": [

            ("planning_immediately", "Immediately", "Immediately"),

            ("planning_1_month", "Within 1 Month", "Within 1 Month"),

            ("planning_3_months", "Within 3 Months", "Within 3 Months"),

            ("planning_6_months", "Within 6 Months", "Within 6 Months"),

            ("planning_12_months", "Within 12 Months", "Within 12 Months"),

            ("planning_over_1_year", "More Than 1 Year", "More Than 1 Year"),

            ("planning_exploring", "Just Exploring", "Just Exploring / Researching"),

        ],

    },

    "q7_budget": {

        "sid": os.getenv("TWILIO_LIST_BUDGET_SID", ""),

        "question": "What's your budget range?",

        "rows": [

            ("budget_25_lakh", "Up to 25 Lakh", "Up to 25 lakh"),

            ("budget_25_50_lakh", "25 - 50 Lakh", "25 lakh - 50 lakh"),

            ("budget_50_lakh_1_crore", "50 Lakh - 1 Crore", "50 lakh - 1 crore"),

            ("budget_1_2_crore", "1 - 2 Crore", "1 crore - 2 crore"),

            ("budget_over_2_crore", "Above 2 Crore", "Above 2 crore"),

        ],

    },

    "q8_category": {

        "sid": os.getenv("TWILIO_LIST_PAYMENT_CATEGORY_SID", ""),

        "question": "How would you like to pay? Choose a category:",

        "rows": [

            ("pay_loan", "Loan / Bank Finance", "Loan / Bank Finance"),

            ("pay_cash", "Cash / Down Payment", "Cash / Down Payment"),

            ("pay_developer", "Developer Plans", "Developer Plans"),

            ("pay_nri", "NRI Payment Plan", "NRI Payment Plan (for Overseas Buyers)"),

        ],

    },

    "q8_loan": {

        "sid": os.getenv("TWILIO_LIST_PAYMENT_LOAN_SID", ""),

        "question": "Choose your loan or bank-finance option:",

        "rows": [

            ("loan_bank_emi", "Bank Finance (EMI)", "Bank Finance with EMI"),

            ("loan_mortgage", "Home Loan (Mortgage)", "Home Loan (Mortgage)"),

            ("loan_part_cash", "Part Cash + Home Loan", "Part Cash + Home Loan"),

            ("loan_joint", "Joint Home Loan", "Joint Home Loan (Co-applicant Financing)"),

        ],

    },

    "q8_cash": {

        "sid": os.getenv("TWILIO_LIST_PAYMENT_CASH_SID", ""),

        "question": "Choose your cash or down-payment option:",

        "rows": [

            ("cash_full", "Full Cash Payment", "Full Cash Payment"),

            ("cash_down_payment", "Down Payment Plan", "Down Payment Plan"),

            ("cash_balance_registration", "Balance at Registration", "Part Payment with Balance at Registration"),

        ],

    },

    "q8_developer": {

        "sid": os.getenv("TWILIO_LIST_PAYMENT_DEVELOPER_SID", ""),

        "question": "Choose your developer payment plan:",

        "rows": [

            ("dev_clp", "Construction-Linked", "Construction-Linked Payment Plan (CLP)"),

            ("dev_plp", "Possession-Linked", "Possession-Linked Payment Plan (PLP)"),

            ("dev_installment", "Installment Plan", "Installment Payment Plan"),

            ("dev_financing", "Developer Financing", "Developer Financing"),

            ("dev_rent_to_own", "Rent-to-Own", "Rent-to-Own Scheme"),

            ("dev_subvention", "Subvention (Pre-EMI)", "Subvention Scheme (Developer Pays Pre-EMI)"),

            ("dev_flexible", "Flexible Payment Plan", "Flexible Payment Plan"),

        ],

    },

    "q9_bhk": {

        "sid": os.getenv("TWILIO_LIST_BHK_SID", ""),

        "question": "What type of home are you looking for?",

        "rows": [

            ("bhk_1_rk", "1 RK", "1 RK"),

            ("bhk_1", "1 BHK", "1 BHK"),

            ("bhk_2", "2 BHK", "2 BHK"),

            ("bhk_2_5", "2.5 BHK", "2.5 BHK"),

            ("bhk_3", "3 BHK", "3 BHK"),

            ("bhk_3_5", "3.5 BHK", "3.5 BHK"),

            ("bhk_4", "4 BHK", "4 BHK"),

            ("bhk_5_plus", "5 BHK+", "5 BHK+"),

            ("bhk_villa", "Villa", "Villa"),

            ("bhk_penthouse", "Penthouse", "Penthouse"),

        ],

    },

}



QUICK_REPLY_MOBILE_SID = os.getenv("TWILIO_QUICK_REPLY_MOBILE_SID", "")



TEXT_PROMPTS = {

    "q1_first_name": "Hi! 👋 Let's find your perfect property. What's your *first name*?",

    "q2_last_name": "Thanks, {first_name}! And your *last name*? (Type *skip* to continue)",

    "q3_email": "Please share your *email address*.",

    "q3_email_invalid": "That doesn't look right. Please enter a valid email, e.g. name@example.com",

    "q4_mobile_other": "Please type another 10-digit number.",

    "q5_location": "Which *city or area* are you looking to buy in?",

    "q10_remarks": "Any *special requirements*? For example floor, facing, parking, or amenities. (Type *skip* if none)",

}



STAGE_PROMPT = {

    "q1_first_name": "q1_first_name",

    "q2_last_name": "q2_last_name",

    "q3_email": "q3_email",

    "q4_mobile": "q4_mobile",

    "q4_mobile_other": "q4_mobile_other",

    "q5_location": "q5_location",

    "q6_planning": "q6_planning",

    "q7_budget": "q7_budget",

    "q8_category": "q8_category",

    "q8_loan": "q8_loan",

    "q8_cash": "q8_cash",

    "q8_developer": "q8_developer",

    "q9_bhk": "q9_bhk",

    "q10_remarks": "q10_remarks",

}





def twiml(message: str = "") -> Response:

    response = MessagingResponse()

    if message:

        response.message(message)

    return Response(str(response), media_type="application/xml")





def send_content(to_phone: str, content_sid: str, variables: dict | None = None) -> str | None:

    if not all((TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM, content_sid)):

        logger.error("WhatsApp message skipped: Twilio credentials, sender, or Content SID is missing.")

        return

    try:

        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

        kwargs = {

            "from_": f"whatsapp:{TWILIO_WHATSAPP_FROM}",

            "to": f"whatsapp:{to_phone}",

            "content_sid": content_sid,

        }

        if variables:

            kwargs["content_variables"] = json.dumps(variables)

        message = client.messages.create(**kwargs)

        return message.sid

    except Exception:

        logger.exception("Could not send WhatsApp message to %s", to_phone)

        return None





async def start_questionnaire(

    conversations,

    phone: str,

    contact_id: str,

    background_tasks: BackgroundTasks,

    *,

    full_name: str = "",

    email: str = "",

):

    name_parts = full_name.strip().split(maxsplit=1)

    answers = {

        "first_name": name_parts[0] if name_parts else "",

        "last_name": name_parts[1] if len(name_parts) > 1 else "",

        "email": email,

        "mobile_number": phone,

    }

    await conversations.update_one(

        {"phone": phone},

        {"$set": {

            "phone": phone,

            "contact_id": contact_id,

            # The contact form already collected name, email, and mobile.

            # Start the WhatsApp questionnaire at the first missing answer.

            "stage": "q5_location",

            "answers": answers,

            "status": "awaiting_location",

            "updated_at": datetime.now(timezone.utc),

        }},

        upsert=True,

    )

    if not whatsapp_configuration()["outbound_configured"]:

        missing = whatsapp_configuration()["missing_outbound_settings"]

        logger.error("WhatsApp start message skipped: configure %s in .env.", ", ".join(missing))

        await conversations.update_one(

            {"phone": phone},

            {"$set": {"status": "template_not_configured", "updated_at": datetime.now(timezone.utc)}},

        )

        return {"started": False, "status": "configuration_missing", "missing": missing}

    message_sid = await run_in_threadpool(

        send_content,

        phone,

        START_TEMPLATE_SID,

        start_template_variables(),

    )

    if not message_sid:

        await conversations.update_one(

            {"phone": phone},

            {"$set": {"status": "start_send_failed", "updated_at": datetime.now(timezone.utc)}},

        )

        return {"started": False, "status": "twilio_rejected"}

    await conversations.update_one(

        {"phone": phone},

        {"$set": {"status": "awaiting_location", "start_message_sid": message_sid, "updated_at": datetime.now(timezone.utc)}},

    )

    return {"started": True, "status": "accepted"}





def menu_fallback(stage: str) -> str:

    menu = LISTS[stage]

    rows = menu["rows"]

    choices = "\n".join(f"{i}. {title}" for i, (_, title, _) in enumerate(rows, 1))

    return f"{menu['question']}\n{choices}\n\nReply with the option number."





def dispatch_stage(stage: str, phone: str, answers: dict, background_tasks: BackgroundTasks) -> str:

    if stage in LISTS:

        content_sid = LISTS[stage]["sid"]

        if content_sid:

            background_tasks.add_task(send_content, phone, content_sid)

            return ""

        return menu_fallback(stage)

    if stage == "q4_mobile":

        if QUICK_REPLY_MOBILE_SID:

            background_tasks.add_task(

                send_content,

                phone,

                QUICK_REPLY_MOBILE_SID,

                {"1": phone},

            )

            return ""

        return f"Is *{phone}* the best number to reach you? Reply *Yes*, or type another 10-digit number."

    prompt_key = STAGE_PROMPT.get(stage)

    if not prompt_key:

        return ""

    if stage == "q2_last_name":

        return TEXT_PROMPTS[prompt_key].format(first_name=answers.get("first_name", "there"))

    return TEXT_PROMPTS[prompt_key]





def list_choice(stage: str, form) -> tuple[str, str] | None:

    menu = LISTS[stage]

    by_id = {row_id: (label, value) for row_id, label, value in menu["rows"]}

    by_label = {label.casefold(): (label, value) for _, label, value in menu["rows"]}

    for candidate in (

        str(form.get("ButtonPayload", "")).strip(),

        str(form.get("Body", "")).strip(),

        str(form.get("ButtonText", "")).strip(),

    ):

        if candidate in by_id:

            return by_id[candidate]

        if candidate.casefold() in by_label:

            return by_label[candidate.casefold()]

        if candidate.isdigit():

            index = int(candidate) - 1

            if 0 <= index < len(menu["rows"]):

                _, label, value = menu["rows"][index]

                return label, value

    return None





def find_list_stage(stage: str) -> str | None:

    if stage in LISTS:

        return stage

    return None





def next_after_preferences(stage: str) -> str:

    return {

        "q8_loan": "q9_bhk",

        "q8_cash": "q9_bhk",

        "q8_developer": "q9_bhk",

    }[stage]



import traceback

@router.post("/webhooks/whatsapp")

async def whatsapp_webhook(request: Request, background_tasks: BackgroundTasks):

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

        if not re.fullmatch(r"[^@\s]+@[^@\s]+\\.[^@\s]+", text):

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
