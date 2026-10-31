from frappe.model.document import Document


class APIRefreshToken(Document):
	"""Read-only session metadata; api.services.auth.refresh_tokens owns all mutations."""
