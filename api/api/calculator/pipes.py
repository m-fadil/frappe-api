import math
from typing import Any

from api.api.calculator.service import OPERATIONS
from api.api.core.exceptions import UnprocessableEntityException


def _require_value(data: dict[str, Any], key: str, code: str) -> Any:
	value = data.get(key)
	if value in (None, ""):
		raise UnprocessableEntityException(f"{key} is required", code=code)
	return value


def _parse_operand(value: Any, key: str, code: str) -> float:
	try:
		parsed = float(value)
	except (TypeError, ValueError) as exc:
		raise UnprocessableEntityException(f"{key} must be numeric", code=code) from exc

	if not math.isfinite(parsed):
		raise UnprocessableEntityException(f"{key} must be numeric", code=code)

	return parsed


def validate_calculation(data: dict[str, Any]) -> dict[str, Any]:
	left = _parse_operand(_require_value(data, "left", "LEFT_REQUIRED"), "left", "INVALID_LEFT_OPERAND")
	right = _parse_operand(
		_require_value(data, "right", "RIGHT_REQUIRED"),
		"right",
		"INVALID_RIGHT_OPERAND",
	)
	# str() dulu: payload JSON boleh mengirim tipe apa pun, harus jadi 422 bukan 500
	operation = str(_require_value(data, "operation", "OPERATION_REQUIRED")).lower()

	if operation not in OPERATIONS:
		raise UnprocessableEntityException(
			f"operation must be one of: {', '.join(OPERATIONS)}",
			code="INVALID_OPERATION",
		)

	if operation == "divide" and right == 0:
		raise UnprocessableEntityException("Cannot divide by zero", code="DIVIDE_BY_ZERO")

	return {
		"left": left,
		"right": right,
		"operation": operation,
	}
