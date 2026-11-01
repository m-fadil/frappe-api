from __future__ import annotations

from contextlib import contextmanager

import frappe
from frappe import _
from frappe.auth import LoginManager, validate_ip_address
from frappe.twofactor import ExpiredLoginException
from redis.exceptions import LockError

_CHALLENGE_SUFFIXES = ("_usr", "_pwd", "_otp_secret", "_token")
_VERIFICATION_FIELDS = ("method", "setup", "prompt", "token_delivery")
_MISSING = object()


class _PasswordLoginManager(LoginManager):
	"""Use native login security without creating or resuming a Frappe session."""

	__slots__ = ("authenticated", "challenge_verified")

	def __init__(self):
		# LoginManager.__init__ also resumes/creates sessions, even for guests.
		self.user = None
		self.info = None
		self.full_name = None
		self.user_type = None
		self.resume = False
		self.authenticated = False
		self.challenge_verified = False

	def login(self):
		# Frappe 15 checks password expiry before OTP and omits before_login.
		# Preserve the newer ordering: a reset key must not be issued until
		# the second factor has been verified.
		self.run_trigger("before_login")
		if frappe.get_system_settings("disable_user_pass_login"):
			frappe.throw(_("Login with username and password is not allowed."), frappe.AuthenticationError)

		user, pwd = frappe.auth.get_cached_user_pass()
		if frappe.form_dict.get("tmp_id") and user and not frappe.auth.should_run_2fa(user):
			frappe.throw(
				_("Two-factor login is no longer available; retry login"), frappe.AuthenticationError
			)
		self.authenticate(user=user, pwd=pwd)
		frappe.clear_cache(user=self.user)

		if frappe.form_dict.get("tmp_id") or frappe.auth.should_run_2fa(self.user):
			frappe.auth.authenticate_for_2factor(self.user)
			if not frappe.auth.confirm_otp_token(self):
				return False

		if self.force_user_to_reset_password():
			doc = frappe.get_doc("User", self.user)
			doc._reset_password(send_email=True, password_expired=True)
			frappe.local.response["message"] = "Password Reset"
			return False

		frappe.form_dict.pop("pwd", None)
		self.post_login()

	def force_user_to_reset_password(self):
		# Native login reaches this check only after any required OTP passed.
		self.challenge_verified = True
		return super().force_user_to_reset_password()

	def post_login(self, session_end=None, audit_user=None):
		self.run_trigger("on_login")
		validate_ip_address(self.user)
		self.validate_hour()
		self.get_user_info()
		self.authenticated = True


@contextmanager
def _native_login_context(form, manager):
	"""Keep native form/response side effects private to this login attempt."""
	original = {
		name: getattr(frappe.local, name, _MISSING) for name in ("form_dict", "login_manager", "response")
	}
	response = frappe._dict()
	frappe.local.form_dict = form
	frappe.local.login_manager = manager
	frappe.local.response = response
	try:
		yield response
	finally:
		for name, value in original.items():
			if value is _MISSING:
				delattr(frappe.local, name)
			else:
				setattr(frappe.local, name, value)


def _run_login(form):
	manager = _PasswordLoginManager()
	with _native_login_context(form, manager) as response:
		try:
			manager.login()
		except ExpiredLoginException:
			frappe.throw(
				_("Login session expired, retry with your username and password"),
				frappe.AuthenticationError,
			)
		finally:
			if manager.challenge_verified and form.get("tmp_id"):
				frappe.cache.delete_value([form.tmp_id + suffix for suffix in _CHALLENGE_SUFFIXES])

		if response.get("message") == "Password Reset":
			frappe.throw(_("Password reset required"), frappe.AuthenticationError)
		if manager.authenticated:
			if manager.user == "Guest" or not frappe.db.get_value("User", manager.user, "enabled"):
				frappe.throw(_("User disabled or missing"), frappe.AuthenticationError)
			return manager.user

		tmp_id = response.get("tmp_id")
		verification = response.get("verification")
		if isinstance(tmp_id, str) and tmp_id and isinstance(verification, dict):
			return {
				"mfa_required": True,
				"tmp_id": tmp_id,
				"verification": {
					key: verification[key] for key in _VERIFICATION_FIELDS if key in verification
				},
			}
		frappe.throw(_("Login could not be completed"), frappe.AuthenticationError)


def authenticate_login(
	usr: str | None,
	pwd: str | None,
	otp: str | None = None,
	tmp_id: str | None = None,
) -> str | dict:
	"""Return a canonical user or native MFA challenge, never credentials or a sid."""
	if otp is None and tmp_id is None:
		return _run_login(frappe._dict(usr=usr, pwd=pwd))
	if not (isinstance(otp, str) and otp and isinstance(tmp_id, str) and tmp_id):
		frappe.throw(_("Incomplete two-factor login details"), frappe.AuthenticationError)

	cache = frappe.cache
	# A lease outlives every native challenge key. If slow hooks outlive the
	# lease, another request can acquire the lock but cannot authenticate.
	ttl = max(cache.pttl(cache.make_key(tmp_id + suffix)) for suffix in _CHALLENGE_SUFFIXES)
	if ttl <= 0:
		frappe.throw(
			_("Login session expired, retry with your username and password"), frappe.AuthenticationError
		)
	try:
		with cache.lock(
			cache.make_key(f"api:password-login:{tmp_id}"), timeout=ttl / 1000 + 5, blocking_timeout=5
		):
			# Never fall back to caller-supplied credentials for an expired or
			# replayed challenge. Native login reads these same site-scoped keys.
			for suffix in _CHALLENGE_SUFFIXES:
				key = cache.make_key(tmp_id + suffix)
				# Frappe 15's get_value(expires=True) may still read a stale
				# request-local entry; native OTP handling must see Redis.
				frappe.local.cache.pop(key, None)
				if suffix != "_token" and not cache.get(key):
					frappe.throw(
						_("Login session expired, retry with your username and password"),
						frappe.AuthenticationError,
					)
			return _run_login(frappe._dict(otp=otp, tmp_id=tmp_id))
	except LockError:
		frappe.throw(_("Login challenge is already being processed; retry"), frappe.AuthenticationError)
