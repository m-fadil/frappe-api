from __future__ import annotations

import secrets
import time

import frappe
import jwt

from api.services.auth.audit import audit
from api.services.auth.settings import get_jwt_settings
from api.services.auth.users import active_user


def access_token(user: str) -> dict:
	settings = get_jwt_settings()
	now = int(time.time())
	claims = {
		"sub": user,
		"iss": settings["issuer"],
		"aud": settings["audience"],
		"iat": now,
		"nbf": now,
		"exp": now + settings["access_ttl"],
		"jti": secrets.token_urlsafe(24),
		"typ": "access",
	}
	return {
		"access_token": jwt.encode(claims, settings["secret"], algorithm="HS256"),
		"token_type": "Bearer",
		"expires_in": settings["access_ttl"],
	}


def validate() -> None:
	header = frappe.get_request_header("Authorization", "") or ""
	parts = header.split()
	if not parts or parts[0].lower() != "bearer":
		return
	# Core OAuth validation precedes auth_hooks; never reinterpret an accepted OAuth token.
	if len(parts) == 2 and frappe.db.exists("OAuth Bearer Token", parts[1]):
		return
	try:
		if len(parts) != 2:
			raise jwt.InvalidTokenError()
		settings = get_jwt_settings()
		claims = jwt.decode(
			parts[1],
			settings["secret"],
			algorithms=["HS256"],
			issuer=settings["issuer"],
			audience=settings["audience"],
			options={"require": ["sub", "iss", "aud", "iat", "nbf", "exp", "jti", "typ"]},
		)
		if claims["typ"] != "access" or not active_user(claims["sub"]):
			raise jwt.InvalidTokenError()
	except jwt.PyJWTError:
		audit("jwt_rejected")
		frappe.local.response_headers["WWW-Authenticate"] = 'Bearer error="invalid_token"'
		raise frappe.AuthenticationError("Invalid or expired access token") from None
	form_dict = frappe.local.form_dict
	# Frappe requires set_user in auth hooks; signature, claims and active user are verified above.
	frappe.set_user(claims["sub"])  # nosemgrep: frappe-setuser
	frappe.local.form_dict = form_dict
	frappe.local.api_auth_method = "jwt"
