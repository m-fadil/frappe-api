from api.api.core.exceptions import UnprocessableEntityException


def validate_create_customer(data: dict) -> dict:
	customer_name = data.get("customer_name")
	if not customer_name:
		raise UnprocessableEntityException(
			"customer_name is required",
			code="CUSTOMER_NAME_REQUIRED",
		)

	email = data.get("email")
	# str() dulu: payload JSON boleh mengirim tipe apa pun, harus jadi 422 bukan 500
	if email and "@" not in str(email):
		raise UnprocessableEntityException("Invalid email", code="INVALID_EMAIL")

	return data
