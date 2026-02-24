import frappe
from frappe.utils import getdate, add_months, nowdate, fmt_money
from frappe.utils.pdf import get_pdf
from frappe.utils.file_manager import save_file


@frappe.whitelist()
def send_customer_statement(customer, to_phone, from_date=None, to_date=None):
    """
    Generate a Customer Statement of Account and send it via WhatsApp.

    Since Twilio trial accounts can't easily send PDFs via MediaUrl
    (needs a publicly accessible URL), we send a text summary
    and optionally attach the PDF to the Customer record.
    """
    if not from_date:
        from_date = add_months(nowdate(), -1)
    if not to_date:
        to_date = nowdate()

    customer_name = frappe.db.get_value("Customer", customer, "customer_name")

    # Get outstanding invoices
    invoices = frappe.db.sql("""
        SELECT
            name, posting_date, grand_total, outstanding_amount, due_date, currency
        FROM `tabSales Invoice`
        WHERE customer = %s
            AND posting_date BETWEEN %s AND %s
            AND docstatus = 1
            AND outstanding_amount > 0
        ORDER BY posting_date
    """, (customer, from_date, to_date), as_dict=True)

    if not invoices:
        frappe.msgprint(f"No outstanding invoices for {customer_name}")
        return

    total_outstanding = sum(inv.outstanding_amount for inv in invoices)
    currency = invoices[0].currency if invoices else "KES"

    # Build text summary
    lines = [
        f"*Statement of Account*",
        f"Customer: {customer_name}",
        f"Period: {from_date} to {to_date}",
        f"---",
    ]
    for inv in invoices:
        lines.append(
            f"• {inv.name} | {inv.posting_date} | "
            f"Total: {fmt_money(inv.grand_total, currency=currency)} | "
            f"Due: {fmt_money(inv.outstanding_amount, currency=currency)} | "
            f"Due Date: {inv.due_date}"
        )
    lines.append(f"---")
    lines.append(f"*Total Outstanding: {fmt_money(total_outstanding, currency=currency)}*")

    message_body = "\n".join(lines)

    # Send via WhatsApp
    from twilio_whatsapp.api import send_whatsapp_message
    result = send_whatsapp_message(to=to_phone, body=message_body)

    # Also generate and attach PDF to customer record for records
    _attach_statement_pdf(customer, from_date, to_date)

    return result


def _attach_statement_pdf(customer, from_date, to_date):
    """Generate and attach a PDF statement to the Customer doctype."""
    try:
        # Use ERPNext's built-in General Ledger report for the statement
        from erpnext.accounts.report.general_ledger.general_ledger import execute as gl_execute

        filters = frappe._dict({
            "company": frappe.defaults.get_user_default("company"),
            "party_type": "Customer",
            "party": [customer],
            "from_date": from_date,
            "to_date": to_date,
            "group_by": "Group by Voucher (Consolidated)",
        })

        columns, data = gl_execute(filters)[:2]

        # Build HTML for PDF
        html = frappe.render_template(
            "twilio_whatsapp/templates/statement.html",
            {
                "customer": customer,
                "customer_name": frappe.db.get_value("Customer", customer, "customer_name"),
                "from_date": from_date,
                "to_date": to_date,
                "columns": columns,
                "data": data,
                "company": frappe.defaults.get_user_default("company"),
            }
        )

        pdf = get_pdf(html)
        file_name = f"Statement_{customer}_{from_date}_to_{to_date}.pdf"

        save_file(
            fname=file_name,
            content=pdf,
            dt="Customer",
            dn=customer,
            is_private=1
        )
    except Exception:
        frappe.log_error(title="Statement PDF Generation Error")


@frappe.whitelist()
def send_bulk_statements(from_date=None, to_date=None):
    """
    Send statements to all customers who have outstanding invoices
    and a linked Sales Person with a phone number.
    """
    if not from_date:
        from_date = add_months(nowdate(), -1)
    if not to_date:
        to_date = nowdate()

    # Get customers with outstanding invoices
    customers = frappe.db.sql("""
        SELECT DISTINCT si.customer, c.customer_name, c.mobile_no
        FROM `tabSales Invoice` si
        JOIN `tabCustomer` c ON c.name = si.customer
        WHERE si.docstatus = 1
            AND si.outstanding_amount > 0
            AND si.posting_date BETWEEN %s AND %s
            AND c.mobile_no IS NOT NULL
            AND c.mobile_no != ''
    """, (from_date, to_date), as_dict=True)

    results = []
    for cust in customers:
        try:
            send_customer_statement(
                customer=cust.customer,
                to_phone=cust.mobile_no,
                from_date=from_date,
                to_date=to_date
            )
            results.append({"customer": cust.customer_name, "status": "Sent"})
        except Exception as e:
            results.append({"customer": cust.customer_name, "status": f"Failed: {str(e)}"})
            frappe.log_error(title=f"WhatsApp Statement Error: {cust.customer}")

    return results
