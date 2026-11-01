import frappe


def response_headers():
	"""Collect headers for Frappe 15's after_request response hook."""
	headers = getattr(frappe.local, "response_headers", None)
	if headers is None:
		headers = frappe.local.response_headers = {}
	return headers


def apply_response_headers(response, request):
	if response is not None:
		response.headers.update(getattr(frappe.local, "response_headers", {}))
