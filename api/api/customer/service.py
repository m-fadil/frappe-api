from __future__ import annotations

from typing import TYPE_CHECKING

import frappe

if TYPE_CHECKING:
	from api.api.customer.dto import CreateCustomerDTO


def create_customer(body: "CreateCustomerDTO") -> dict[str, str]:
	doc = frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": body.customer_name,
			"email_id": body.email,
			"mobile_no": body.phone,
		}
	)
	doc.insert()
	return {"name": doc.name}
