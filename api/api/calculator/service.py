from __future__ import annotations

import operator
from typing import TYPE_CHECKING

if TYPE_CHECKING:
	from api.api.calculator.dto import CalculateDTO


OPERATIONS = {
	"add": operator.add,
	"subtract": operator.sub,
	"multiply": operator.mul,
	"divide": operator.truediv,
}


def calculate(body: "CalculateDTO") -> dict[str, float | str]:
	result = OPERATIONS[body.operation](body.left, body.right)
	return {
		"operation": body.operation,
		"left": body.left,
		"right": body.right,
		"result": result,
	}
