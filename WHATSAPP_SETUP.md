# Contact form WhatsApp questionnaire

For the full project installation, webhook setup, test steps, and delivery checklist, see [STEP_BY_STEP_GUIDE.md](STEP_BY_STEP_GUIDE.md).

## Connected pages and CRM

- `/` opens the Contact Us form.
- `/enquiry` opens the detailed property enquiry form.
- `/admin/login` opens the protected CRM login; after login, `/admin` shows the overview and combined **All Leads** list, with separate editable views for each form.
- Contact Us submissions are stored in the MongoDB `contacts` collection. Property form and completed WhatsApp questionnaire records are stored in `property_leads` by default. The CRM reads both collections, so leads from either customer form appear in the same dashboard.
- The CRM overview includes All Leads, separate editable lists, links to both public forms, and a Twilio configuration indicator. The indicator checks local settings and webhook URL format; it cannot confirm approval or delivery in Twilio.

Set `ADMIN_USERNAME`, `ADMIN_PASSWORD`, and a long random `SESSION_SECRET` in `.env` before using the CRM.

When a visitor checks the optional WhatsApp questionnaire box and submits Contact Us with **Send Enquiry**, the app saves the contact and opt-in record, then makes a Twilio API call to send the approved start template to that number. If unchecked, the contact is still saved but no WhatsApp message is sent. The page reports whether Twilio accepted the request. When the customer replies, the bot asks Q1–Q10 in order. Conversation state is saved in MongoDB's `whatsapp_conversations` collection. On completion, the final property enquiry is upserted into `property_leads` and attached to the original contact record.

The flow validates first name and email, supports skip for last name and remarks, confirms or replaces the mobile number, and uses native WhatsApp list pickers for planning, budget, payment categories/sub-options, and BHK. Payment options use separate category and sub-option menus so no list exceeds WhatsApp's 10-row limit.

## Configure Twilio

1. Install the supported dependencies: `python -m pip install -r requirements.txt`.
2. Copy `.env.example` to `.env`. Fill in `MONGODB_URI`, Twilio account SID and Auth Token, WhatsApp sender number, and the public HTTPS `PUBLIC_BASE_URL`. Keep `.env` private.
3. Run `python create_twilio_content.py` once to create Content API templates. Copy the printed Content SIDs into the matching `.env` entries.
4. Submit `property_contact_start` for WhatsApp approval in Twilio Console. The form-triggered first message requires a registered WhatsApp sender, a customer opt-in, and an approved start template. List pickers and quick replies are used after the recipient responds, inside the 24-hour customer service window.
5. Configure the WhatsApp sender's incoming-message webhook in Twilio as `https://YOUR_PUBLIC_HOST/webhooks/whatsapp`, method `POST`. The host must exactly match `PUBLIC_BASE_URL` in `.env`.
6. Run the app on a publicly reachable HTTPS host. When a customer submits Contact Us, the server stores the contact and attempts to send the start template. The page reports whether Twilio accepted that start message. A Twilio-accepted message may still be queued; check Twilio Messaging Logs for delivery status.

The Contact Us form asks for name, email, and an international-format phone number; it does not require a separate requirement/remarks field. The optional checkbox explicitly records the customer's WhatsApp opt-in and starts the WhatsApp flow only when selected. WhatsApp requires explicit opt-in for business-initiated messages. Keep `.env` private; never distribute it. If the Contact Us confirmation says setup is missing, it lists the relevant environment variable names. If Twilio rejects the message, use the app terminal and Twilio Messaging Logs to see the error.

## Sandbox testing

The Sandbox is intended for testing and can message only joined numbers. For automatic form-triggered starts, the Sandbox supports only its own pre-approved templates; your custom property start template requires a registered WhatsApp sender and approval. To test the custom form-triggered questionnaire, use a registered sender with the approved start template. Alternatively, for an inbound Sandbox test, have the customer join the Sandbox and use **Prefer WhatsApp? Start a chat**; the customer's `Hi` starts the questions inside the open session.

WhatsApp list-picker messages cannot start a business-initiated conversation; they are only sent after the recipient replies and opens the 24-hour window. See [Twilio's list-picker docs](https://www.twilio.com/docs/content/twiliolist-picker), [WhatsApp session rules](https://www.twilio.com/docs/whatsapp/key-concepts), and [template setup](https://www.twilio.com/docs/whatsapp/tutorial/send-whatsapp-notification-messages-templates).
