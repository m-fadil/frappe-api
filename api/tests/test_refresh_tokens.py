from __future__ import annotations

import hashlib
import secrets
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timedelta
from threading import Barrier
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import get_datetime

from api.services.auth import refresh_tokens
from api.services.auth.settings import get_jwt_settings


class TestRefreshTokens(IntegrationTestCase):
	"""Exercise committed rows and independent competing database consumers."""

	def setUp(self):
		super().setUp()
		self.client_id = f"refresh-test-{secrets.token_hex(8)}"
		self.family_ids = set()
		self.addCleanup(self._cleanup_families)

	def _cleanup_families(self):
		# Service transactions deliberately outlive the test/request transaction.
		frappe.db.rollback()
		if self.family_ids:
			with refresh_tokens._transaction() as db:
				for family_id in self.family_ids:
					db.sql("DELETE FROM `tabAPI Refresh Token` WHERE family_id = %s", (family_id,))
			self.family_ids.clear()

	def _create(self, user="Administrator"):
		token = refresh_tokens.create_session(user, self.client_id)
		self.family_ids.add(self._record(token).family_id)
		return token

	def _record(self, token):
		with refresh_tokens._transaction() as db:
			rows = db.sql(
				"SELECT * FROM `tabAPI Refresh Token` WHERE token_hash = %s",
				(hashlib.sha256(token.encode()).hexdigest(),),
				as_dict=True,
			)
		self.assertEqual(len(rows), 1)
		return rows[0]

	def _rows(self, family_id):
		with refresh_tokens._transaction() as db:
			return db.sql(
				"SELECT * FROM `tabAPI Refresh Token` WHERE family_id = %s",
				(family_id,),
				as_dict=True,
			)

	def _compete(self, family_id, calls):
		barrier = Barrier(len(calls) + 1)
		site = frappe.local.site
		sites_path = frappe.local.sites_path
		with ThreadPoolExecutor(max_workers=len(calls)) as executor:
			with refresh_tokens._transaction() as db:
				# Hold the real family lock so both consumers contend for it.
				db.sql(
					"SELECT name FROM `tabAPI Refresh Token` WHERE name = %s FOR UPDATE",
					(family_id,),
				)
				futures = [
					executor.submit(_consume, site, sites_path, operation, token, barrier)
					for operation, token in calls
				]
				barrier.wait(timeout=20)
				done, _pending = wait(futures, timeout=0.25)
				self.assertFalse(done, "A consumer bypassed the held family lock")
			return [future.result(timeout=20) for future in futures]

	def test_stores_only_hash_and_uses_configured_absolute_ttl(self):
		now = datetime(2030, 1, 1)
		with patch.object(refresh_tokens, "now_datetime", return_value=now):
			token = self._create()
		record = self._record(token)
		self.assertGreaterEqual(len(token), 64)
		self.assertEqual(record.token_hash, hashlib.sha256(token.encode()).hexdigest())
		self.assertTrue(token not in repr(record), "Refresh plaintext must never be persisted")
		self.assertEqual(record.name, record.family_id)
		self.assertEqual(record.user, "Administrator")
		self.assertEqual(record.client_id, self.client_id)
		self.assertEqual(
			get_datetime(record.expires_at), now + timedelta(seconds=get_jwt_settings()["refresh_ttl"])
		)
		self.assertFalse(record.used_at)
		self.assertFalse(record.revoked_at)

	def test_rotation_keeps_used_rows_and_original_family_expiry(self):
		now = datetime(2030, 1, 1)
		with patch.object(refresh_tokens, "now_datetime", return_value=now):
			original = self._create()
		root = self._record(original)
		expires_at = get_datetime(root.expires_at)
		with patch.object(refresh_tokens, "now_datetime", return_value=now + (expires_at - now) / 2):
			user, replacement = refresh_tokens.rotate(original)
		old = self._record(original)
		new = self._record(replacement)
		self.assertEqual(user, "Administrator")
		self.assertTrue(original != replacement, "Rotation must issue a new opaque credential")
		self.assertTrue(old.used_at)
		self.assertEqual(old.replaced_by, new.name)
		self.assertEqual(new.family_id, old.family_id)
		self.assertEqual(new.client_id, self.client_id)
		self.assertEqual(get_datetime(new.expires_at), expires_at)
		self.assertEqual(len(self._rows(root.family_id)), 2)
		with patch.object(refresh_tokens, "now_datetime", return_value=expires_at):
			with self.assertRaises(frappe.AuthenticationError):
				refresh_tokens.rotate(replacement)
		self.assertFalse(self._record(replacement).used_at)
		self.assertEqual(len(self._rows(root.family_id)), 2)

	def test_replay_revokes_all_generations_and_survives_request_rollback(self):
		original = self._create()
		_user, middle = refresh_tokens.rotate(original)
		_user, current = refresh_tokens.rotate(middle)
		unrelated = self._create()
		unrelated_record = self._record(unrelated)
		# Discard the request snapshot created before the independent inserts.
		frappe.db.rollback()
		frappe.db.sql(
			"UPDATE `tabAPI Refresh Token` SET client_id = %s WHERE name = %s",
			("uncommitted-request-write", unrelated_record.name),
		)
		with self.assertRaises(frappe.AuthenticationError):
			refresh_tokens.rotate(original)
		frappe.db.rollback()
		self.assertEqual(self._record(unrelated).client_id, self.client_id)
		rows = self._rows(self._record(original).family_id)
		self.assertEqual(len(rows), 3)
		self.assertTrue(all(row.revoked_at for row in rows))
		with self.assertRaises(frappe.AuthenticationError):
			refresh_tokens.rotate(current)
		# Other independently issued families are not revoked by the replay.
		refresh_tokens.rotate(unrelated)

	def test_revoke_is_idempotent_and_rejects_every_descendant(self):
		original = self._create()
		_user, current = refresh_tokens.rotate(original)
		self.assertIsNone(refresh_tokens.revoke(original))
		self.assertIsNone(refresh_tokens.revoke(current))
		self.assertIsNone(refresh_tokens.revoke(secrets.token_urlsafe(48)))
		self.assertTrue(all(row.revoked_at for row in self._rows(self._record(original).family_id)))
		with self.assertRaises(frappe.AuthenticationError):
			refresh_tokens.rotate(current)

	def test_expired_family_cannot_rotate_and_can_be_logged_out(self):
		original = self._create()
		record = self._record(original)
		with patch.object(refresh_tokens, "now_datetime", return_value=get_datetime(record.expires_at)):
			with self.assertRaises(frappe.AuthenticationError):
				refresh_tokens.rotate(original)
			self.assertIsNone(refresh_tokens.revoke(original))
		self.assertEqual(len(self._rows(record.family_id)), 1)
		self.assertTrue(self._record(original).revoked_at)

	def test_invalid_inputs_do_not_create_sessions(self):
		for value in (None, 123, [], {}, "", "x" * 513):
			with self.subTest(input_type=type(value).__name__):
				with self.assertRaises(frappe.AuthenticationError):
					refresh_tokens.rotate(value)
				with self.assertRaises(frappe.ValidationError):
					refresh_tokens.revoke(value)
		with self.assertRaises(frappe.AuthenticationError):
			refresh_tokens.rotate(secrets.token_urlsafe(48))
		with self.assertRaises(frappe.AuthenticationError):
			refresh_tokens.create_session("Guest", self.client_id)

	def test_disabled_user_cannot_consume_a_persisted_refresh_token(self):
		user = f"{self.client_id}@example.com"
		frappe.get_doc(
			{
				"doctype": "User",
				"email": user,
				"first_name": "Refresh lifecycle test",
				"enabled": 1,
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()

		def remove_user():
			self._cleanup_families()
			frappe.delete_doc("User", user, force=True, ignore_permissions=True)
			frappe.db.commit()

		self.addCleanup(remove_user)
		token = self._create(user)
		frappe.db.set_value("User", user, "enabled", 0)
		frappe.db.commit()
		with self.assertRaises(frappe.AuthenticationError):
			refresh_tokens.rotate(token)
		self.assertFalse(self._record(token).used_at)
		self.assertEqual(len(self._rows(self._record(token).family_id)), 1)

	def test_failed_successor_insert_leaves_original_consumable(self):
		original = self._create()
		# Force a real unique-index violation, rather than mocking a DB result.
		with patch.object(refresh_tokens.secrets, "token_urlsafe", return_value=original):
			try:
				refresh_tokens.rotate(original)
			except Exception as exc:
				self.assertTrue(
					frappe.db.is_unique_key_violation(exc), "Expected token_hash unique violation"
				)
			else:
				self.fail("The database accepted duplicate token hashes")
		self.assertFalse(self._record(original).used_at)
		self.assertEqual(len(self._rows(self._record(original).family_id)), 1)
		refresh_tokens.rotate(original)

	def test_concurrent_rotation_mints_once_then_revokes_the_winner(self):
		original = self._create()
		family_id = self._record(original).family_id
		outcomes = self._compete(
			family_id, [(refresh_tokens.rotate, original), (refresh_tokens.rotate, original)]
		)
		successes = [value for status, value in outcomes if status == "ok"]
		self.assertEqual(len(successes), 1)
		self.assertEqual(sum(status == "rejected" for status, _value in outcomes), 1)
		rows = self._rows(family_id)
		self.assertEqual(len(rows), 2)
		self.assertTrue(all(row.revoked_at for row in rows))
		with self.assertRaises(frappe.AuthenticationError):
			refresh_tokens.rotate(successes[0][1])

	def test_replay_and_descendant_rotation_share_one_family_lock(self):
		original = self._create()
		_user, current = refresh_tokens.rotate(original)
		family_id = self._record(original).family_id
		outcomes = self._compete(
			family_id, [(refresh_tokens.rotate, original), (refresh_tokens.rotate, current)]
		)
		self.assertEqual(outcomes[0][0], "rejected")
		self.assertTrue(all(row.revoked_at for row in self._rows(family_id)))
		for status, result in outcomes:
			if status == "ok":
				with self.assertRaises(frappe.AuthenticationError):
					refresh_tokens.rotate(result[1])

	def test_logout_serializes_with_rotation(self):
		original = self._create()
		family_id = self._record(original).family_id
		outcomes = self._compete(
			family_id, [(refresh_tokens.revoke, original), (refresh_tokens.rotate, original)]
		)
		self.assertEqual(outcomes[0], ("ok", None))
		self.assertTrue(all(row.revoked_at for row in self._rows(family_id)))
		if outcomes[1][0] == "ok":
			with self.assertRaises(frappe.AuthenticationError):
				refresh_tokens.rotate(outcomes[1][1][1])

	def test_permissions_allow_only_metadata_reads(self):
		meta = frappe.get_meta("API Refresh Token")
		hash_field = meta.get_field("token_hash")
		self.assertTrue(hash_field.unique)
		self.assertTrue(hash_field.hidden)
		self.assertGreater(hash_field.permlevel, 0)
		self.assertTrue(meta.get_field("family_id").search_index)
		self.assertEqual(len(meta.permissions), 1)
		permission = meta.permissions[0]
		self.assertEqual(permission.role, "System Manager")
		self.assertEqual(permission.permlevel, 0)
		self.assertTrue(permission.read)
		for operation in ("create", "write", "delete", "export", "share"):
			self.assertFalse(permission.get(operation))
		self.assertFalse(frappe.has_permission("API Refresh Token", "read", user="Guest"))
		self.assertFalse(frappe.has_permission("API Refresh Token", "create", user="Guest"))


def _consume(site, sites_path, operation, token, barrier):
	"""Each competing consumer gets its own Frappe context and DB connection."""
	frappe.init(site=site, sites_path=sites_path)
	try:
		frappe.connect()
		barrier.wait(timeout=20)
		try:
			return "ok", operation(token)
		except frappe.AuthenticationError:
			frappe.db.rollback()  # The same rollback a failed request performs.
			return "rejected", None
	finally:
		frappe.destroy()
