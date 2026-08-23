from unittest import TestCase

from api.api.core.exceptions import UnprocessableEntityException
from api.api.core.pipes import run_default_pipes, run_pipes
from api.api.customer.pipes import validate_create_customer


class TestPipes(TestCase):
	def test_run_default_pipes_trims_strings_and_drops_cmd(self):
		result = run_default_pipes({"name": "  pong  ", "count": 1, "cmd": "x"})

		self.assertEqual(result, {"name": "pong", "count": 1})

	def test_run_pipes_runs_in_order(self):
		def add_name(data):
			data["name"] = "pong"
			return data

		def add_upper(data):
			data["upper"] = data["name"].upper()
			return data

		result = run_pipes({}, (add_name, add_upper))

		self.assertEqual(result, {"name": "pong", "upper": "PONG"})

	def test_validate_create_customer_requires_customer_name(self):
		with self.assertRaises(UnprocessableEntityException) as ctx:
			validate_create_customer({"customer_name": ""})

		self.assertEqual(ctx.exception.status_code, 422)
		self.assertEqual(ctx.exception.code, "CUSTOMER_NAME_REQUIRED")

	def test_validate_create_customer_rejects_invalid_email(self):
		with self.assertRaises(UnprocessableEntityException) as ctx:
			validate_create_customer({"customer_name": "ACME", "email": "invalid"})

		self.assertEqual(ctx.exception.status_code, 422)
		self.assertEqual(ctx.exception.code, "INVALID_EMAIL")

	def test_validate_create_customer_rejects_non_string_email(self):
		"""Body JSON bisa mengirim tipe apa pun; validator harus 422, bukan meledak jadi 500."""
		with self.assertRaises(UnprocessableEntityException) as ctx:
			validate_create_customer({"customer_name": "ACME", "email": 5})

		self.assertEqual(ctx.exception.status_code, 422)
		self.assertEqual(ctx.exception.code, "INVALID_EMAIL")

	def test_run_default_pipes_preserves_non_string_values(self):
		data = {"count": 1, "items": [" a "], "meta": {"name": " a "}, "active": True, "empty": None}

		self.assertEqual(run_default_pipes(data), data)

	def test_custom_pipes_receive_trimmed_values(self):
		seen = {}

		def assert_trimmed(data):
			seen["name"] = data["name"]
			return data

		run_pipes(run_default_pipes({"name": "  ACME  "}), (assert_trimmed,))

		self.assertEqual(seen["name"], "ACME")

	def test_run_pipes_passes_api_exception_through(self):
		def explode(_data):
			raise UnprocessableEntityException("bad", code="BAD")

		with self.assertRaises(UnprocessableEntityException) as ctx:
			run_pipes({}, (explode,))

		self.assertEqual(ctx.exception.code, "BAD")
