from __future__ import annotations

import secrets
from concurrent.futures import ThreadPoolExecutor, wait
from contextlib import ExitStack
from datetime import datetime
from threading import Barrier
from unittest.mock import patch

import frappe
import pyotp
from frappe.auth import CookieManager, LoginAttemptTracker
from frappe.tests.utils import FrappeTestCase
from frappe.twofactor import get_otpsecret_for_, set_default
from frappe.utils import add_days, today
from frappe.utils.password import set_encrypted_password, update_password
from werkzeug.wrappers import Request

from api.services.auth import password as password_login
from api.services.auth import users

_MISSING = object()


class TestPasswordLogin(FrappeTestCase):
	"""Use native password hashes, restriction checks, OTPs and site Redis state."""

	def setUp(self):
		super().setUp()
		self.suffix = secrets.token_hex(8)
		self.user = f"password-login-{self.suffix}@example.com"
		self.role = f"Password Login {self.suffix}"
		self.password = f"  Native-{self.suffix}-<password>  "
		self.ip = f"198.18.{int(self.suffix[:2], 16)}.{int(self.suffix[2:4], 16)}"
		self.challenges = set()
		self.original_local = {
			name: getattr(frappe.local, name, _MISSING)
			for name in (
				"session",
				"session_obj",
				"form_dict",
				"response",
				"login_manager",
				"cookie_manager",
				"request",
				"request_ip",
			)
		}
		self.addCleanup(self._restore_local)
		self.addCleanup(self._cleanup_records)
		frappe.local.session = frappe._dict(user="Administrator", sid="Guest")
		frappe.get_doc(doctype="Role", role_name=self.role, desk_access=1, two_factor_auth=1).insert(
			ignore_permissions=True
		)
		user = frappe.get_doc(
			doctype="User",
			email=self.user,
			first_name="Password",
			last_name="Login",
			enabled=1,
			send_welcome_email=0,
			roles=[{"role": self.role}],
			username=f"login_{self.suffix}",
		)
		user.flags.no_welcome_mail = True
		user.insert(ignore_permissions=True)
		update_password(self.user, self.password)
		frappe.db.commit()

		self.settings = {
			"disable_user_pass_login": 0,
			"enable_two_factor_auth": 0,
			"two_factor_method": "OTP App",
			"bypass_2fa_for_retricted_ip_users": 0,
			"bypass_restrict_ip_check_if_2fa_enabled": 0,
			"force_user_to_reset_password": 0,
			"allow_login_using_user_name": 0,
			"allow_login_using_mobile_number": 0,
		}
		stack = ExitStack()
		self.addCleanup(stack.close)
		get_setting = frappe.get_system_settings
		stack.enter_context(
			patch.object(
				frappe,
				"get_system_settings",
				side_effect=lambda key=None: self.settings[key] if key in self.settings else get_setting(key),
			)
		)
		get_single_value = frappe.db.get_single_value

		def configured_single_value(doctype, fieldname, *args, **kwargs):
			if doctype == "System Settings" and fieldname in self.settings:
				return self.settings[fieldname]
			return get_single_value(doctype, fieldname, *args, **kwargs)

		stack.enter_context(patch.object(frappe.db, "get_single_value", side_effect=configured_single_value))
		get_doc = frappe.get_doc

		def configured_doc(*args, **kwargs):
			doc = get_doc(*args, **kwargs)
			if args == ("System Settings",) and not kwargs:
				# Change only this freshly loaded object, never site settings.
				doc.allow_consecutive_login_attempts = 2
				doc.allow_login_after_fail = 300
			return doc

		stack.enter_context(patch.object(frappe, "get_doc", side_effect=configured_doc))
		self.session = frappe._dict(user="Guest", sid="Guest")
		self.form = frappe._dict(cmd="api.auth.login", untouched="  original  ")
		self.response = frappe._dict(message="original response")
		self.manager = object()
		self.cookies = CookieManager()
		frappe.local.session = self.session
		frappe.local.form_dict = self.form
		frappe.local.response = self.response
		frappe.local.login_manager = self.manager
		frappe.local.cookie_manager = self.cookies
		frappe.local.request = Request.from_values(path="/api/method/api.auth.login", method="POST")
		frappe.local.request_ip = self.ip
		self.sessions_before = self._sessions()
		self.refresh_before = frappe.db.count("API Refresh Token", {"user": self.user})
		self.addCleanup(self._assert_auth_boundary)

	def _restore_local(self):
		for name, value in self.original_local.items():
			if value is _MISSING:
				if hasattr(frappe.local, name):
					delattr(frappe.local, name)
			else:
				setattr(frappe.local, name, value)

	def _cleanup_records(self):
		# Native failed-login logging commits; delete only this test's own rows.
		frappe.db.rollback()
		frappe.local.login_manager = None
		frappe.local.session = frappe._dict(user="Administrator", sid="Guest")
		for tmp_id in self.challenges:
			frappe.cache.delete_value(
				[tmp_id + suffix for suffix in ("_usr", "_pwd", "_otp_secret", "_token")]
			)
		for key in (self.user, self.ip):
			LoginAttemptTracker(key).add_success_attempt()
		for suffix in ("_otpsecret", "_otplogin"):
			frappe.defaults.clear_default(self.user + suffix, parent="__2fa")
		frappe.db.delete("Activity Log", {"user": self.user})
		if frappe.db.exists("User", self.user):
			frappe.delete_doc("User", self.user, ignore_permissions=True, force=True)
		if frappe.db.exists("Role", self.role):
			frappe.delete_doc("Role", self.role, ignore_permissions=True, force=True)
		frappe.db.commit()

	def _sessions(self):
		return frappe.db.sql("SELECT sid FROM `tabSessions` WHERE user = %s ORDER BY sid", self.user)

	def _assert_auth_boundary(self):
		self.assertIs(frappe.local.session, self.session)
		self.assertEqual(self.session, {"user": "Guest", "sid": "Guest"})
		self.assertIs(frappe.local.form_dict, self.form)
		self.assertEqual(self.form, {"cmd": "api.auth.login", "untouched": "  original  "})
		self.assertIs(frappe.local.response, self.response)
		self.assertEqual(self.response, {"message": "original response"})
		self.assertIs(frappe.local.login_manager, self.manager)
		self.assertEqual(self.cookies.cookies, {})
		self.assertEqual(self.cookies.to_delete, [])
		self.assertEqual(self._sessions(), self.sessions_before)
		self.assertEqual(frappe.db.count("API Refresh Token", {"user": self.user}), self.refresh_before)

	def _login(self, **kwargs):
		return password_login.authenticate_login(self.user, self.password, **kwargs)

	def _challenge(self):
		self.settings["enable_two_factor_auth"] = 1
		# A real established native OTP setup avoids sending setup email.
		set_default(self.user + "_otplogin", 1)
		secret = get_otpsecret_for_(self.user)
		result = self._login()
		self.assertEqual(set(result), {"mfa_required", "tmp_id", "verification"})
		self.assertIs(result["mfa_required"], True)
		self.assertEqual(result["verification"], {"method": "OTP App", "setup": True})
		self.assertNotIn(secret, repr(result))
		self.assertNotIn(self.password, repr(result))
		self.assertNotIn(self.user, repr(result))
		self.challenges.add(result["tmp_id"])
		return result["tmp_id"], secret

	def _assert_consumed(self, tmp_id):
		for suffix in ("_usr", "_pwd", "_otp_secret", "_token"):
			self.assertIsNone(frappe.cache.get(frappe.cache.make_key(tmp_id + suffix)))

	def test_guest_rpc_preserves_html_password_before_native_authentication(self):
		from api.api.auth import login

		original_form = frappe.local.form_dict
		try:
			frappe.local.form_dict = frappe._dict(usr=self.user, pwd=self.password)
			frappe.is_whitelisted(login)
			self.assertEqual(
				password_login.authenticate_login(frappe.form_dict.usr, frappe.form_dict.pwd),
				self.user,
			)
		finally:
			frappe.local.form_dict = original_form

	def test_success_returns_canonical_identity_without_tokens_or_sid(self):
		self.settings["allow_login_using_user_name"] = 1
		self.assertEqual(password_login.authenticate_login(f"login_{self.suffix}", self.password), self.user)
		self.assertEqual(self._login(), self.user)

	def test_wrong_password_updates_native_user_and_ip_failure_state(self):
		with self.assertRaises(frappe.AuthenticationError):
			password_login.authenticate_login(self.user, self.password.strip())
		self.assertEqual(LoginAttemptTracker(self.user).login_failed_count, 1)
		self.assertEqual(LoginAttemptTracker(self.ip).login_failed_count, 1)
		self.assertEqual(self._login(), self.user)
		self.assertIsNone(LoginAttemptTracker(self.user).login_failed_count)
		self.assertIsNone(LoginAttemptTracker(self.ip).login_failed_count)

	def test_native_lockout_blocks_correct_password_for_user_and_ip(self):
		for key in (self.user, self.ip):
			with self.subTest(key=key):
				tracker = LoginAttemptTracker(key)
				for _attempt in range(3):
					tracker.add_failure_attempt()
				with self.assertRaises(frappe.SecurityException):
					self._login()
				tracker.add_success_attempt()
		self.assertEqual(self._login(), self.user)

	def test_disabled_password_login_and_disabled_user_are_rejected(self):
		self.settings["disable_user_pass_login"] = 1
		with self.assertRaisesRegex(frappe.AuthenticationError, "not allowed"):
			self._login()
		self.settings["disable_user_pass_login"] = 0
		frappe.db.set_value("User", self.user, "enabled", 0)
		frappe.clear_cache(user=self.user)
		with self.assertRaises(frappe.AuthenticationError):
			self._login()

	def test_native_ip_allowlist_and_login_hours_are_enforced(self):
		frappe.db.set_value("User", self.user, "restrict_ip", "203.0.113.")
		frappe.clear_cache(user=self.user)
		with self.assertRaisesRegex(frappe.AuthenticationError, "IP Address"):
			self._login()
		frappe.db.set_value(
			"User", self.user, {"restrict_ip": self.ip, "login_after": 10, "login_before": 18}
		)
		frappe.clear_cache(user=self.user)
		for hour in (9, 18):
			with (
				self.subTest(hour=hour),
				patch("frappe.utils.now_datetime", return_value=datetime(2030, 1, 1, hour)),
			):
				with self.assertRaisesRegex(frappe.AuthenticationError, "not allowed at this time"):
					self._login()
		with patch("frappe.utils.now_datetime", return_value=datetime(2030, 1, 1, 12)):
			self.assertEqual(self._login(), self.user)

	def test_password_expiry_preserves_native_reset_without_leaking_key(self):
		self.settings["force_user_to_reset_password"] = 1
		frappe.db.set_value("User", self.user, "last_password_reset_date", add_days(today(), -2))
		with patch("frappe.core.doctype.user.user.User.password_reset_mail") as mail:
			with self.assertRaisesRegex(frappe.AuthenticationError, "Password reset required") as raised:
				self._login()
		key = frappe.db.get_value("User", self.user, "reset_password_key")
		self.assertTrue(key)
		self.assertNotIn(key, str(raised.exception))
		self.assertNotIn(key, repr(frappe.response))
		self.assertNotIn("redirect_to", frappe.response)
		self.assertTrue(mail.called, "The native password-reset notification must still happen")

	def test_native_before_login_and_on_login_hooks_can_reject(self):
		get_hooks = frappe.get_hooks
		for event in ("before_login", "on_login"):

			def hooks(*args, **kwargs):
				result = get_hooks(*args, **kwargs)
				if not args and not kwargs:
					return frappe._dict(result) | {event: ["api.tests.test_password_login.reject_login"]}
				return result

			with self.subTest(event=event), patch.object(frappe, "get_hooks", side_effect=hooks):
				with self.assertRaisesRegex(frappe.AuthenticationError, "Rejected by login hook"):
					self._login()

	def test_user_disabled_by_native_on_login_hook_cannot_authenticate(self):
		get_hooks = frappe.get_hooks

		def hooks(*args, **kwargs):
			result = get_hooks(*args, **kwargs)
			if not args and not kwargs:
				return frappe._dict(result) | {
					"on_login": ["api.tests.test_password_login.disable_user_during_login"]
				}
			return result

		with patch.object(frappe, "get_hooks", side_effect=hooks):
			with self.assertRaisesRegex(frappe.AuthenticationError, "disabled"):
				self._login()

	def test_success_preserves_preexisting_caller_identity_and_sid(self):
		self.session.update(user="Administrator", sid="preexisting-caller-sid")
		try:
			self.assertEqual(self._login(), self.user)
			self.assertIs(frappe.local.session, self.session)
			self.assertEqual(self.session, {"user": "Administrator", "sid": "preexisting-caller-sid"})
			self.assertEqual(self.cookies.cookies, {})
			self.assertEqual(self.cookies.to_delete, [])
		finally:
			self.session.update(user="Guest", sid="Guest")

	def test_mfa_pending_completion_and_replay(self):
		tmp_id, secret = self._challenge()
		self._assert_auth_boundary()
		otp = pyotp.TOTP(secret).now()
		self.assertEqual(password_login.authenticate_login(None, None, otp, tmp_id), self.user)
		self._assert_consumed(tmp_id)
		with self.assertRaises(frappe.AuthenticationError):
			# Supplying a good password must not revive a consumed challenge.
			password_login.authenticate_login(self.user, self.password, otp, tmp_id)

	def test_mfa_wrong_code_updates_native_failure_counter_but_allows_retry(self):
		tmp_id, secret = self._challenge()
		totp = pyotp.TOTP(secret)
		wrong = next(f"{value:06d}" for value in range(10) if not totp.verify(f"{value:06d}"))
		with self.assertRaises(frappe.AuthenticationError):
			password_login.authenticate_login(None, None, wrong, tmp_id)
		self.assertEqual(LoginAttemptTracker(self.user).login_failed_count, 1)
		self.assertEqual(password_login.authenticate_login(None, None, totp.now(), tmp_id), self.user)
		self._assert_consumed(tmp_id)

	def test_pending_mfa_fails_closed_if_two_factor_is_disabled(self):
		tmp_id, secret = self._challenge()
		self.settings["enable_two_factor_auth"] = 0
		with self.assertRaises(frappe.AuthenticationError):
			password_login.authenticate_login(None, None, pyotp.TOTP(secret).now(), tmp_id)
		self.settings["enable_two_factor_auth"] = 1
		self.assertEqual(
			password_login.authenticate_login(None, None, pyotp.TOTP(secret).now(), tmp_id), self.user
		)
		self._assert_consumed(tmp_id)

	def test_mfa_missing_or_expired_native_cache_never_falls_back_to_password(self):
		for suffix in ("_usr", "_pwd", "_otp_secret"):
			with self.subTest(missing=suffix):
				tmp_id, secret = self._challenge()
				# Expire the actual native Redis key, without waiting on wall time.
				frappe.cache.pexpire(frappe.cache.make_key(tmp_id + suffix), 0)
				with self.assertRaisesRegex(frappe.AuthenticationError, "expired"):
					password_login.authenticate_login(
						self.user, self.password, pyotp.TOTP(secret).now(), tmp_id
					)
		with self.assertRaises(frappe.AuthenticationError):
			password_login.authenticate_login(self.user, self.password, "123456", "unknown-challenge")

	def test_native_mfa_expiry_during_verification_becomes_authentication_error(self):
		from frappe.auth import confirm_otp_token

		tmp_id, secret = self._challenge()

		def expire_before_verification(manager):
			frappe.cache.pexpire(frappe.cache.make_key(tmp_id + "_otp_secret"), 0)
			return confirm_otp_token(manager)

		with patch("frappe.auth.confirm_otp_token", side_effect=expire_before_verification):
			with self.assertRaisesRegex(frappe.AuthenticationError, "expired"):
				password_login.authenticate_login(None, None, pyotp.TOTP(secret).now(), tmp_id)

	def test_mfa_requires_both_otp_and_challenge_even_with_valid_password(self):
		for otp, tmp_id in (("123456", None), (None, "challenge"), ("", "challenge")):
			with self.subTest(otp=otp, tmp_id=tmp_id), self.assertRaises(frappe.AuthenticationError):
				password_login.authenticate_login(self.user, self.password, otp, tmp_id)

	def test_native_email_and_sms_hotp_challenges_complete_without_secret_leaks(self):
		self.settings["enable_two_factor_auth"] = 1
		frappe.db.set_value("User", self.user, "mobile_no", "+12025550123")
		secret = get_otpsecret_for_(self.user)
		get_doc = frappe.get_doc

		def delivery_settings(*args, **kwargs):
			if args == ("SMS Settings", "SMS Settings"):
				return frappe._dict(
					sms_gateway_url="https://sms.invalid/send",
					message_parameter="message",
					receiver_parameter="to",
					parameters=[],
					use_post=1,
				)
			return get_doc(*args, **kwargs)

		for method in ("Email", "SMS"):
			self.settings["two_factor_method"] = method
			# Only outbound transports are replaced; native challenge generation,
			# metadata, cached credentials and HOTP verification remain real.
			with (
				self.subTest(method=method),
				patch.object(frappe, "get_doc", side_effect=delivery_settings),
				patch.object(frappe, "sendmail", return_value=True),
				patch("frappe.twofactor.enqueue"),
			):
				result = self._login()
			tmp_id = result["tmp_id"]
			self.challenges.add(tmp_id)
			self.assertEqual(result["verification"]["method"], method)
			self.assertTrue(result["verification"]["token_delivery"])
			token = frappe.cache.get_value(tmp_id + "_token", expires=True)
			self.assertIsNotNone(token)
			self.assertNotIn(secret, repr(result))
			self.assertNotIn(self.password, repr(result))
			otp = pyotp.HOTP(secret).at(int(token))
			self.assertEqual(password_login.authenticate_login(None, None, otp, tmp_id), self.user)
			self._assert_consumed(tmp_id)

	def test_mfa_continuation_cannot_rebind_cached_identity(self):
		tmp_id, secret = self._challenge()
		self.assertEqual(
			password_login.authenticate_login(
				"Administrator", "not-the-password", pyotp.TOTP(secret).now(), tmp_id
			),
			self.user,
		)
		self._assert_consumed(tmp_id)

	def test_verified_mfa_is_consumed_when_password_reset_is_required(self):
		tmp_id, secret = self._challenge()
		self.settings["force_user_to_reset_password"] = 1
		frappe.db.set_value("User", self.user, "last_password_reset_date", add_days(today(), -2))
		with patch("frappe.core.doctype.user.user.User.password_reset_mail"):
			with self.assertRaisesRegex(frappe.AuthenticationError, "Password reset required"):
				password_login.authenticate_login(None, None, pyotp.TOTP(secret).now(), tmp_id)
		self._assert_consumed(tmp_id)
		self.assertTrue(frappe.db.get_value("User", self.user, "reset_password_key"))

	def test_expired_password_does_not_issue_reset_before_mfa(self):
		self.settings["force_user_to_reset_password"] = 1
		frappe.db.set_value("User", self.user, "last_password_reset_date", add_days(today(), -2))
		with patch("frappe.core.doctype.user.user.User.password_reset_mail") as mail:
			tmp_id, secret = self._challenge()
			totp = pyotp.TOTP(secret)
			wrong = next(f"{value:06d}" for value in range(10) if not totp.verify(f"{value:06d}"))
			with self.assertRaises(frappe.AuthenticationError):
				password_login.authenticate_login(None, None, wrong, tmp_id)
			self.assertFalse(frappe.db.get_value("User", self.user, "reset_password_key"))
			mail.assert_not_called()
			with self.assertRaisesRegex(frappe.AuthenticationError, "Password reset required"):
				password_login.authenticate_login(None, None, totp.now(), tmp_id)
			self.assertTrue(frappe.db.get_value("User", self.user, "reset_password_key"))
			mail.assert_called_once()
		self._assert_consumed(tmp_id)

	def test_concurrent_mfa_completion_has_only_one_consumer(self):
		tmp_id, secret = self._challenge()
		frappe.db.commit()
		barrier = Barrier(3)
		with ThreadPoolExecutor(max_workers=2) as executor:
			with frappe.cache.lock(frappe.cache.make_key(f"api:password-login:{tmp_id}"), timeout=20):
				futures = [
					executor.submit(
						complete_challenge,
						frappe.local.site,
						frappe.local.sites_path,
						pyotp.TOTP(secret).now(),
						tmp_id,
						self.ip,
						barrier,
					)
					for _consumer in range(2)
				]
				barrier.wait(timeout=20)
				done, _pending = wait(futures, timeout=0.1)
				self.assertFalse(done, "A challenge consumer bypassed the held native Redis lock")
			results = [future.result(timeout=20) for future in futures]
		self.assertCountEqual(results, ["rejected", self.user])
		self._assert_consumed(tmp_id)

	def test_safe_profile_excludes_real_api_credentials_and_private_fields(self):
		api_key = secrets.token_hex(16)
		api_secret = secrets.token_hex(24)
		frappe.db.set_value(
			"User", self.user, {"api_key": api_key, "reset_password_key": "private-reset-key"}
		)
		set_encrypted_password("User", self.user, api_secret, "api_secret")
		profile = users.get_user_profile(self.user)
		self.assertEqual(
			set(profile),
			{
				"name",
				"email",
				"first_name",
				"last_name",
				"full_name",
				"user_image",
				"language",
				"time_zone",
				"user_type",
				"roles",
			},
		)
		self.assertEqual(profile["name"], self.user)
		self.assertEqual(profile["email"], self.user)
		self.assertEqual(profile["first_name"], "Password")
		self.assertIn(self.role, profile["roles"])
		for secret in (api_key, api_secret, self.password, "private-reset-key"):
			self.assertNotIn(secret, repr(profile))
		with self.assertRaises(frappe.AuthenticationError):
			users.get_user_profile(f"missing-{self.suffix}@example.com")


def reject_login(login_manager):
	frappe.throw("Rejected by login hook", frappe.AuthenticationError)


def disable_user_during_login(login_manager):
	frappe.db.set_value("User", login_manager.user, "enabled", 0)


def complete_challenge(site, sites_path, otp, tmp_id, ip, barrier):
	"""Competing consumers use independent native request and database contexts."""
	frappe.init(site=site, sites_path=sites_path)
	try:
		frappe.connect()
		frappe.local.session = frappe._dict(user="Guest", sid="Guest")
		frappe.local.form_dict = frappe._dict()
		frappe.local.response = frappe._dict()
		frappe.local.request = Request.from_values(path="/api/method/api.auth.login", method="POST")
		frappe.local.request_ip = ip
		frappe.local.cookie_manager = CookieManager()
		barrier.wait(timeout=20)
		try:
			return password_login.authenticate_login(None, None, otp, tmp_id)
		except frappe.AuthenticationError:
			return "rejected"
	finally:
		frappe.destroy()
