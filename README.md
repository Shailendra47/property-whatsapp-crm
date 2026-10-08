# Property Contact Form + WhatsApp Questionnaire + CRM

A FastAPI application with two customer forms, a Twilio WhatsApp questionnaire, MongoDB persistence, and a protected CRM dashboard.

## Quick start

1. Read [STEP_BY_STEP_GUIDE.md](STEP_BY_STEP_GUIDE.md) for MongoDB, Twilio, webhook, Sandbox, and production setup.
2. Create a virtual environment and install dependencies:

   ```bat
   py -m venv .venv
   .venv\Scripts\activate
   python -m pip install -r requirements.txt
   copy .env.example .env
   ```

3. Fill `.env` with private MongoDB, Twilio, and admin settings.
4. Start the app:

   ```bat
   python -m uvicorn main:app --reload --port 8000
   ```

5. Open the Contact Us form at `http://127.0.0.1:8000/`, the property enquiry form at `/enquiry`, or CRM login at `/admin/login`.

**WhatsApp:** Contact Us needs only name, email, and phone; no requirement text is needed. If the customer checks the optional WhatsApp questionnaire checkbox and submits the form, the app saves the opt-in and sends the configured start template: “Thanks for your interest! 🏡 Which location or area are you looking for a property in?” The form already supplies name, email, and mobile, so the WhatsApp questionnaire starts by asking for the location. If unchecked, the app saves the contact without messaging. Customer replies return to `/webhooks/whatsapp`. The exact custom opening text requires a registered WhatsApp sender and an approved template; the Sandbox does not support custom templates. Use an HTTPS public host (ngrok for local testing) for inbound webhooks.

For a template that requires placeholders, set `TWILIO_WHATSAPP_START_TEMPLATE_VARIABLES` to a JSON object in `.env`, for example `{"1":"12/1","2":"3pm"}` for the Sandbox Appointment Reminders template. Use the matching Content SID and required variables for the chosen template; that built-in appointment template sends an appointment reminder, not the custom property-location opening text.

Never share `.env`; it contains credentials. The supplied `.env.example` is safe to copy and fill in.
