import time
from unittest import TestCase
from unittest.mock import patch

import frappe
import jwt

from api.services.auth import jwt as auth


class TestJWTAuthentication(TestCase):
	def setUp(self):
		self.settings = {"secret": "s" * 48, "issuer": "test-site", "audience": "api", "access_ttl": 900}
		self.config = patch.object(auth, "get_jwt_settings", return_value=self.settings)
		self.config.start()
		self.addCleanup(self.config.stop)

	def validate_token(self, token):
		with (
			patch.object(frappe, "get_request_header", return_value=f"Bearer {token}"),
			patch.object(frappe.db, "exists", return_value=False),
			patch.object(auth, "active_user", return_value=True),
			patch.object(frappe, "set_user") as set_user,
		):
			auth.validate()
			return set_user.call_args.args[0]

	def test_issued_token_authenticates_subject(self):
		token = auth.access_token("Administrator")["access_token"]
		self.assertEqual(self.validate_token(token), "Administrator")

	def test_jwt_identity_change_preserves_parsed_endpoint_payload(self):
		from api.api.core.exceptions import UnprocessableEntityException
		from api.api.core.request import get_request_data
		from api.api.customer.pipes import validate_create_customer

		original_user = frappe.session.user
		original_form = frappe.local.form_dict
		payload = frappe._dict(customer_name="Bruno Review", email="invalid-email")
		token = auth.access_token("Administrator")["access_token"]
		try:
			frappe.local.form_dict = payload
			with (
				patch.object(frappe, "get_request_header", return_value=f"Bearer {token}"),
				patch.object(frappe.db, "exists", return_value=False),
				patch.object(auth, "active_user", return_value=True),
			):
				auth.validate()
			with self.assertRaises(UnprocessableEntityException) as error:
				validate_create_customer(get_request_data())
			self.assertEqual(error.exception.code, "INVALID_EMAIL")
			self.assertEqual(frappe.form_dict.customer_name, "Bruno Review")
		finally:
			frappe.set_user(original_user)
			frappe.local.form_dict = original_form

	def test_invalid_claims_and_signature_are_rejected(self):
		now = int(time.time())
		claims = {
			"sub": "Administrator",
			"iss": "test-site",
			"aud": "api",
			"iat": now,
			"nbf": now,
			"exp": now + 900,
			"jti": "test",
			"typ": "access",
		}
		for change in (
			{"exp": now - 60},
			{"nbf": now + 60},
			{"aud": "other"},
			{"iss": "other-site"},
			{"typ": "refresh"},
		):
			with self.subTest(change=change), self.assertRaises(frappe.AuthenticationError):
				self.validate_token(jwt.encode(claims | change, self.settings["secret"], algorithm="HS256"))
		with self.assertRaises(frappe.AuthenticationError):
			self.validate_token(jwt.encode(claims, "wrong" * 10, algorithm="HS256"))

	def test_disabled_user_is_rejected(self):
		token = auth.access_token("Administrator")["access_token"]
		with (
			patch.object(frappe, "get_request_header", return_value=f"Bearer {token}"),
			patch.object(frappe.db, "exists", return_value=False),
			patch.object(auth, "active_user", return_value=False),
			self.assertRaises(frappe.AuthenticationError),
		):
			auth.validate()

	def test_oauth_bearer_is_not_reinterpreted(self):
		with (
			patch.object(frappe, "get_request_header", return_value="Bearer existing-oauth"),
			patch.object(frappe.db, "exists", return_value=True),
			patch.object(auth, "get_jwt_settings", side_effect=AssertionError("JWT settings consulted")),
		):
			auth.validate()
