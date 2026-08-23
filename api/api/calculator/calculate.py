from api.api.calculator.dto import CalculateDTO
from api.api.calculator.pipes import validate_calculation
from api.api.calculator.service import calculate as calculate_service
from api.api.core.decorators import endpoint


@endpoint(methods=("GET", "POST"), guest=True, dto=CalculateDTO, pipes=(validate_calculation,))
def calculate(body: CalculateDTO):
	return calculate_service(body)
