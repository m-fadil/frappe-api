from api.api.core.decorators import endpoint
from api.api.ping.service import ping as ping_service


@endpoint(methods=("GET",), guest=True)
def ping():
	return ping_service()
