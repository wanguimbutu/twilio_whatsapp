import frappe
import requests
import json
from requests.auth import HTTPBasicAuth


def get_twilio_settings():
    settings = frappe.get_single("Twilio Whatsapp Settings")
    if not settings.enabled:
        frappe.throw("Twilio WhatsApp is not enabled")
    return settings


def format_phone(number):
    """
    Format phone number to international format.
    Handles Kenyan numbers without country code.
    """
    if not number:
        frappe.throw("Phone number is required")

    # Remove spaces, dashes, brackets
    number = number.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")

    # Already has + prefix
    if number.startswith("+"):
        return number

    # Kenyan number starting with 07 or 01
    if number.startswith("07") or number.startswith("01"):
        return f"+254{number[1:]}"

    # Kenyan number starting with 7 or 1 (9 digits)
    if len(number) == 9 and (number.startswith("7") or number.startswith("1")):
        return f"+254{number}"

    # Starts with 254 but no +
    if number.startswith("254"):
        return f"+{number}"

    # Fallback — return as-is with +
    return f"+{number}"


@frappe.whitelist()
def send_whatsapp_message(to, body=None, content_sid=None, content_variables=None, media_url=None):
    """
    Send a WhatsApp message via Twilio.

    Args:
        to: Phone number (e.g., +254768140326, 0768140326, 768140326)
        body: Free-form text (for session messages)
        content_sid: Twilio Content Template SID (for template messages)
        content_variables: JSON string of template variables
        media_url: URL of media to attach (e.g., PDF link)
    """
    settings = get_twilio_settings()
    account_sid = settings.account_sid
    auth_token = settings.get_password("auth_token")

    to = format_phone(to)

    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"

    payload = {
        "To": f"whatsapp:{to}",
        "From": f"whatsapp:{settings.from_number}",
    }

    if content_sid:
        payload["ContentSid"] = content_sid
        if content_variables:
            payload["ContentVariables"] = content_variables if isinstance(content_variables, str) else json.dumps(content_variables)
    elif body:
        payload["Body"] = body
    else:
        frappe.throw("Either 'body' or 'content_sid' is required")

    if media_url:
        payload["MediaUrl"] = media_url

    response = requests.post(
        url,
        data=payload,
        auth=HTTPBasicAuth(account_sid, auth_token)
    )

    result = response.json()

    # Log the message
    frappe.get_doc({
        "doctype": "Comment",
        "comment_type": "Info",
        "content": f"WhatsApp sent to {to}: SID {result.get('sid', 'ERROR')} | Status: {result.get('status', response.status_code)}",
        "comment_email": frappe.session.user,
    }).insert(ignore_permissions=True)

    if response.status_code not in (200, 201):
        frappe.log_error(
            title="Twilio WhatsApp Error",
            message=f"To: {to}\nResponse: {json.dumps(result, indent=2)}"
        )
        frappe.throw(f"Failed to send WhatsApp: {result.get('message', 'Unknown error')}")

    return result
