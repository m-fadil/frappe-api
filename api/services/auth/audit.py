from __future__ import annotations

import frappe


def audit(event: str, **metadata) -> None:
	"""Security events deliberately exclude request bodies, headers and credentials."""
	frappe.logger("api_auth", allow_site=True).info({"event": event, **metadata})
