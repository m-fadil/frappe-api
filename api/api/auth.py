from __future__ import annotations

import frappe
from frappe.rate_limiter import rate_limit

from api.api.auth_dto import IssueTokenDTO, LoginDTO, RefreshTokenDTO, RevokeTokenDTO
from api.api.auth_pipes import (
	validate_issue_token,
	validate_login,
	validate_refresh_token,
	validate_revoke_token,
)
from api.api.core.decorators import endpoint
from api.api.core.logging import AUTH_METADATA_ONLY
from api.api.core.policies import api_enabled, native_authenticated
from api.services.auth.audit import audit
from api.services.auth.jwt import access_token
from api.services.auth.password import authenticate_login
from api.services.auth.refresh_tokens import create_session, rotate
from api.services.auth.refresh_tokens import revoke as revoke_session
from api.services.auth.users import get_user_profile


@endpoint(
	methods=("POST",),
	guest=True,
	dto=IssueTokenDTO,
	pipes=(validate_issue_token,),
	policies=(api_enabled, native_authenticated),
	normalize=False,
	telemetry=AUTH_METADATA_ONLY,
)
@rate_limit(limit=20, seconds=60, user_based=True)
def issue(body: IssueTokenDTO) -> dict:
	"""Exchange native Frappe authentication; JWT cannot bootstrap another family."""
	user = frappe.session.user
	result = access_token(user)
	result["refresh_token"] = create_session(user, body.client_id)
	audit("token_issued", user=user)
	return result


@endpoint(
	methods=("POST",),
	guest=True,
	dto=RefreshTokenDTO,
	pipes=(validate_refresh_token,),
	policies=(api_enabled,),
	normalize=False,
	telemetry=AUTH_METADATA_ONLY,
)
@rate_limit(limit=30, seconds=60)
def refresh(body: RefreshTokenDTO) -> dict:
	# Resolve signing configuration before consuming the refresh credential.
	from api.services.auth.settings import get_jwt_settings

	get_jwt_settings()
	try:
		user, replacement = rotate(body.refresh_token)
	except frappe.AuthenticationError:
		audit("refresh_rejected")
		raise
	result = access_token(user)
	result["refresh_token"] = replacement
	audit("token_refreshed", user=user)
	return result


@endpoint(
	methods=("POST",),
	guest=True,
	dto=RevokeTokenDTO,
	pipes=(validate_revoke_token,),
	policies=(api_enabled,),
	normalize=False,
	telemetry=AUTH_METADATA_ONLY,
)
@rate_limit(limit=30, seconds=60)
def revoke(body: RevokeTokenDTO) -> dict:
	revoke_session(body.refresh_token)
	audit("token_revoked")
	return {"revoked": True}


@endpoint(
	methods=("POST",),
	guest=True,
	xss_safe=True,
	dto=LoginDTO,
	pipes=(validate_login,),
	policies=(api_enabled,),
	normalize=False,
	telemetry=AUTH_METADATA_ONLY,
)
@rate_limit(limit=10, seconds=60)
def login(body: LoginDTO) -> dict:
	"""Authenticate native credentials and return JWTs with an allowlisted profile."""
	from api.services.auth.settings import get_jwt_settings

	get_jwt_settings()
	try:
		outcome = authenticate_login(body.usr, body.pwd, otp=body.otp, tmp_id=body.tmp_id)
	except frappe.AuthenticationError:
		audit("password_login_rejected")
		raise
	if isinstance(outcome, dict):
		return outcome
	profile = get_user_profile(outcome)
	result = access_token(outcome)
	result["refresh_token"] = create_session(outcome, body.client_id)
	result["user"] = profile
	audit("password_login_succeeded", user=outcome)
	return result
