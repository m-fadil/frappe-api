from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from api.rest_api.doctype.api_settings.api_settings import (
	APISettings,
	clear_old_logs,
	get_settings,
)


class TestAPISettings(TestCase):
	def test_get_settings_returns_defaults_when_no_db(self):
		with patch.object(frappe, "db", None):
			settings = get_settings()

		self.assertEqual(settings["enable_api"], 1)
		self.assertEqual(settings["enable_logging"], 1)
		self.assertEqual(settings["log_errors_only"], 0)
		self.assertEqual(settings["retention_days"], 30)

	def test_validate_rejects_non_positive_retention_days(self):
		doc = APISettings({"doctype": "API Settings"})
		doc.retention_days = 0

		with patch.object(frappe, "throw") as mock_throw:
			doc.validate()
			mock_throw.assert_called_once()

	def test_clear_old_logs_executes_delete_query(self):
		if not getattr(frappe, "db", None):
			frappe.local.db = MagicMock()

		with patch.object(frappe.db, "delete", return_value=12) as mock_delete:
			deleted = clear_old_logs(days=15)
			self.assertEqual(deleted, 12)
			mock_delete.assert_called_once()
