from unittest import TestCase
from unittest.mock import MagicMock, patch

from api.api.core.exceptions import (
	BadRequestException,
	ForbiddenException,
	ServiceUnavailableException,
	UnprocessableEntityException,
)
from api.api.core.logging import (
	_mask_data,
	_safe_serialize,
	_to_legacy_error_response,
	log,
	record_api_log,
)


class TestLogging(TestCase):
	def test_to_legacy_error_response_formats_status_title_detail(self):
		exc = UnprocessableEntityException("customer_name is required", code="CUSTOMER_NAME_REQUIRED")
		resp = _to_legacy_error_response(exc)

		self.assertEqual(
			resp,
			{
				"_status_code": 422,
				"_title": "Unprocessable Entity",
				"_detail": "customer_name is required",
				"_code": "CUSTOMER_NAME_REQUIRED",
			},
		)

	def test_to_legacy_error_response_includes_optional_payload(self):
		exc = BadRequestException("invalid", payload={"field": "email"})
		resp = _to_legacy_error_response(exc)

		self.assertEqual(resp["_payload"], {"field": "email"})

	def test_log_decorator_catches_api_exception_and_returns_error_dict(self):
		@log()
		def faulty():
			raise BadRequestException("Bad input", code="BAD_INPUT")

		resp = faulty()
		self.assertEqual(resp["_status_code"], 400)
		self.assertEqual(resp["_code"], "BAD_INPUT")
		self.assertEqual(resp["_detail"], "Bad input")

	def test_log_decorator_catches_generic_exception_and_returns_500(self):
		@log()
		def crash():
			raise ZeroDivisionError("division by zero")

		resp = crash()
		self.assertEqual(resp["_status_code"], 500)
		self.assertEqual(resp["_code"], "INTERNAL_SERVER_ERROR")
		self.assertIn("division by zero", resp["_detail"])

	def test_log_decorator_returns_success_result(self):
		@log()
		def succeed():
			return {"message": "ok"}

		self.assertEqual(succeed(), {"message": "ok"})

	def test_log_decorator_blocks_request_when_api_disabled(self):
		disabled_settings = {"enable_api": 0}

		with patch("api.api.core.logging._get_settings", return_value=disabled_settings):

			@log()
			def test_endpoint():
				return "ok"

			with self.assertRaises(ServiceUnavailableException) as ctx:
				test_endpoint()

			self.assertEqual(ctx.exception.code, "API_DISABLED")

	def test_log_decorator_blocks_guest_when_guest_access_disabled(self):
		guest_disabled_settings = {"enable_api": 1, "allow_guest_access": 0}

		with (
			patch("api.api.core.logging._get_settings", return_value=guest_disabled_settings),
			patch("api.api.core.logging.frappe.session", MagicMock(user="Guest")),
		):

			@log()
			def guest_endpoint():
				return "ok"

			with self.assertRaises(ForbiddenException) as ctx:
				guest_endpoint()

			self.assertEqual(ctx.exception.code, "GUEST_ACCESS_DISABLED")

	def test_mask_data_masks_nested_sensitive_keys(self):
		data = {
			"username": "alice",
			"password": "secret_password",
			"nested": {
				"api_token": "xyz123",
				"public_field": "hello",
			},
			"items": [{"auth": "bearer token"}],
		}
		sensitive_keys = {"password", "token", "auth"}
		masked = _mask_data(data, sensitive_keys)

		self.assertEqual(masked["username"], "alice")
		self.assertEqual(masked["password"], "********")
		self.assertEqual(masked["nested"]["api_token"], "********")
		self.assertEqual(masked["nested"]["public_field"], "hello")
		self.assertEqual(masked["items"][0]["auth"], "********")

	def test_record_api_log_skips_when_logging_disabled(self):
		settings = {"enable_logging": 0}

		with (
			patch("api.api.core.logging._get_settings", return_value=settings),
			patch("api.api.core.logging.frappe.get_doc") as mock_get_doc,
		):
			record_api_log(endpoint="test", status_code=200, execution_time_ms=10.0)
			mock_get_doc.assert_not_called()

	def test_record_api_log_skips_success_when_log_errors_only(self):
		settings = {"enable_logging": 1, "log_errors_only": 1}

		with (
			patch("api.api.core.logging._get_settings", return_value=settings),
			patch("api.api.core.logging.frappe.get_doc") as mock_get_doc,
		):
			record_api_log(endpoint="test", status_code=200, execution_time_ms=10.0)
			mock_get_doc.assert_not_called()

	def test_record_api_log_skips_excluded_endpoints(self):
		settings = {"enable_logging": 1, "excluded_endpoints": "api.api.ping.ping.ping, other.endpoint"}

		with (
			patch("api.api.core.logging._get_settings", return_value=settings),
			patch("api.api.core.logging.frappe.get_doc") as mock_get_doc,
		):
			record_api_log(endpoint="api.api.ping.ping.ping", status_code=200, execution_time_ms=5.0)
			mock_get_doc.assert_not_called()
