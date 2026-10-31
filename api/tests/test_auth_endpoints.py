from contextlib import ExitStack
from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from api.api import auth
from api.api.auth_dto import IssueTokenDTO, RefreshTokenDTO, RevokeTokenDTO


class TestAuthEndpoints(TestCase):
	def setUp(self):
		stack = self.enterContext(ExitStack())
		self.settings = {
			"enable_api": 1,
			"allow_guest_access": 0,
			"enable_logging": 1,
			"log_request_payload": 1,
			"log_response_payload": 1,
			"log_headers": 1,
			"mask_sensitive_data": 0,
		}
		stack.enter_context(patch("api.api.core.policies.get_settings", return_value=self.settings))
		stack.enter_context(patch.object(frappe, "session", frappe._dict(user="Administrator")))
		stack.enter_context(patch.object(frappe, "form_dict", {}))
		missing = object()
		for name, value in {
			"request": None,
			"response": frappe._dict(http_status_code=200),
			"response_headers": {},
			"api_auth_method": None,
		}.items():
			original = getattr(frappe.local, name, missing)
			if original is missing:
				stack.callback(delattr, frappe.local, name)
			else:
				stack.callback(setattr, frappe.local, name, original)
			setattr(frappe.local, name, value)
		self.active_user = stack.enter_context(
			patch("api.services.auth.users.active_user", return_value=True)
		)
		self.jwt_settings = stack.enter_context(
			patch("api.services.auth.settings.get_jwt_settings", return_value={})
		)
		self.audit = stack.enter_context(patch.object(auth, "audit"))
		self.pipe_audit = stack.enter_context(patch("api.api.auth_pipes.audit"))
		self.logger = stack.enter_context(patch.object(frappe, "logger", return_value=MagicMock()))
		self.api_log = stack.enter_context(patch("api.api.core.logging.record_api_log"))
		self.log_settings = stack.enter_context(patch("api.api.core.logging._get_settings"))
		self.extract_context = stack.enter_context(patch("api.api.core.logging._extract_request_context"))
		self.serialize = stack.enter_context(patch("api.api.core.logging._safe_serialize"))
		self.normalize = stack.enter_context(patch("api.api.core.decorators.run_default_pipes"))

	def tearDown(self):
		self.api_log.assert_not_called()
		self.log_settings.assert_not_called()
		self.extract_context.assert_not_called()
		self.serialize.assert_not_called()
		self.normalize.assert_not_called()

	def _payload(self, **values):
		return patch.object(frappe, "form_dict", values)

	def _assert_no_store(self):
		self.assertEqual(frappe.local.response_headers["Cache-Control"], "no-store")
		self.assertEqual(frappe.local.response_headers["Pragma"], "no-cache")

	def test_issue_preserves_client_id_and_response_secrets(self):
		client_id = "  opaque-client <tag>  "
		credentials = {"access_token": "  access-secret  ", "token_type": "Bearer", "expires_in": 900}
		with (
			self._payload(client_id=client_id, cmd="ignored", extra="ignored"),
			patch.object(auth, "access_token", return_value=credentials) as access,
			patch.object(auth, "create_session", return_value="  refresh-secret  ") as create,
		):
			result = auth.issue()
		access.assert_called_once_with("Administrator")
		create.assert_called_once_with("Administrator", client_id)
		self.assertIs(result, credentials)
		self.assertEqual(result["access_token"], "  access-secret  ")
		self.assertEqual(result["refresh_token"], "  refresh-secret  ")
		self.audit.assert_called_once_with("token_issued", user="Administrator")
		self._assert_no_store()

	def test_issue_invalid_client_id_fails_before_dto_and_handler(self):
		for value in (123, False, [], {}, "x" * 141):
			with (
				self.subTest(input_type=type(value).__name__),
				self._payload(client_id=value),
				patch.object(IssueTokenDTO, "__init__", autospec=True) as build,
				patch.object(auth, "access_token") as access,
				patch.object(auth, "create_session") as create,
				self.assertRaises(frappe.ValidationError),
			):
				auth.issue()
			build.assert_not_called()
			access.assert_not_called()
			create.assert_not_called()
			self._assert_no_store()

	def test_native_policy_rejects_guest_inactive_and_jwt_before_pipe_or_handler(self):
		for user, active, method in (
			("Guest", False, None),
			("disabled@example.com", False, None),
			("Administrator", True, "jwt"),
		):
			frappe.local.api_auth_method = method
			with (
				self.subTest(user=user, method=method),
				patch.object(frappe, "session", frappe._dict(user=user)),
				patch("api.services.auth.users.active_user", return_value=active),
				self._payload(client_id=[]),
				patch.object(auth, "access_token") as access,
				self.assertRaises(frappe.AuthenticationError),
			):
				auth.issue()
			access.assert_not_called()
			self._assert_no_store()

	def test_refresh_preserves_opaque_credential_for_guest(self):
		token = "  opaque <refresh> credential  "
		with (
			patch.object(frappe, "session", frappe._dict(user="Guest")),
			self._payload(refresh_token=token, unknown="ignored"),
			patch.object(auth, "rotate", return_value=("Administrator", "  replacement  ")) as rotate,
			patch.object(auth, "access_token", return_value={"access_token": "  access  "}),
		):
			result = auth.refresh()
		rotate.assert_called_once_with(token)
		self.jwt_settings.assert_called_once_with()
		self.assertEqual(result, {"access_token": "  access  ", "refresh_token": "  replacement  "})
		self.audit.assert_called_once_with("token_refreshed", user="Administrator")
		self._assert_no_store()

	def test_refresh_missing_or_malformed_credential_is_native_auth_failure_before_dto(self):
		payloads = [{}, *({"refresh_token": value} for value in (None, 123, False, [], {}, "", "x" * 513))]
		for payload in payloads:
			with (
				self.subTest(payload_type=type(payload.get("refresh_token")).__name__),
				self._payload(**payload),
				patch.object(RefreshTokenDTO, "__init__", autospec=True) as build,
				patch.object(auth, "rotate") as rotate,
				self.assertRaises(frappe.AuthenticationError),
			):
				auth.refresh()
			build.assert_not_called()
			rotate.assert_not_called()
			self.jwt_settings.assert_not_called()
			self.pipe_audit.assert_called_with("refresh_rejected")
			self._assert_no_store()

	def test_refresh_resolves_signing_configuration_before_consuming_token(self):
		with (
			self._payload(refresh_token="opaque"),
			patch(
				"api.services.auth.settings.get_jwt_settings",
				side_effect=frappe.ValidationError("JWT configuration"),
			),
			patch.object(auth, "rotate") as rotate,
			self.assertRaises(frappe.ValidationError),
		):
			auth.refresh()
		rotate.assert_not_called()
		self._assert_no_store()

	def test_refresh_rejection_preserves_native_exception_and_audit(self):
		error = frappe.AuthenticationError("Invalid or expired refresh token")
		with (
			self._payload(refresh_token="opaque"),
			patch.object(auth, "rotate", side_effect=error),
			self.assertRaises(frappe.AuthenticationError) as raised,
		):
			auth.refresh()
		self.assertIs(raised.exception, error)
		self.audit.assert_called_once_with("refresh_rejected")
		self._assert_no_store()

	def test_revoke_preserves_credential_for_guest(self):
		token = "  opaque <refresh> credential  "
		with (
			patch.object(frappe, "session", frappe._dict(user="Guest")),
			self._payload(refresh_token=token, unknown="ignored"),
			patch.object(auth, "revoke_session") as revoke,
		):
			result = auth.revoke()
		revoke.assert_called_once_with(token)
		self.assertEqual(result, {"revoked": True})
		self.audit.assert_called_once_with("token_revoked")
		self._assert_no_store()

	def test_revoke_missing_or_malformed_credential_is_native_validation_before_dto(self):
		payloads = [{}, *({"refresh_token": value} for value in (None, 123, False, [], {}, "", "x" * 513))]
		for payload in payloads:
			with (
				self.subTest(payload_type=type(payload.get("refresh_token")).__name__),
				self._payload(**payload),
				patch.object(RevokeTokenDTO, "__init__", autospec=True) as build,
				patch.object(auth, "revoke_session") as revoke,
				self.assertRaises(frappe.ValidationError),
			):
				auth.revoke()
			build.assert_not_called()
			revoke.assert_not_called()
			self._assert_no_store()

	def test_refresh_and_revoke_keep_broad_bounded_string_compatibility(self):
		for token in (" ", "x" * 512, "a_-" * 21 + "a"):
			with (
				self.subTest(length=len(token)),
				self._payload(refresh_token=token),
				patch.object(auth, "rotate", return_value=("Administrator", "replacement")) as rotate,
				patch.object(auth, "access_token", return_value={}),
				patch.object(auth, "revoke_session") as revoke,
			):
				auth.refresh()
				auth.revoke()
			rotate.assert_called_once_with(token)
			revoke.assert_called_once_with(token)

	def test_login_mfa_challenge_does_not_issue_tokens_or_profile(self):
		challenge = {"mfa_required": True, "tmp_id": "pending-id", "verification": {"method": "OTP App"}}
		with (
			self._payload(usr="user@example.test", pwd="secret"),
			patch.object(auth, "authenticate_login", return_value=challenge),
			patch.object(auth, "get_user_profile") as profile,
			patch.object(auth, "access_token") as access,
			patch.object(auth, "create_session") as create,
		):
			result = auth.login()
		self.assertTrue(result["mfa_required"])
		self.assertNotIn("access_token", result)
		self.assertNotIn("refresh_token", result)
		self.assertNotIn("user", result)
		profile.assert_not_called()
		access.assert_not_called()
		create.assert_not_called()
		self._assert_no_store()

	def test_login_rejected_credentials_do_not_issue_tokens_or_profile(self):
		with (
			self._payload(usr="user@example.test", pwd="incorrect"),
			patch.object(auth, "authenticate_login", side_effect=frappe.AuthenticationError()),
			patch.object(auth, "get_user_profile") as profile,
			patch.object(auth, "access_token") as access,
			patch.object(auth, "create_session") as create,
			self.assertRaises(frappe.AuthenticationError),
		):
			auth.login()
		profile.assert_not_called()
		access.assert_not_called()
		create.assert_not_called()
		self._assert_no_store()

	def test_login_invalid_payload_is_rejected_before_authentication(self):
		for payload in (
			{},
			{"usr": "user@example.test"},
			{"usr": "user@example.test", "pwd": 123},
			{"usr": "user@example.test", "pwd": "x" * 513},
			{"otp": "123456"},
			{"tmp_id": "pending-id"},
			{"otp": [], "tmp_id": "pending-id"},
		):
			with (
				self.subTest(keys=list(payload)),
				self._payload(**payload),
				patch.object(auth, "authenticate_login") as authenticate,
				self.assertRaises(frappe.AuthenticationError),
			):
				auth.login()
			authenticate.assert_not_called()
			self._assert_no_store()

	def test_profile_error_does_not_leave_a_refresh_family(self):
		with (
			self._payload(usr="user@example.test", pwd="secret"),
			patch.object(auth, "authenticate_login", return_value="user@example.test"),
			patch.object(auth, "get_user_profile", side_effect=frappe.ValidationError("Profile unavailable")),
			patch.object(auth, "access_token") as access,
			patch.object(auth, "create_session") as create,
			self.assertRaises(frappe.ValidationError),
		):
			auth.login()
		access.assert_not_called()
		create.assert_not_called()
		self._assert_no_store()
