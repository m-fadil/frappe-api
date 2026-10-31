from __future__ import annotations

import re
import secrets
from typing import Any

import frappe

DEFAULT_ACCESS_TOKEN_TTL = 900
DEFAULT_REFRESH_TOKEN_TTL = 30 * 24 * 60 * 60
DEFAULT_AUDIENCE = "api"
MIN_SECRET_BYTES = 32

_TTL_FIELDS = {
	"access_ttl": "api_jwt_access_token_ttl",
	"refresh_ttl": "api_jwt_refresh_token_ttl",
}


def _is_empty(value: Any, *, ttl: bool = False) -> bool:
	return value is None or value == "" or (ttl and value == 0)


def _configured_value(doc: Any, fieldname: str, *, ttl: bool = False) -> Any:
	value = doc.get(fieldname)
	if _is_empty(value, ttl=ttl):
		value = frappe.conf.get(fieldname)
	return value


def _document_secret(doc: Any) -> str | None:
	if _is_empty(doc.get("api_jwt_secret")):
		return None
	# Keep decryption errors visible: a broken encrypted secret is not an empty setting.
	return doc.get_password("api_jwt_secret")


def _validate_secret(value: Any) -> str:
	if not isinstance(value, str) or len(value.encode("utf-8")) < MIN_SECRET_BYTES:
		frappe.throw(
			frappe._("JWT signing secret must contain at least 32 UTF-8 bytes."),
			frappe.ValidationError,
		)
	return value


def _validate_ttl(value: Any, fieldname: str) -> int:
	if isinstance(value, int) and not isinstance(value, bool):
		ttl = value
	elif isinstance(value, str) and re.fullmatch(r"[+-]?[0-9]+", value):
		ttl = int(value)
	else:
		frappe.throw(
			frappe._("{0} must be a positive integer number of seconds.").format(fieldname),
			frappe.ValidationError,
		)
	if ttl <= 0:
		frappe.throw(
			frappe._("{0} must be a positive integer number of seconds.").format(fieldname),
			frappe.ValidationError,
		)
	return ttl


def validate_jwt_fields(doc: Any) -> None:
	"""Validate nonempty Desk values without materializing site-config defaults."""
	if not _is_empty(doc.get("api_jwt_secret")):
		_validate_secret(_document_secret(doc))
	for fieldname in _TTL_FIELDS.values():
		value = doc.get(fieldname)
		if not _is_empty(value, ttl=True):
			_validate_ttl(value, fieldname)


def _resolve_settings(doc: Any) -> dict[str, Any]:
	secret = _document_secret(doc)
	if _is_empty(secret):
		secret = frappe.conf.get("api_jwt_secret")
	if _is_empty(secret):
		frappe.throw(
			frappe._("JWT signing secret is not configured. Run site migration to initialize API Settings."),
			frappe.ValidationError,
		)

	settings = {"secret": _validate_secret(secret)}
	for key, default in (("issuer", None), ("audience", DEFAULT_AUDIENCE)):
		value = _configured_value(doc, f"api_jwt_{key}")
		if _is_empty(value):
			value = str(frappe.local.site) if key == "issuer" else default
		if not isinstance(value, str):
			frappe.throw(frappe._("JWT {0} must be a string.").format(key), frappe.ValidationError)
		settings[key] = value

	for key, default in (
		("access_ttl", DEFAULT_ACCESS_TOKEN_TTL),
		("refresh_ttl", DEFAULT_REFRESH_TOKEN_TTL),
	):
		fieldname = _TTL_FIELDS[key]
		value = _configured_value(doc, fieldname, ttl=True)
		settings[key] = _validate_ttl(default if _is_empty(value, ttl=True) else value, fieldname)
	return settings


def get_jwt_settings() -> dict[str, Any]:
	"""Resolve signing settings: nonempty Single values, site config, then defaults.

	The signing secret has no runtime default and is never generated on a request.
	"""
	return _resolve_settings(frappe.get_cached_doc("API Settings"))


def initialize_jwt_settings() -> None:
	"""Initialize missing values after schema sync, preserving explicit configuration.

	Saving the Password field delegates encryption to Frappe's document lifecycle.
	No commit is issued here; install/migration owns the surrounding transaction.
	"""
	doc = frappe.get_single("API Settings")
	changed = False
	if _is_empty(_document_secret(doc)) and _is_empty(frappe.conf.get("api_jwt_secret")):
		doc.set("api_jwt_secret", secrets.token_urlsafe(48))
		changed = True

	defaults = {
		"api_jwt_issuer": str(frappe.local.site),
		"api_jwt_audience": DEFAULT_AUDIENCE,
		"api_jwt_access_token_ttl": DEFAULT_ACCESS_TOKEN_TTL,
		"api_jwt_refresh_token_ttl": DEFAULT_REFRESH_TOKEN_TTL,
	}
	for fieldname, default in defaults.items():
		is_ttl = fieldname in _TTL_FIELDS.values()
		if _is_empty(_configured_value(doc, fieldname, ttl=is_ttl), ttl=is_ttl):
			doc.set(fieldname, default)
			changed = True
	_resolve_settings(doc)
	if changed:
		doc.save(ignore_permissions=True)
