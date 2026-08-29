from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from api.rest_api.doctype.api_log.api_log import APILog


class TestAPILog(TestCase):
	def test_before_insert_sets_title_and_status_success(self):
		log_doc = APILog({"doctype": "API Log"})
		log_doc.status_code = 200
		log_doc.method = "GET"
		log_doc.endpoint = "api.api.ping.ping.ping"
		log_doc.before_insert()

		self.assertEqual(log_doc.status, "Success")
		self.assertEqual(log_doc.title, "[GET] 200 api.api.ping.ping.ping")
		self.assertIsNotNone(log_doc.timestamp)

	def test_before_insert_sets_title_and_status_error(self):
		log_doc = APILog({"doctype": "API Log"})
		log_doc.status_code = 422
		log_doc.method = "POST"
		log_doc.endpoint = "api.api.customer.create_customer.create_customer"
		log_doc.before_insert()

		self.assertEqual(log_doc.status, "Error")
		self.assertEqual(log_doc.title, "[POST] 422 api.api.customer.create_customer.create_customer")

	def test_clear_old_logs_calls_db_delete(self):
		if not getattr(frappe, "db", None):
			frappe.local.db = MagicMock()

		with patch.object(frappe.db, "delete", return_value=5) as mock_delete:
			deleted = APILog.clear_old_logs(days=30)
			self.assertEqual(deleted, 5)
			mock_delete.assert_called_once()
