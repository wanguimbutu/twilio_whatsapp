import frappe
import json
from frappe.utils import nowdate, fmt_money, flt


@frappe.whitelist()
def send_sales_person_report(sales_person, to_phone):
    """
    Run the existing Outstanding Debts report filtered by Sales Person
    and send the results via WhatsApp.
    """
    from frappe.desk.query_report import run as run_report

    filters = {
        "sales_person": sales_person,
        "as_on_date": nowdate()
    }

    report = run_report(
        "Outstanding Debts",
        filters=filters,
        ignore_prepared_report=True
    )

    data = report.get("result", [])

    if not data:
        frappe.msgprint(f"No outstanding debts for {sales_person}")
        return

    sp_name = frappe.db.get_value("Sales Person", sales_person, "sales_person_name") or sales_person

    total_net_outstanding = 0
    total_overdue = 0
    customer_totals = {}

    for row in data:
        if not isinstance(row, dict) or not row.get("customer_name"):
            continue

        customer = row.get("customer_name")
        net_outstanding = flt(row.get("net_outstanding", 0))
        overdue = flt(row.get("overdue_amount", 0))

        total_net_outstanding += net_outstanding
        total_overdue += overdue

        customer_totals[customer] = {
            "net_outstanding": customer_totals.get(customer, {}).get("net_outstanding", 0) + net_outstanding,
            "overdue": customer_totals.get(customer, {}).get("overdue", 0) + overdue
        }

    sorted_customers = sorted(
        customer_totals.items(),
        key=lambda x: x[1]["net_outstanding"],
        reverse=True
    )

    currency = frappe.db.get_single_value("Global Defaults", "default_currency") or "KES"

    lines = [
        f"*Outstanding Debts Report*",
        f"Sales Person: {sp_name}",
        f"As on: {nowdate()}",
        f"---",
        f"*Net Outstanding: {fmt_money(total_net_outstanding, currency=currency)}*",
        f"*Overdue: {fmt_money(total_overdue, currency=currency)}*",
        f"Customers: {len(sorted_customers)}",
        f"---",
        f"*Top Customers:*",
    ]

    for customer, amounts in sorted_customers[:10]:
        overdue_flag = " ⚠️" if amounts["overdue"] > 0 else ""
        lines.append(
            f"• {customer}: {fmt_money(amounts['net_outstanding'], currency=currency)}"
            f" (Overdue: {fmt_money(amounts['overdue'], currency=currency)}){overdue_flag}"
        )

    if len(sorted_customers) > 10:
        remaining = sum(c[1]["net_outstanding"] for c in sorted_customers[10:])
        lines.append(f"• ... {len(sorted_customers) - 10} more: {fmt_money(remaining, currency=currency)}")

    message_body = "\n".join(lines)

    from twilio_whatsapp.api import send_whatsapp_message
    result = send_whatsapp_message(to=to_phone, body=message_body)

    return result


@frappe.whitelist()
def send_all_sales_person_reports():
    """Send Outstanding Debts report to all active Sales Persons."""
    sales_persons = frappe.db.sql("""
        SELECT
            sp.name as sales_person,
            sp.sales_person_name,
            COALESCE(emp.cell_phone, emp.company_phone) as phone
        FROM `tabSales Person` sp
        LEFT JOIN `tabEmployee` emp ON sp.employee = emp.name
        WHERE sp.enabled = 1
            AND (emp.cell_phone IS NOT NULL AND emp.cell_phone != ''
                 OR emp.company_phone IS NOT NULL AND emp.company_phone != '')
    """, as_dict=True)

    results = []
    for sp in sales_persons:
        try:
            send_sales_person_report(
                sales_person=sp.sales_person,
                to_phone=sp.phone
            )
            results.append({"sales_person": sp.sales_person_name, "status": "Sent"})
        except Exception as e:
            results.append({"sales_person": sp.sales_person_name, "status": f"Failed: {str(e)}"})
            frappe.log_error(title=f"WhatsApp Report Error: {sp.sales_person}")

    return results
