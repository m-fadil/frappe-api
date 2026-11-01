import json
from contextlib import ExitStack
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe
from werkzeug.exceptions import Unauthorized

from api.api.core.exceptions import (
	BadRequestException,
	InternalServerErrorException,
	UnprocessableEntityException,
)
from api.api.core.logging import (
	AUTH_METADATA_ONLY,
	STANDARD,
	_mask_data,
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
			raise BadRequestException("Bad input", code="BAD_INPUT", payload={"field": "email"})

		local = SimpleNamespace(response={})
		with (
			patch("api.api.core.logging.record_api_log") as record,
			patch("api.api.core.logging.frappe.local", local),
		):
			resp = faulty()
		self.assertEqual(
			resp,
			{
				"_status_code": 400,
				"_title": "Bad Request",
				"_code": "BAD_INPUT",
				"_detail": "Bad input",
				"_payload": {"field": "email"},
			},
		)
		self.assertEqual(local.response["http_status_code"], 400)
		record.assert_called_once()
		self.assertEqual(record.call_args.kwargs["response_data"], resp)
		self.assertEqual(record.call_args.kwargs["error_message"], "Bad input")

	def test_log_decorator_catches_generic_exception_and_returns_500(self):
		@log()
		def crash():
			raise ZeroDivisionError("division by zero")

		local = SimpleNamespace(response={})
		with (
			patch("api.api.core.logging.record_api_log") as record,
			patch("api.api.core.logging.frappe.local", local),
			patch("api.api.core.logging.frappe.get_traceback", return_value="business traceback"),
		):
			resp = crash()
		self.assertEqual(resp["_status_code"], 500)
		self.assertEqual(resp["_code"], "INTERNAL_SERVER_ERROR")
		self.assertEqual(resp["_detail"], "division by zero")
		self.assertEqual(local.response["http_status_code"], 500)
		record.assert_called_once()
		self.assertEqual(record.call_args.kwargs["traceback_str"], "business traceback")

	def test_log_decorator_returns_and_records_success_result(self):
		@log(telemetry=STANDARD)
		def succeed(**kwargs):
			return {"message": "ok"}

		with patch("api.api.core.logging.record_api_log") as record:
			self.assertEqual(succeed(value="hello"), {"message": "ok"})
		record.assert_called_once()
		self.assertEqual(record.call_args.kwargs["request_data"], {"value": "hello"})
		self.assertEqual(record.call_args.kwargs["response_data"], {"message": "ok"})
		self.assertEqual(record.call_args.kwargs["status_code"], 200)

	def test_log_decorator_preserves_native_http_errors_and_statuses(self):
		for exception_type, status in (
			(frappe.AuthenticationError, 401),
			(frappe.PermissionError, 403),
			(frappe.ValidationError, 417),
			(frappe.RateLimitExceededError, 429),
			(Unauthorized, 401),
		):
			with self.subTest(exception_type=exception_type):
				error = exception_type("Native rejection")

				@log()
				def reject():
					raise error

				local = SimpleNamespace(response={})
				with (
					patch("api.api.core.logging.record_api_log") as record,
					patch("api.api.core.logging.frappe.local", local),
					patch("api.api.core.logging.frappe.get_traceback") as traceback,
				):
					with self.assertRaises(exception_type) as caught:
						reject()
				self.assertIs(caught.exception, error)
				self.assertEqual(
					getattr(caught.exception, "http_status_code", getattr(caught.exception, "code", None)),
					status,
				)
				self.assertNotIn("http_status_code", local.response)
				record.assert_not_called()
				traceback.assert_not_called()

	def test_log_rejects_unknown_telemetry_before_decoration(self):
		with self.assertRaises(ValueError):
			log(telemetry="unknown")

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


class TestAuthMetadataLogging(TestCase):
	def setUp(self):
		stack = ExitStack()
		self.addCleanup(stack.close)
		self.credential = "credential-that-must-never-appear"
		self.local = SimpleNamespace(
			response_headers={},
			response={},
			form_dict={"refresh_token": self.credential},
		)
		self.request = MagicMock()
		self.request.headers = {"Authorization": f"Bearer {self.credential}"}
		self.settings = stack.enter_context(
			patch(
				"api.api.core.logging._get_settings",
				return_value={
					"enable_logging": 1,
					"log_request_payload": 1,
					"log_response_payload": 1,
					"log_headers": 1,
					"mask_sensitive_data": 0,
				},
			)
		)
		self.record = stack.enter_context(patch("api.api.core.logging.record_api_log"))
		self.extract = stack.enter_context(patch("api.api.core.logging._extract_request_context"))
		self.serialize = stack.enter_context(patch("api.api.core.logging._safe_serialize"))
		self.traceback = stack.enter_context(patch("api.api.core.logging.frappe.get_traceback"))
		self.get_logger = stack.enter_context(patch("api.api.core.logging.frappe.logger"))
		self.logger = self.get_logger.return_value
		stack.enter_context(patch("api.api.core.logging.frappe.local", self.local))
		stack.enter_context(patch("api.api.core.logging.frappe.request", self.request))

	def assert_metadata_only(self, endpoint, status):
		self.get_logger.assert_called_once_with("api_auth", allow_site=True)
		self.logger.info.assert_called_once()
		args, kwargs = self.logger.info.call_args
		self.assertEqual(kwargs, {})
		self.assertEqual(len(args), 1)
		metadata = args[0]
		self.assertEqual(set(metadata), {"event", "endpoint", "status_code", "execution_time_ms"})
		self.assertEqual(metadata["endpoint"], f"{endpoint.__module__}.{endpoint.__qualname__}")
		self.assertEqual(metadata["status_code"], status)
		self.assertEqual(metadata["event"], "endpoint_failed" if status >= 400 else "endpoint_completed")
		self.assertIsInstance(metadata["execution_time_ms"], float)
		self.assertGreaterEqual(metadata["execution_time_ms"], 0)
		self.assertNotIn(self.credential, json.dumps(metadata))
		self.assertEqual(self.local.response_headers, {"Cache-Control": "no-store", "Pragma": "no-cache"})
		self.assertNotIn("http_status_code", self.local.response)
		self.record.assert_not_called()
		self.extract.assert_not_called()
		self.serialize.assert_not_called()
		self.traceback.assert_not_called()
		self.settings.assert_not_called()
		self.assertEqual(self.request.mock_calls, [])

	def test_success_never_logs_arguments_or_result_even_with_masking_disabled(self):
		result = {"access_token": self.credential, "refresh_token": self.credential}

		@log(telemetry=AUTH_METADATA_ONLY)
		def issue(body, **kwargs):
			self.assertEqual(self.local.response_headers["Cache-Control"], "no-store")
			self.assertEqual(self.local.response_headers["Pragma"], "no-cache")
			self.assertEqual(body, {"password": self.credential})
			self.assertEqual(kwargs, {"client_id": self.credential})
			return result

		self.assertIs(issue({"password": self.credential}, client_id=self.credential), result)
		self.assert_metadata_only(issue, 200)

	def test_native_errors_keep_consumer_status_without_logging_exception_messages(self):
		for exception_type, status in (
			(frappe.AuthenticationError, 401),
			(frappe.PermissionError, 403),
			(frappe.ValidationError, 417),
			(frappe.RateLimitExceededError, 429),
			(Unauthorized, 401),
		):
			with self.subTest(exception_type=exception_type):
				self.get_logger.reset_mock()
				error = exception_type(self.credential)

				@log(telemetry=AUTH_METADATA_ONLY)
				def reject(**kwargs):
					self.assertEqual(self.local.response_headers["Cache-Control"], "no-store")
					raise error

				with self.assertRaises(exception_type) as caught:
					reject(refresh_token=self.credential)
				self.assertIs(caught.exception, error)
				self.assertEqual(
					getattr(caught.exception, "http_status_code", getattr(caught.exception, "code", None)),
					status,
				)
				self.assert_metadata_only(reject, status)

	def test_payload_bearing_api_exception_is_not_serialized_or_logged(self):
		error = BadRequestException(
			self.credential,
			code=self.credential,
			payload={"refresh_token": self.credential},
		)

		@log(telemetry=AUTH_METADATA_ONLY)
		def reject(body):
			raise error

		with self.assertRaises(BadRequestException) as caught:
			reject({"refresh_token": self.credential})
		self.assertIs(caught.exception, error)
		self.assert_metadata_only(reject, 400)

	def test_generic_error_with_credential_text_propagates_only_sanitized_framework_error(self):
		@log(telemetry=AUTH_METADATA_ONLY)
		def crash(body):
			raise RuntimeError(f"Refresh credential rejected: {self.credential}")

		with self.assertRaises(InternalServerErrorException) as caught:
			crash({"refresh_token": self.credential})
		self.assertEqual(caught.exception.http_status_code, 500)
		self.assertEqual(caught.exception.message, "An unexpected error occurred")
		self.assertEqual(caught.exception.code, "INTERNAL_SERVER_ERROR")
		self.assertEqual(caught.exception.payload, {})
		self.assertNotIn(self.credential, str(caught.exception))
		self.assertTrue(caught.exception.__suppress_context__)
		self.assertIsNone(caught.exception.__cause__)
		self.assert_metadata_only(crash, 500)

	def test_generic_error_is_never_stringified(self):
		class CredentialError(Exception):
			def __str__(self):
				raise AssertionError("Exception messages must never be extracted")

		@log(telemetry=AUTH_METADATA_ONLY)
		def crash():
			raise CredentialError(self.credential)

		with self.assertRaises(InternalServerErrorException):
			crash()
		self.assert_metadata_only(crash, 500)
