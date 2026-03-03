import frappe
import requests
import json
from requests.auth import HTTPBasicAuth


def get_twilio_settings():
    settings = frappe.get_single("Twilio WhatsApp Settings")
    if not settings.enabled:
        frappe.throw("Twilio WhatsApp is not enabled")
    return settings


@frappe.whitelist()
def send_whatsapp_message(to, body=None, content_sid=None, content_variables=None, media_url=None):
    """
    Send a WhatsApp message via Twilio.

    Args:
        to: Phone number with country code (e.g., +25476XXXX326)
        body: Free-form text (for session messages)
        content_sid: Twilio Content Template SID (for template messages)
        content_variables: JSON string of template variables
        media_url: URL of media to attach (e.g., PDF link)
    """
    settings = get_twilio_settings()
    account_sid = settings.account_sid
    auth_token = settings.get_password("auth_token")

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
