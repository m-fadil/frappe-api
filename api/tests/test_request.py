from unittest import TestCase
from unittest.mock import patch

from api.api.core.request import get_request_data


class TestRequest(TestCase):
	def test_get_request_data_merges_kwargs_and_form_dict(self):
		"""form_dict adalah satu-satunya sumber payload; kwargs pemanggil menang."""
		fake_form_dict = {"form_only": "value", "shared": "form", "cmd": "ignored"}

		with patch("api.api.core.request.frappe.form_dict", fake_form_dict):
			result = get_request_data({"kwarg_only": "value", "shared": "kwarg"})

		self.assertEqual(
			result,
			{"kwarg_only": "value", "form_only": "value", "shared": "kwarg"},
		)

	def test_get_request_data_preserves_types_parsed_by_frappe(self):
		"""make_form_dict sudah mem-parse JSON body, jadi tipe non-string harus lolos utuh."""
		fake_form_dict = {"count": 5, "items": [1, 2], "meta": {"a": 1}, "active": True}

		with patch("api.api.core.request.frappe.form_dict", fake_form_dict):
			self.assertEqual(get_request_data(), fake_form_dict)

	def test_get_request_data_does_not_reparse_request_body(self):
		"""Body non-JSON (form-urlencoded, multipart) tidak boleh jadi 400: frappe
		sudah menaruh hasil parse-nya di form_dict."""
		with (
			patch("api.api.core.request.frappe.form_dict", {"customer_name": "ACME"}),
			patch("api.api.core.request.frappe.request", None),
		):
			self.assertEqual(get_request_data(), {"customer_name": "ACME"})

	def test_get_request_data_survives_missing_request_context(self):
		class Unbound:
			def keys(self):
				raise RuntimeError("Working outside of request context")

		with patch("api.api.core.request.frappe.form_dict", Unbound()):
			self.assertEqual(get_request_data({"source": "kwargs"}), {"source": "kwargs"})
