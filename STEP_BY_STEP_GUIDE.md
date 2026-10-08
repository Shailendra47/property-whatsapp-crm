# Property Contact Form, WhatsApp Bot, and CRM — Handover Guide

This guide takes the project from extraction to a working local demonstration. Keep the real `.env` file private; it contains database and Twilio credentials.

## 1. What the project does

1. A customer opens the Contact Us page, enters an international-format WhatsApp number, optionally checks the WhatsApp questionnaire box, and clicks **Send Enquiry**.
2. The app saves the contact in MongoDB's `contacts` collection.
3. If the customer checked the WhatsApp box, the server asks Twilio to send the configured WhatsApp start template. If unchecked, no WhatsApp message is sent.
4. When the customer replies, Twilio POSTs the message to the app's `/webhooks/whatsapp` endpoint.
5. The bot asks the selected property questions and stores conversation state in `whatsapp_conversations`.
6. When the questionnaire is complete, the answers are saved in `property_leads` and shown in the CRM.

The app provides these pages:

| Page | URL | Purpose |
| --- | --- | --- |
| Contact Us form | `/` | Captures contact details; the optional checkbox controls whether the WhatsApp questionnaire starts. |
| Property Enquiry form | `/enquiry` | Captures property preferences directly. |
| CRM login | `/admin/login` | Protected admin sign-in. |
| CRM dashboard | `/admin` | Overview, combined All Leads table, and separate contact/property lead management. |

## 2. Requirements

- Python 3.11 or newer.
- A MongoDB Atlas database and a connection URI.
- A Twilio account with WhatsApp Sandbox access for inbound testing, or a registered WhatsApp sender for production.
- ngrok or another HTTPS tunnel for local webhook testing. For production, deploy the app on a stable public HTTPS host.

## 3. Extract and install

Open Command Prompt in the extracted `property-contact-form` folder. This folder should contain `main.py`, `whatsapp_bot.py`, and `requirements.txt`.

```bat
py -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
copy .env.example .env
```

If PowerShell is being used, activate the environment with:

```powershell
.\.venv\Scripts\Activate.ps1
```

## 4. Configure MongoDB and admin access

Edit `.env` and replace the example values:

```env
MONGODB_URI=mongodb+srv://<db-user>:<db-password>@<cluster>/<database>?retryWrites=true&w=majority
DB_NAME=property_db
COLLECTION_NAME=contacts
ENQUIRY_COLLECTION_NAME=property_leads
ADMIN_USERNAME=admin
ADMIN_PASSWORD=<a-strong-private-password>
SESSION_SECRET=<a-long-random-private-string>
```

In MongoDB Atlas, create a database user and allow the host where the app runs in **Network Access**. If the database password contains URL-reserved characters, URL-encode those characters in `MONGODB_URI`.

## 5. Configure Twilio credentials and sender

Add the credentials from the same Twilio account that owns the sender and Content templates:

```env
TWILIO_ACCOUNT_SID=AC<your-account-sid>
TWILIO_AUTH_TOKEN=<your-private-auth-token>
TWILIO_WHATSAPP_FROM=+<your-whatsapp-enabled-sender-number>
TWILIO_WHATSAPP_START_TEMPLATE_SID=HX<approved-start-template-sid>
```

Use the sender in E.164 format (country code plus number), without the `whatsapp:` prefix. Do not paste the Auth Token into chat or include `.env` when sharing the project.

### Sandbox or production?

- **Sandbox inbound demonstration:** each test phone must first send the Sandbox join phrase. The Sandbox can receive inbound messages and exercise the questionnaire. It supports only its pre-approved templates for business-initiated messages; a custom property-questionnaire start template cannot be used as the Sandbox's form-triggered start.
- **Automatic custom start on form submit:** use a registered WhatsApp sender and an approved start template in that sender's Twilio account. The form notice tells customers that submitting opts them in to the WhatsApp follow-up; retain this clear notice and honor `STOP` replies.

WhatsApp requires explicit opt-in and approved templates for business-initiated conversations. See [Twilio WhatsApp requirements](https://www.twilio.com/docs/whatsapp/api) and [Sandbox limitations](https://www.twilio.com/docs/whatsapp/sandbox).

## 6. Create the Content templates

With the virtual environment active and Twilio credentials saved in `.env`, run once:

```bat
python create_twilio_content.py
```

The script prints `HX...` Content SIDs. Copy each printed line into the corresponding `.env` variable, including:

- `TWILIO_WHATSAPP_START_TEMPLATE_SID`
- planning, budget, payment category/subcategory, and BHK list-picker SIDs
- `TWILIO_QUICK_REPLY_MOBILE_SID`

Submit the `property_contact_start` template for WhatsApp approval in Twilio Console. Its opening message is “Thanks for your interest! 🏡 Which location or area are you looking for a property in?” The first template must be approved before it can start a business-initiated chat. The list-picker and quick-reply templates are used after the customer has replied. If Twilio reports `ContentSid is Invalid`, confirm the SID is an `HX...` SID from this same account and was copied without spaces. The Sandbox cannot send this custom start template; use a registered WhatsApp sender for this form-triggered flow.

## 7. Run the app and expose a local HTTPS webhook

Start the app in one terminal:

```bat
python -m uvicorn main:app --reload --port 8000
```

Start ngrok in a second terminal:

```bat
ngrok http 8000
```

Copy the HTTPS forwarding origin shown by ngrok, for example `https://example-id.ngrok-free.app`. Set that exact origin (no route path and no trailing slash) in `.env`:

```env
PUBLIC_BASE_URL=https://example-id.ngrok-free.app
```

Restart Uvicorn after changing `.env`. Keep both terminals running while testing. A free ngrok URL can change after restarting ngrok; update both `.env` and Twilio whenever it changes.

## 8. Set Twilio's incoming-message webhook

For Sandbox testing, open **Twilio Console → Messaging → Try it out → Send a WhatsApp message → Sandbox settings**. In **When a message comes in**, enter:

```text
https://example-id.ngrok-free.app/webhooks/whatsapp
```

Choose **POST** and save. For a registered WhatsApp sender, open **Messaging → Senders → WhatsApp Senders**, select the sender, and set its inbound-message webhook to the same URL with **POST**. The URL origin must match `PUBLIC_BASE_URL` exactly. Twilio's current webhook configuration locations are described in its [WhatsApp API guide](https://www.twilio.com/docs/whatsapp/api).

## 9. Test the project

### Test inbound chatbot replies in the Sandbox

1. Join your test phone to the Sandbox using the join phrase displayed in Twilio.
2. Send `Hi` to the Sandbox number.
3. Confirm the app terminal/ngrok shows a POST to `/webhooks/whatsapp` and that Q1 is returned.
4. Continue answering. Use `skip` for optional last name or remarks.
5. Complete the flow, then log into `/admin/login` and open **All Leads** or **Property Enquiries**. The completed lead should appear in `property_leads`.

### Test automatic form-triggered opening message

1. Use a registered WhatsApp sender with an approved start template. The template created by `create_twilio_content.py` says “Thanks for your interest! 🏡 Which location or area are you looking for a property in?” The Sandbox cannot send this custom start template.
2. Confirm all four required outbound settings are valid: Account SID, Auth Token, WhatsApp sender, and approved start-template SID.
3. Open `/`, enter a number that has opted in and can receive messages, then click **Send Enquiry**.
4. The app saves the contact and calls Twilio. The confirmation shows whether Twilio accepted the request. Acceptance means Twilio created the message; check **Twilio Console → Messaging → Logs** for final delivery status.
5. Reply with a city or area to continue the questionnaire. The contact form's name, email, and phone are carried into the conversation, so the WhatsApp flow begins with location and continues with planning date, budget, payment choice, home type, and optional remarks.

## 10. Open and use the CRM

Open `http://127.0.0.1:8000/admin/login` and sign in using `ADMIN_USERNAME` and `ADMIN_PASSWORD` from `.env`.

- **Overview** shows lead counts, recent entries, and the WhatsApp configuration indicator.
- **All Leads** combines Contact Us and property enquiry records and supports search.
- **Contact Us Leads** and **Property Enquiries** have separate searchable tables with add, edit, and delete actions.
- The header links back to both forms.

The WhatsApp indicator checks local settings and HTTPS URL shape only; it cannot verify template approval, the Console webhook setting, or final delivery.

## 11. Troubleshooting

| Symptom | Check |
| --- | --- |
| Form says WhatsApp setup is missing | It lists missing setting names. Fill those in `.env` and restart Uvicorn. Use valid `AC...` Account SID, `HX...` Content SID, and E.164 sender. |
| Twilio rejected the start message | Read the app terminal exception and open Messaging Logs for the Twilio error code. Check that sender, recipient, template, and credentials belong to the same account. |
| ContentSid Invalid / error 21655 | Use the actual Content SID from the same account, not an example SID, message SID (`MM...`), or Account SID (`AC...`). |
| Twilio still sends the default “Configure your Sandbox Inbound URL” message | Save the exact public `/webhooks/whatsapp` URL in Sandbox settings, choose POST, and ensure ngrok and Uvicorn are running. |
| Webhook returns invalid signature | Make sure `PUBLIC_BASE_URL` exactly matches the public URL Twilio calls; update it when the ngrok address changes, then restart Uvicorn. |
| Sandbox recipient cannot receive messages | Rejoin using the current Sandbox join phrase; membership expires after 72 hours. |
| Contact form works but replies do not | Check the webhook URL and method. Localhost/127.0.0.1 cannot be reached by Twilio; use HTTPS ngrok for development or a public deployment. |
| CRM login or data fails | Set `ADMIN_PASSWORD` and `SESSION_SECRET`; verify MongoDB URI, Atlas Network Access, and that the app starts without a MongoDB error. |

## 12. Delivery checklist

- [ ] `.env` contains real settings and is excluded from the delivery ZIP.
- [ ] MongoDB Atlas is reachable from the deployment host.
- [ ] Both public forms submit successfully and records appear in CRM.
- [ ] Admin credentials are private and non-default.
- [ ] Sandbox join and inbound chatbot flow have been demonstrated.
- [ ] For automatic custom form-triggered starts, the production sender is registered and the start template is approved.
- [ ] Twilio inbound webhook points to the production HTTPS host at `/webhooks/whatsapp` with POST.
- [ ] Twilio Messaging Logs show an accepted/delivered message during the live test.
- [ ] `.env`, Auth Token, and database password are not in screenshots, source control, or the delivered ZIP.
