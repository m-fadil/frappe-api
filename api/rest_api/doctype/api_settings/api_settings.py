from __future__ import annotations

from typing import Any

import frappe
from frappe.model.document import Document
from frappe.utils import add_days, now

from api.services.auth.settings import validate_jwt_fields


class APISettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		allow_guest_access: DF.Check
		auto_cleanup: DF.Check
		enable_api: DF.Check
		enable_logging: DF.Check
		excluded_endpoints: DF.SmallText | None
		log_errors_only: DF.Check
		log_headers: DF.Check
		log_request_payload: DF.Check
		log_response_payload: DF.Check
		mask_sensitive_data: DF.Check
		max_payload_size_kb: DF.Int
		retention_days: DF.Int
		sensitive_fields: DF.SmallText | None
	# end: auto-generated types

	def validate(self) -> None:
		if self.retention_days is not None and self.retention_days < 1:
			frappe.throw(frappe._("Retention days must be at least 1 day."))
		if self.max_payload_size_kb is not None and self.max_payload_size_kb < 1:
			frappe.throw(frappe._("Max payload size must be at least 1 KB."))
		validate_jwt_fields(self)

	@frappe.whitelist()
	def clear_logs_now(self) -> int:
		"""Whitelisted method untuk membersihkan log lama secara instan via Desk."""
		days = self.retention_days or 30
		deleted = clear_old_logs(days=days)
		frappe.msgprint(frappe._("Deleted {0} old API log(s).").format(deleted))
		return deleted


def get_settings() -> dict[str, Any]:
	"""Ambil konfigurasi API Settings dengan fallback defaults bila belum terisi."""
	defaults: dict[str, Any] = {
		"enable_api": 1,
		"allow_guest_access": 1,
		"enable_logging": 1,
		"log_errors_only": 0,
		"log_request_payload": 1,
		"log_response_payload": 1,
		"log_headers": 1,
		"mask_sensitive_data": 1,
		"sensitive_fields": "password, token, auth, secret, api_key, api_secret, access_token, refresh_token, credit_card, cvv",
		"auto_cleanup": 1,
		"retention_days": 30,
		"max_payload_size_kb": 64,
		"excluded_endpoints": "",
	}

	try:
		if not getattr(frappe, "db", None):
			return defaults
		doc = frappe.get_cached_doc("API Settings")
		for key in defaults:
			val = getattr(doc, key, None)
			if val is not None:
				defaults[key] = val
	except Exception:
		pass

	return defaults


def clear_old_logs(days: int | None = None) -> int:
	"""Hapus API Log yang lebih lama dari retention_days."""
	try:
		if not getattr(frappe, "db", None):
			return 0

		if days is None:
			settings = get_settings()
			if not settings.get("auto_cleanup", 1):
				return 0
			days = settings.get("retention_days", 30)

		days = max(int(days or 30), 1)
		cutoff_date = add_days(now(), -days)

		deleted = frappe.db.delete("API Log", filters={"creation": ("<", cutoff_date)})
		return deleted or 0
	except Exception:
		return 0
