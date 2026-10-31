from unittest import TestCase
from unittest.mock import patch

from api.api.calculator.dto import CalculateDTO
from api.api.core.exceptions import UnprocessableEntityException
from api.tests import load_endpoint_module


class TestCalculatorEndpoint(TestCase):
	def setUp(self):
		self.module = load_endpoint_module("api.api.calculator.calculate")

	def _form_dict(self, **values):
		return patch("api.api.core.request.frappe.form_dict", values)

	def test_calculate_trims_and_evaluates_division(self):
		with self._form_dict(left=" 8 ", right=" 2 ", operation=" divide ", cmd="ignored"):
			result = self.module.calculate()

		self.assertEqual(
			result,
			{
				"operation": "divide",
				"left": 8.0,
				"right": 2.0,
				"result": 4.0,
			},
		)

	def test_calculate_endpoint_builds_dto_from_parsed_body(self):
		with (
			self._form_dict(left=7, right=5, operation="add"),
			patch.object(self.module, "calculate_service", return_value={"result": 12.0}) as service,
		):
			result = self.module.calculate()

		self.assertEqual(result, {"result": 12.0})
		body = service.call_args.args[0]
		self.assertIsInstance(body, CalculateDTO)
		self.assertEqual(body.left, 7.0)
		self.assertEqual(body.right, 5.0)
		self.assertEqual(body.operation, "add")

	def test_calculate_endpoint_rejects_missing_left(self):
		with self._form_dict(right="2", operation="add"):
			with self.assertRaises(UnprocessableEntityException) as ctx:
				self.module.calculate()

		self.assertEqual(ctx.exception.status_code, 422)
		self.assertEqual(ctx.exception.code, "LEFT_REQUIRED")

	def test_calculate_endpoint_rejects_invalid_operation(self):
		with self._form_dict(left="1", right="2", operation="mod"):
			with self.assertRaises(UnprocessableEntityException) as ctx:
				self.module.calculate()

		self.assertEqual(ctx.exception.status_code, 422)
		self.assertEqual(ctx.exception.code, "INVALID_OPERATION")

	def test_calculate_endpoint_rejects_non_string_operation(self):
		"""Body JSON bisa mengirim tipe apa pun; harus 422, bukan AttributeError jadi 500."""
		with self._form_dict(left=1, right=2, operation=5):
			with self.assertRaises(UnprocessableEntityException) as ctx:
				self.module.calculate()

		self.assertEqual(ctx.exception.status_code, 422)
		self.assertEqual(ctx.exception.code, "INVALID_OPERATION")

	def test_calculate_endpoint_rejects_divide_by_zero(self):
		with self._form_dict(left="10", right="0", operation="divide"):
			with self.assertRaises(UnprocessableEntityException) as ctx:
				self.module.calculate()

		self.assertEqual(ctx.exception.status_code, 422)
		self.assertEqual(ctx.exception.code, "DIVIDE_BY_ZERO")

	def test_calculate_endpoint_allows_zero_operand_for_non_divide_operations(self):
		"""right=0 hanya terlarang untuk divide; operasi lain tidak boleh ikut meledak."""
		for operation, expected in (("add", 1.0), ("subtract", 1.0), ("multiply", 0.0)):
			with self.subTest(operation=operation):
				with self._form_dict(left="1", right="0", operation=operation):
					self.assertEqual(self.module.calculate()["result"], expected)

	def test_calculate_endpoint_ignores_unknown_extra_fields(self):
		with self._form_dict(left=1, right=2, operation="add", extra="x"):
			result = self.module.calculate()

		self.assertEqual(result["result"], 3.0)
		self.assertEqual(result["operation"], "add")
