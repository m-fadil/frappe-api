from unittest import TestCase
from unittest.mock import patch

from api.api.core.exceptions import UnprocessableEntityException
from api.api.customer.dto import CreateCustomerDTO
from api.tests import load_endpoint_module


class TestCreateCustomerEndpoint(TestCase):
	def setUp(self):
		self.module = load_endpoint_module("api.api.customer.create_customer")

	def _form_dict(self, **values):
		return patch("api.api.core.request.frappe.form_dict", values)

	def test_create_customer_endpoint_builds_dto_and_calls_service(self):
		with (
			self._form_dict(
				customer_name="  ACME  ", email=" test@example.com ", phone=" 08123 ", cmd="ignored"
			),
			patch.object(
				self.module, "create_customer_service", return_value={"name": "CUST-0001"}
			) as service,
		):
			result = self.module.create_customer()

		self.assertEqual(result, {"name": "CUST-0001"})

		body = service.call_args.args[0]
		self.assertIsInstance(body, CreateCustomerDTO)
		self.assertEqual(body.customer_name, "ACME")
		self.assertEqual(body.email, "test@example.com")
		self.assertEqual(body.phone, "08123")

	def test_create_customer_endpoint_rejects_missing_customer_name(self):
		with self._form_dict(customer_name="   "):
			with self.assertRaises(UnprocessableEntityException) as ctx:
				self.module.create_customer()

		self.assertEqual(ctx.exception.status_code, 422)
		self.assertEqual(ctx.exception.code, "CUSTOMER_NAME_REQUIRED")

	def test_create_customer_endpoint_rejects_invalid_email(self):
		with self._form_dict(customer_name="ACME", email="not-an-email"):
			with self.assertRaises(UnprocessableEntityException) as ctx:
				self.module.create_customer()

		self.assertEqual(ctx.exception.status_code, 422)
		self.assertEqual(ctx.exception.code, "INVALID_EMAIL")

	def test_create_customer_endpoint_ignores_params_outside_the_dto(self):
		"""Query param nyasar (utm_*, token proxy) bukan alasan untuk 400."""
		with (
			self._form_dict(customer_name="ACME", utm_source="ads", unknown="value"),
			patch.object(
				self.module, "create_customer_service", return_value={"name": "CUST-0002"}
			) as service,
		):
			result = self.module.create_customer()

		self.assertEqual(result, {"name": "CUST-0002"})
		self.assertEqual(service.call_args.args[0].customer_name, "ACME")
