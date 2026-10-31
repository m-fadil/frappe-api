from __future__ import annotations

import frappe
from frappe import _

_PROFILE_FIELDS = (
	"name",
	"email",
	"first_name",
	"last_name",
	"full_name",
	"user_image",
	"language",
	"time_zone",
	"user_type",
)


def active_user(user: str) -> bool:
	return isinstance(user, str) and user != "Guest" and bool(frappe.db.get_value("User", user, "enabled"))


def get_user_profile(user: str) -> dict:
	"""Read only public own-profile fields, never a full User document."""
	profile = frappe.db.get_value("User", user, _PROFILE_FIELDS, as_dict=True)
	if not profile:
		frappe.throw(_("User disabled or missing"), frappe.AuthenticationError)
	from frappe.permissions import get_roles

	return {field: profile.get(field) for field in _PROFILE_FIELDS} | {"roles": get_roles(user)}
