from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import frappe

from api.rest_api.doctype.api_settings.api_settings import get_settings

from .exceptions import ForbiddenException, ServiceUnavailableException


@dataclass(frozen=True, slots=True)
class RequestContext:
	user: str
	method: str
	endpoint: str


type Policy = Callable[[RequestContext], None]


def api_enabled(ctx: RequestContext) -> None:
	if not get_settings().get("enable_api", 1):
		raise ServiceUnavailableException("API service is currently disabled", code="API_DISABLED")


def guest_access_allowed(ctx: RequestContext) -> None:
	if ctx.user == "Guest" and not get_settings().get("allow_guest_access", 1):
		raise ForbiddenException("Guest access to API is disabled", code="GUEST_ACCESS_DISABLED")


def authenticated(ctx: RequestContext) -> None:
	if not ctx.user or ctx.user == "Guest":
		raise frappe.AuthenticationError("Authentication is required")


def native_authenticated(ctx: RequestContext) -> None:
	from api.services.auth.users import active_user

	authenticated(ctx)
	if getattr(frappe.local, "api_auth_method", None) == "jwt" or not active_user(ctx.user):
		raise frappe.AuthenticationError("Native Frappe authentication is required")


def require_roles(*roles: str) -> Policy:
	if not roles:
		raise ValueError("require_roles requires at least one role")
	required = frozenset(roles)

	def check(ctx: RequestContext) -> None:
		authenticated(ctx)
		if required.isdisjoint(frappe.get_roles(ctx.user)):
			raise frappe.PermissionError("Insufficient permissions")

	return check


DEFAULT_POLICIES = (api_enabled, guest_access_allowed)
