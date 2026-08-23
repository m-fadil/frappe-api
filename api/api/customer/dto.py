from dataclasses import dataclass


@dataclass(slots=True)
class CreateCustomerDTO:
	customer_name: str
	email: str | None = None
	phone: str | None = None
