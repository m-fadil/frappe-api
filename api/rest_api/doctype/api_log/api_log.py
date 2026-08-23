from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class APILog(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		endpoint: DF.Data | None
		error_code: DF.Data | None
		error_message: DF.SmallText | None
		execution_time: DF.Float
		headers: DF.Code | None
		host: DF.Data | None
		ip_address: DF.Data | None
		method: DF.Data | None
		path: DF.SmallText | None
		request_data: DF.Code | None
		response_data: DF.Code | None
		status: DF.Literal["Success", "Error", "Warning"]
		status_code: DF.Int
		timestamp: DF.Datetime | None
		title: DF.Data | None
		traceback: DF.Code | None
		user: DF.Link | None
		user_agent: DF.SmallText | None
	# end: auto-generated types

	def before_insert(self) -> None:
		if not self.status:
			code = int(self.status_code or 200)
			self.status = "Success" if code < 400 else "Error"

		if not self.title:
			method = self.method or "GET"
			status_code = self.status_code or 200
			path = self.endpoint or self.path or ""
			self.title = f"[{method}] {status_code} {path}".strip()

		if not self.timestamp:
			self.timestamp = now_datetime()

	@staticmethod
	def clear_old_logs(days: int = 30) -> int:
		"""Hapus log yang lebih tua dari N hari."""
		try:
			if not getattr(frappe, "db", None):
				return 0
			days = max(int(days), 1)
			deleted = frappe.db.delete(
				"API Log",
				filters={"creation": ("<", frappe.utils.add_days(frappe.utils.now(), -days))},
			)
			return deleted or 0
		except Exception:
			return 0
