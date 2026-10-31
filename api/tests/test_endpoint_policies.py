from dataclasses import dataclass
from unittest import TestCase
from unittest.mock import patch

import frappe

from api.api.core.decorators import endpoint
from api.api.core.exceptions import ForbiddenException, ServiceUnavailableException
from api.api.core.logging import AUTH_METADATA_ONLY
from api.api.core.policies import api_enabled, authenticated, require_roles


@dataclass(slots=True)
class InputDTO:
	value: str


class TestEndpointPolicies(TestCase):
	def setUp(self):
		self.original_session = frappe.local.session
		frappe.local.session = frappe._dict(user="Guest")
		self.addCleanup(setattr, frappe.local, "session", self.original_session)
		self.settings = {"enable_api": 1, "allow_guest_access": 1}
		for patcher in (
			patch("api.api.core.policies.get_settings", return_value=self.settings),
			patch.object(frappe, "logger"),
		):
			patcher.start()
			self.addCleanup(patcher.stop)

	def build(self, **options):
		return endpoint(guest=True, telemetry=AUTH_METADATA_ONLY, **options)

	def test_default_policy_blocks_guest_but_explicit_policy_replaces_it(self):
		self.settings["allow_guest_access"] = 0

		@self.build()
		def default_endpoint():
			return {"accepted": True}

		@self.build(policies=(api_enabled,))
		def credential_endpoint():
			return {"accepted": True}

		with self.assertRaises(ForbiddenException) as error:
			default_endpoint()
		self.assertEqual(error.exception.code, "GUEST_ACCESS_DISABLED")
		self.assertEqual(credential_endpoint(), {"accepted": True})

	def test_explicit_empty_tuple_replaces_all_default_policies(self):
		self.settings.update(enable_api=0, allow_guest_access=0)

		@self.build(policies=())
		def unguarded():
			return "explicit bypass"

		self.assertEqual(unguarded(), "explicit bypass")

	def test_master_switch_runs_before_payload_validation(self):
		self.settings["enable_api"] = 0
		reached = []

		def pipe(data):
			reached.append("pipe")
			return data

		@self.build(policies=(api_enabled,), pipes=(pipe,), dto=InputDTO)
		def guarded(body):
			reached.append("handler")
			return body.value

		with self.assertRaises(ServiceUnavailableException) as error:
			guarded()
		self.assertEqual(error.exception.code, "API_DISABLED")
		self.assertEqual(reached, [])

	def test_policies_fail_fast_before_later_policy_pipe_and_handler(self):
		reached = []

		def deny(ctx):
			reached.append("deny")
			raise frappe.PermissionError("Denied by access policy")

		def later(ctx):
			reached.append("later")

		def pipe(data):
			reached.append("pipe")
			return data

		@self.build(policies=(deny, later), pipes=(pipe,))
		def guarded():
			reached.append("handler")

		with self.assertRaises(frappe.PermissionError):
			guarded()
		self.assertEqual(reached, ["deny"])

	def test_role_policy_distinguishes_missing_auth_and_missing_permission(self):
		@self.build(policies=(authenticated, require_roles("Sales User", "Sales Manager")))
		def guarded():
			return "authorized"

		with self.assertRaises(frappe.AuthenticationError):
			guarded()
		frappe.local.session.user = "sales@example.test"
		with patch.object(frappe, "get_roles", return_value=["Employee"]):
			with self.assertRaises(frappe.PermissionError):
				guarded()
		with patch.object(frappe, "get_roles", return_value=["Sales Manager"]):
			self.assertEqual(guarded(), "authorized")

	def test_pipes_transform_before_dto_and_ignore_unknown_fields(self):
		def uppercase(data):
			return data | {"value": data["value"].upper()}

		@self.build(policies=(), pipes=(uppercase,), dto=InputDTO)
		def accept(body):
			return body.value

		with patch.object(frappe, "form_dict", {"value": "  example  ", "unknown": "discard"}):
			self.assertEqual(accept(), "EXAMPLE")

	def test_normalization_can_be_removed_without_changing_pipe_or_dto_support(self):
		def preserve(data):
			if data["value"] != "  exact credential  ":
				raise frappe.AuthenticationError("Credential changed")
			return data

		@self.build(policies=(), normalize=False, pipes=(preserve,), dto=InputDTO)
		def accept(body):
			return body.value

		with patch.object(frappe, "form_dict", {"value": "  exact credential  "}):
			self.assertEqual(accept(), "  exact credential  ")
