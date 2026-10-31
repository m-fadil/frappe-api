import frappe
from frappe.auth import MAX_PASSWORD_SIZE

from api.services.auth.audit import audit


def validate_issue_token(data: dict) -> dict:
	client_id = data.get("client_id")
	if client_id is not None and (not isinstance(client_id, str) or len(client_id) > 140):
		raise frappe.ValidationError("Invalid client_id")
	return data


def validate_refresh_token(data: dict) -> dict:
	refresh_token = data.get("refresh_token")
	if not isinstance(refresh_token, str) or not refresh_token or len(refresh_token) > 512:
		audit("refresh_rejected")
		raise frappe.AuthenticationError("Invalid or expired refresh token")
	return data


def validate_revoke_token(data: dict) -> dict:
	refresh_token = data.get("refresh_token")
	if not isinstance(refresh_token, str) or not refresh_token or len(refresh_token) > 512:
		raise frappe.ValidationError("refresh_token must be a nonempty string of at most 512 characters")
	return data


def validate_login(data: dict) -> dict:
	"""Validate shape only; native Frappe verifies password and MFA credentials."""
	validate_issue_token(data)
	usr, pwd = data.get("usr"), data.get("pwd")
	otp, tmp_id = data.get("otp"), data.get("tmp_id")
	if otp is not None or tmp_id is not None:
		if (
			not isinstance(otp, str)
			or not otp
			or len(otp) > 32
			or not isinstance(tmp_id, str)
			or not tmp_id
			or len(tmp_id) > 140
		):
			raise frappe.AuthenticationError("Invalid verification details")
	else:
		if (
			not isinstance(usr, str)
			or not usr
			or len(usr) > 320
			or not isinstance(pwd, str)
			or not pwd
			or len(pwd) > MAX_PASSWORD_SIZE
		):
			raise frappe.AuthenticationError("Invalid login credentials")
	return data
