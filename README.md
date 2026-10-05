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

**WhatsApp:** Contact Us needs only name, email, and phone; no requirement text is needed. If the customer checks the optional WhatsApp questionnaire checkbox and submits the form, the app saves the opt-in and calls Twilio to send the configured start Content template. If unchecked, it saves the contact without messaging. Customer replies return to `/webhooks/whatsapp`. Automatic starts with a custom template require a registered WhatsApp sender, an approved template, a customer's opt-in, and valid credentials. Use an HTTPS public host (ngrok for local testing) for inbound webhooks. Sandbox supports only pre-approved templates for business-initiated messages.

Never share `.env`; it contains credentials. The supplied `.env.example` is safe to copy and fill in.
