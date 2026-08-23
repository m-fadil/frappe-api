from unittest import TestCase

from api.api.core.exceptions import (
	ApiException,
	BadRequestException,
	InternalServerErrorException,
	UnprocessableEntityException,
)


class TestExceptions(TestCase):
	def test_api_exception_keeps_http_fields(self):
		error = ApiException("broken", status_code=499, code="BROKEN", payload={"x": 1})

		self.assertEqual(error.message, "broken")
		self.assertEqual(error.status_code, 499)
		self.assertEqual(error.code, "BROKEN")
		self.assertEqual(error.payload, {"x": 1})

	def test_api_exception_exposes_status_under_frappe_attribute_name(self):
		"""frappe/app.py membaca `http_status_code`. Tanpa alias ini tiap ApiException
		yang lolos ke handler Frappe jadi 500, berapa pun status_code-nya."""
		for error in (BadRequestException(), UnprocessableEntityException(), InternalServerErrorException()):
			with self.subTest(error=type(error).__name__):
				self.assertEqual(error.http_status_code, error.status_code)

	def test_http_exception_uses_default_status(self):
		error = UnprocessableEntityException("bad input")

		self.assertEqual(error.message, "bad input")
		self.assertEqual(error.status_code, 422)

	def test_http_exception_defaults_message_code_and_payload(self):
		error = BadRequestException()

		self.assertEqual(error.message, "Bad Request")
		self.assertEqual(error.status_code, 400)
		self.assertIsNone(error.code)
		self.assertEqual(error.payload, {})
		self.assertEqual(str(error), "Bad Request")

	def test_api_exception_payload_is_isolated_per_instance(self):
		first = InternalServerErrorException()
		second = InternalServerErrorException()

		first.payload["trace"] = "one"

		self.assertEqual(second.payload, {})
