from contextlib import ExitStack
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

import frappe

from api.api import auth


class TestIssueRateLimit(TestCase):
	def setUp(self):
		stack = ExitStack()
		self.addCleanup(stack.close)
		self.users = [f"rate-{uuid4().hex}@example.com" for _ in range(2)]
		self.keys = [frappe.cache.make_key(f"rl:api.api.auth.issue:{user}") for user in self.users]
		self.addCleanup(frappe.cache.delete, *self.keys)
		self.session = frappe._dict(user=self.users[0])
		stack.enter_context(patch.object(frappe, "session", self.session))
		stack.enter_context(patch.object(frappe, "form_dict", {"cmd": "spoofed", "user": self.users[1]}))
		stack.enter_context(
			patch.object(frappe.local, "request", SimpleNamespace(method="POST"), create=True)
		)
		stack.enter_context(patch.object(frappe.local, "response_headers", {}, create=True))
		stack.enter_context(patch.object(frappe.local, "api_auth_method", None, create=True))
		stack.enter_context(patch("api.api.core.policies.get_settings", return_value={"enable_api": 1}))
		stack.enter_context(patch("api.services.auth.users.active_user", return_value=True))
		stack.enter_context(patch.object(auth, "access_token", side_effect=lambda user: {"user": user}))
		stack.enter_context(patch.object(auth, "create_session", return_value="refresh"))
		stack.enter_context(patch.object(auth, "audit"))
		stack.enter_context(patch("api.api.core.logging._record_auth_metadata"))

	def test_user_boundaries_and_fixed_window_expiry(self):
		for _ in range(20):
			self.assertEqual(auth.issue()["user"], self.users[0])
		self.assertEqual(int(frappe.cache.get(self.keys[0])), 20)
		self.assertGreater(frappe.cache.ttl(self.keys[0]), 0)
		self.assertLessEqual(frappe.cache.ttl(self.keys[0]), 60)
		frappe.cache.pexpire(self.keys[0], 30000)
		with self.assertRaises(frappe.RateLimitExceededError):
			auth.issue()
		self.assertGreater(frappe.cache.pttl(self.keys[0]), 0)
		self.assertLessEqual(frappe.cache.pttl(self.keys[0]), 30000)

		self.session.user = self.users[1]
		for _ in range(20):
			self.assertEqual(auth.issue()["user"], self.users[1])
		with self.assertRaises(frappe.RateLimitExceededError):
			auth.issue()
		self.assertEqual(int(frappe.cache.get(self.keys[0])), 21)
		self.assertEqual(int(frappe.cache.get(self.keys[1])), 21)

		frappe.cache.pexpire(self.keys[0], 0)
		self.session.user = self.users[0]
		self.assertEqual(auth.issue()["user"], self.users[0])
		self.assertEqual(int(frappe.cache.get(self.keys[0])), 1)
		self.assertGreater(frappe.cache.ttl(self.keys[0]), 0)

	def test_no_request_bypasses_limiter(self):
		frappe.local.request = None
		for _ in range(21):
			self.assertEqual(auth.issue()["user"], self.users[0])
		self.assertIsNone(frappe.cache.get(self.keys[0]))

	def test_policy_rejection_does_not_consume_limit(self):
		self.session.user = "Guest"
		with (
			patch.object(frappe.cache, "eval", wraps=frappe.cache.eval) as evaluate,
			self.assertRaises(frappe.AuthenticationError),
		):
			auth.issue()
		evaluate.assert_not_called()
