from api.api.core.decorators import endpoint
from api.api.customer.dto import CreateCustomerDTO
from api.api.customer.pipes import validate_create_customer
from api.api.customer.service import create_customer as create_customer_service


@endpoint(methods=("POST",), dto=CreateCustomerDTO, pipes=(validate_create_customer,))
def create_customer(body: CreateCustomerDTO):
	return create_customer_service(body)
