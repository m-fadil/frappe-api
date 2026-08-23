from dataclasses import dataclass


@dataclass(slots=True)
class CalculateDTO:
	left: float
	right: float
	operation: str
