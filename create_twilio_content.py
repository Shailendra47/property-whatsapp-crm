"""Create the WhatsApp templates used by the property questionnaire.

Run once after setting TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN in .env.
The script prints Content SIDs; paste them into .env. Submit the start text
template for WhatsApp approval in Twilio Console before enabling form sends.
"""

import os

import requests
from dotenv import load_dotenv

load_dotenv()

account_sid = os.getenv("TWILIO_ACCOUNT_SID")
auth_token = os.getenv("TWILIO_AUTH_TOKEN")
if not account_sid or not auth_token:
    raise SystemExit("Set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN in .env first.")

CONTENT_API_URL = "https://content.twilio.com/v1/Content"


def create_content(friendly_name: str, types: dict, variables: dict | None = None) -> str:
    payload = {
        "friendly_name": friendly_name,
        "language": "en",
        "types": types,
    }
    if variables:
        payload["variables"] = variables
    response = requests.post(
        CONTENT_API_URL,
        json=payload,
        auth=(account_sid, auth_token),
        timeout=30,
    )
    if not response.ok:
        raise SystemExit(
            f"Twilio could not create template {friendly_name!r} "
            f"(HTTP {response.status_code}): {response.text}"
        )
    return response.json()["sid"]

MENUS = {
    "planning": (
        "TWILIO_LIST_PLANNING_SID",
        "property_planning_to_buy",
        "When are you planning to buy?",
        [
            ("planning_immediately", "Immediately", "Immediately"),
            ("planning_1_month", "Within 1 Month", "Within 1 Month"),
            ("planning_3_months", "Within 3 Months", "Within 3 Months"),
            ("planning_6_months", "Within 6 Months", "Within 6 Months"),
            ("planning_12_months", "Within 12 Months", "Within 12 Months"),
            ("planning_over_1_year", "More Than 1 Year", "More Than 1 Year"),
            ("planning_exploring", "Just Exploring", "Just Exploring / Researching"),
        ],
    ),
    "budget": (
        "TWILIO_LIST_BUDGET_SID",
        "property_budget_range",
        "What's your budget range?",
        [
            ("budget_25_lakh", "Up to 25 Lakh", "Up to 25 lakh"),
            ("budget_25_50_lakh", "25 - 50 Lakh", "25 lakh - 50 lakh"),
            ("budget_50_lakh_1_crore", "50 Lakh - 1 Crore", "50 lakh - 1 crore"),
            ("budget_1_2_crore", "1 - 2 Crore", "1 crore - 2 crore"),
            ("budget_over_2_crore", "Above 2 Crore", "Above 2 crore"),
        ],
    ),
    "payment_category": (
        "TWILIO_LIST_PAYMENT_CATEGORY_SID",
        "property_payment_category",
        "How would you like to pay? Choose a category:",
        [
            ("pay_loan", "Loan / Bank Finance", "Choose loan or bank finance"),
            ("pay_cash", "Cash / Down Payment", "Choose cash or down payment"),
            ("pay_developer", "Developer Plans", "Choose a developer plan"),
            ("pay_nri", "NRI Payment Plan", "NRI Payment Plan (for Overseas Buyers)"),
        ],
    ),
    "payment_loan": (
        "TWILIO_LIST_PAYMENT_LOAN_SID",
        "property_payment_loan",
        "Choose your loan or bank-finance option:",
        [
            ("loan_bank_emi", "Bank Finance (EMI)", "Bank Finance with EMI"),
            ("loan_mortgage", "Home Loan (Mortgage)", "Home Loan (Mortgage)"),
            ("loan_part_cash", "Part Cash + Home Loan", "Part Cash + Home Loan"),
            ("loan_joint", "Joint Home Loan", "Joint Home Loan (Co-applicant Financing)"),
        ],
    ),
    "payment_cash": (
        "TWILIO_LIST_PAYMENT_CASH_SID",
        "property_payment_cash",
        "Choose your cash or down-payment option:",
        [
            ("cash_full", "Full Cash Payment", "Full Cash Payment"),
            ("cash_down_payment", "Down Payment Plan", "Down Payment Plan"),
            ("cash_balance_registration", "Balance at Registration", "Part Payment with Balance at Registration"),
        ],
    ),
    "payment_developer": (
        "TWILIO_LIST_PAYMENT_DEVELOPER_SID",
        "property_payment_developer",
        "Choose your developer payment plan:",
        [
            ("dev_clp", "Construction-Linked", "Construction-Linked Payment Plan (CLP)"),
            ("dev_plp", "Possession-Linked", "Possession-Linked Payment Plan (PLP)"),
            ("dev_installment", "Installment Plan", "Installment Payment Plan"),
            ("dev_financing", "Developer Financing", "Developer Financing"),
            ("dev_rent_to_own", "Rent-to-Own", "Rent-to-Own Scheme"),
            ("dev_subvention", "Subvention (Pre-EMI)", "Subvention Scheme (Developer Pays Pre-EMI)"),
            ("dev_flexible", "Flexible Payment Plan", "Flexible Payment Plan"),
        ],
    ),
    "bhk": (
        "TWILIO_LIST_BHK_SID",
        "property_bhk_preference",
        "What type of home are you looking for?",
        [
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
    ),
}

created = {}

start_sid = create_content(
    "property_contact_start",
    {
        "twilio/text": {
            "body": "Thank you for contacting us. Hi! 👋 Let's find your perfect property. What's your *first name*? Reply with your first name to continue."
        }
    },
)
created["TWILIO_WHATSAPP_START_TEMPLATE_SID"] = start_sid

for _, (env_name, friendly_name, question, rows) in MENUS.items():
    created[env_name] = create_content(
        friendly_name,
        {
            "twilio/list-picker": {
                "body": question,
                "button": "Choose an option",
                "items": [
                    {"id": row_id, "item": title, "description": description}
                    for row_id, title, description in rows
                ],
            }
        },
    )

created["TWILIO_QUICK_REPLY_MOBILE_SID"] = create_content(
    "property_mobile_confirmation",
    {
        "twilio/quick-reply": {
            "body": "Is {{1}} the best number to reach you?",
            "actions": [
                {"type": "QUICK_REPLY", "title": "Yes, same number", "id": "mobile_same"},
                {"type": "QUICK_REPLY", "title": "Use another number", "id": "mobile_other"},
            ],
        }
    },
    variables={"1": "+91 98765 43210"},
)

print("Created Twilio Content templates. Add these lines to .env:")
for key, sid in created.items():
    print(f"{key}={sid}")
print("\nSubmit property_contact_start for WhatsApp approval in Twilio Console.")
print("The list-picker and mobile quick-reply templates are used inside the 24-hour session.")
