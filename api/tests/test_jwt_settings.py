from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from api.rest_api.doctype.api_settings.api_settings import APISettings, get_settings
from api.services.auth.settings import (
	DEFAULT_ACCESS_TOKEN_TTL,
	DEFAULT_REFRESH_TOKEN_TTL,
	get_jwt_settings,
	initialize_jwt_settings,
)


class TestJWTSettings(TestCase):
	def setUp(self):
		self.values = {}
		self.encrypted = {}
		self.doc = MagicMock()
		self.doc.get.side_effect = self.values.get
		self.doc.set.side_effect = self.values.__setitem__
		self.doc.get_password.side_effect = self._get_password
		self.doc.save.side_effect = self._save
		self.conf = frappe._dict()
		self.generated_secret = "generated-secret" * 4
		original_site = getattr(frappe.local, "site", None)
		frappe.local.site = "settings.test"
		self.addCleanup(setattr, frappe.local, "site", original_site)
		for target, value in (
			("api.services.auth.settings.frappe.get_cached_doc", self.doc),
			("api.services.auth.settings.frappe.get_single", self.doc),
		):
			patcher = patch(target, return_value=value)
			patcher.start()
			self.addCleanup(patcher.stop)
		for patcher in (
			patch.object(frappe, "conf", self.conf),
			patch.object(frappe, "throw", side_effect=self._throw),
		):
			patcher.start()
			self.addCleanup(patcher.stop)
		self.generator = patch(
			"api.services.auth.settings.secrets.token_urlsafe", return_value=self.generated_secret
		)
		self.generate_secret = self.generator.start()
		self.addCleanup(self.generator.stop)

	@staticmethod
	def _throw(message, exc=frappe.ValidationError):
		raise exc(message)

	def _get_password(self, fieldname):
		return self.encrypted.get(fieldname, self.values.get(fieldname))

	def _save(self, **kwargs):
		secret = self.values.get("api_jwt_secret")
		if secret and secret != "*****":
			self.encrypted["api_jwt_secret"] = secret
			self.values["api_jwt_secret"] = "*****"

	def test_nonempty_document_values_override_site_configuration(self):
		self.values.update(
			api_jwt_secret="d" * 32,
			api_jwt_issuer="desk-issuer",
			api_jwt_audience="desk-audience",
			api_jwt_access_token_ttl=60,
			api_jwt_refresh_token_ttl=120,
		)
		self.conf.update(
			api_jwt_secret="c" * 32,
			api_jwt_issuer="conf-issuer",
			api_jwt_audience="conf-audience",
			api_jwt_access_token_ttl=180,
			api_jwt_refresh_token_ttl=240,
		)
		self.assertEqual(
			get_jwt_settings(),
			{
				"secret": "d" * 32,
				"issuer": "desk-issuer",
				"audience": "desk-audience",
				"access_ttl": 60,
				"refresh_ttl": 120,
			},
		)
		self.doc.get_password.assert_called_once_with("api_jwt_secret")
		self.doc.save.assert_not_called()

	def test_empty_document_values_fall_back_to_site_configuration(self):
		self.values.update(
			api_jwt_secret="",
			api_jwt_issuer="",
			api_jwt_audience=None,
			api_jwt_access_token_ttl=0,
			api_jwt_refresh_token_ttl="",
		)
		self.conf.update(
			api_jwt_secret="c" * 32,
			api_jwt_issuer="conf-issuer",
			api_jwt_audience="conf-audience",
			api_jwt_access_token_ttl="60",
			api_jwt_refresh_token_ttl=120,
		)
		settings = get_jwt_settings()
		self.assertEqual(
			settings,
			{
				"secret": "c" * 32,
				"issuer": "conf-issuer",
				"audience": "conf-audience",
				"access_ttl": 60,
				"refresh_ttl": 120,
			},
		)
		self.doc.get_password.assert_not_called()

	def test_empty_ttls_use_defaults_at_both_sources(self):
		self.conf.api_jwt_secret = "c" * 32
		for empty in (None, "", 0):
			with self.subTest(empty=empty):
				for source in (self.values, self.conf):
					source["api_jwt_access_token_ttl"] = empty
					source["api_jwt_refresh_token_ttl"] = empty
				settings = get_jwt_settings()
				self.assertEqual(settings["access_ttl"], DEFAULT_ACCESS_TOKEN_TTL)
				self.assertEqual(settings["refresh_ttl"], DEFAULT_REFRESH_TOKEN_TTL)
				self.assertEqual(settings["issuer"], "settings.test")
				self.assertEqual(settings["audience"], "api")

	def test_nonempty_invalid_ttls_are_rejected_at_each_source(self):
		self.conf.api_jwt_secret = "c" * 32
		for source in (self.values, self.conf):
			for fieldname in ("api_jwt_access_token_ttl", "api_jwt_refresh_token_ttl"):
				for invalid in (-1, "-1", "0", 1.5, "1.5", "invalid-ttl", " ", True):
					with self.subTest(source=source is self.conf, field=fieldname, invalid=invalid):
						source[fieldname] = invalid
						with self.assertRaises(frappe.ValidationError):
							get_jwt_settings()
						source.pop(fieldname)

	def test_positive_integer_ttls_are_not_clamped(self):
		self.conf.update(
			api_jwt_secret="c" * 32, api_jwt_access_token_ttl=1, api_jwt_refresh_token_ttl=100_000_000
		)
		settings = get_jwt_settings()
		self.assertEqual(settings["access_ttl"], 1)
		self.assertEqual(settings["refresh_ttl"], 100_000_000)

	def test_secret_length_is_measured_in_utf8_bytes(self):
		for secret in ("a" * 32, "é" * 16):
			with self.subTest(secret=secret):
				self.conf.api_jwt_secret = secret
				self.assertEqual(get_jwt_settings()["secret"], secret)
		for secret in ("a" * 31, "é" * 15, 32):
			with self.subTest(secret=secret):
				self.conf.api_jwt_secret = secret
				with self.assertRaises(frappe.ValidationError):
					get_jwt_settings()

	def test_weak_document_secret_does_not_fall_back_to_config(self):
		self.values["api_jwt_secret"] = "weak-secret"
		self.conf.api_jwt_secret = "c" * 32
		with self.assertRaises(frappe.ValidationError) as error:
			get_jwt_settings()
		self.assertNotIn("weak-secret", str(error.exception))

	def test_missing_secret_has_no_encryption_key_fallback_or_runtime_generation(self):
		self.conf.encryption_key = "e" * 64
		with self.assertRaises(frappe.ValidationError):
			get_jwt_settings()
		self.generate_secret.assert_not_called()
		self.doc.save.assert_not_called()

	def test_password_decryption_error_does_not_fall_back_or_generate(self):
		self.values["api_jwt_secret"] = "*****"
		self.conf.api_jwt_secret = "c" * 32
		self.doc.get_password.side_effect = frappe.ValidationError("Cannot decrypt")
		for operation in (get_jwt_settings, initialize_jwt_settings):
			with self.subTest(operation=operation.__name__):
				with self.assertRaises(frappe.ValidationError):
					operation()
		self.generate_secret.assert_not_called()
		self.doc.save.assert_not_called()

	def test_initializer_generates_once_and_is_idempotent(self):
		initialize_jwt_settings()
		initialize_jwt_settings()
		self.generate_secret.assert_called_once_with(48)
		self.doc.save.assert_called_once_with(ignore_permissions=True)
		self.assertEqual(
			self.values,
			{
				"api_jwt_secret": "*****",
				"api_jwt_issuer": "settings.test",
				"api_jwt_audience": "api",
				"api_jwt_access_token_ttl": DEFAULT_ACCESS_TOKEN_TTL,
				"api_jwt_refresh_token_ttl": DEFAULT_REFRESH_TOKEN_TTL,
			},
		)
		self.assertEqual(get_jwt_settings()["secret"], self.generated_secret)

	def test_initializer_preserves_site_configuration_without_copying_it(self):
		self.conf.update(
			api_jwt_secret="c" * 32,
			api_jwt_issuer="conf-issuer",
			api_jwt_audience="conf-audience",
			api_jwt_access_token_ttl=60,
			api_jwt_refresh_token_ttl=120,
		)
		initialize_jwt_settings()
		initialize_jwt_settings()
		self.generate_secret.assert_not_called()
		self.doc.save.assert_not_called()
		self.assertEqual(self.values, {})

	def test_initializer_preserves_existing_secret_and_fills_only_empty_sources(self):
		self.values.update(
			api_jwt_secret="d" * 32,
			api_jwt_issuer="desk-issuer",
			api_jwt_access_token_ttl=0,
			api_jwt_refresh_token_ttl=99,
		)
		self.conf.update(api_jwt_audience="conf-audience", api_jwt_access_token_ttl=0)
		initialize_jwt_settings()
		self.generate_secret.assert_not_called()
		self.assertEqual(
			get_jwt_settings(),
			{
				"secret": "d" * 32,
				"issuer": "desk-issuer",
				"audience": "conf-audience",
				"access_ttl": DEFAULT_ACCESS_TOKEN_TTL,
				"refresh_ttl": 99,
			},
		)
		self.assertNotIn("api_jwt_audience", self.values)

	def test_initializer_rejects_invalid_config_instead_of_saving_defaults(self):
		self.conf.update(api_jwt_secret="c" * 32, api_jwt_access_token_ttl=-1)
		with self.assertRaises(frappe.ValidationError):
			initialize_jwt_settings()
		self.doc.save.assert_not_called()

	def test_controller_validates_nonempty_jwt_fields(self):
		doc = APISettings({"doctype": "API Settings"})
		for fieldname, invalid in (
			("api_jwt_secret", "short"),
			("api_jwt_access_token_ttl", -1),
			("api_jwt_refresh_token_ttl", "1.5"),
		):
			with self.subTest(field=fieldname):
				doc.set(fieldname, invalid)
				with self.assertRaises(frappe.ValidationError):
					doc.validate()
				doc.set(fieldname, None)
		doc.api_jwt_access_token_ttl = 0
		doc.api_jwt_refresh_token_ttl = 0
		doc.validate()

	def test_generic_settings_never_include_signing_secret(self):
		self.values["api_jwt_secret"] = "d" * 32
		with patch.object(frappe, "db", MagicMock()):
			settings = get_settings()
		self.assertNotIn("api_jwt_secret", settings)
		self.assertNotIn("secret", settings)
		self.doc.get_password.assert_not_called()
