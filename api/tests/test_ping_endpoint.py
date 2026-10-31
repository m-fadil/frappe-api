from dataclasses import dataclass
from unittest import TestCase
from unittest.mock import patch

from api.api.core.exceptions import BadRequestException
from api.tests import load_endpoint_module, stub_whitelist


@dataclass(slots=True)
class _Body:
	required: str
	optional: str | None = None


class TestPingEndpoint(TestCase):
	def setUp(self):
		self.module = load_endpoint_module("api.api.ping.ping")

	def _form_dict(self, **values):
		return patch("api.api.core.request.frappe.form_dict", values)

	def _build_endpoint(self, **options):
		"""Bikin endpoint ad-hoc dengan log di-stub, untuk menguji decorator-nya
		sendiri lepas dari slice mana pun."""
		import api.api.core.decorators as decorators

		def decorate(fn):
			with (
				patch.object(decorators, "log", lambda **kwargs: lambda f: f),
				patch.object(decorators.frappe, "whitelist", stub_whitelist),
			):
				return decorators.endpoint(policies=(), **options)(fn)

		return decorate

	def test_ping_returns_pong(self):
		with self._form_dict():
			result = self.module.ping()

		self.assertEqual(result, {"message": "pong"})

	def test_ping_endpoint_ignores_extra_query_params(self):
		"""form_dict membawa semua query param; endpoint tanpa DTO tidak boleh 500 karenanya."""
		with self._form_dict(foo="1", cmd="ignored"):
			self.assertEqual(self.module.ping(), {"message": "pong"})

	def test_endpoint_without_dto_rejects_missing_required_argument(self):
		"""Argumen wajib yang tidak dikirim client = 400, bukan TypeError yang jadi 500."""

		@self._build_endpoint()
		def echo(required: str):
			return {"required": required}

		with self._form_dict(), self.assertRaises(BadRequestException) as ctx:
			echo()

		self.assertEqual(ctx.exception.status_code, 400)
		self.assertEqual(ctx.exception.code, "INVALID_REQUEST_PAYLOAD")

	def test_endpoint_without_dto_passes_declared_arguments(self):
		@self._build_endpoint()
		def echo(required: str):
			return {"required": required}

		with self._form_dict(required="x", cmd="ignored"):
			self.assertEqual(echo(), {"required": "x"})

	def test_endpoint_with_dto_rejects_missing_required_field(self):
		"""Field DTO wajib yang absen = 400. Param asing sudah difilter, jadi ini satu-satunya
		alasan DTO bisa melempar TypeError."""

		@self._build_endpoint(dto=_Body)
		def consumer(body: _Body):
			return {"required": body.required}

		with self._form_dict(), self.assertRaises(BadRequestException) as ctx:
			consumer()

		self.assertEqual(ctx.exception.status_code, 400)
		self.assertEqual(ctx.exception.code, "INVALID_REQUEST_PAYLOAD")

	def test_endpoint_rejects_positional_arguments(self):
		"""Payload selalu dibangun dari request, jadi positional arg pasti hilang.
		Lebih baik gagal keras daripada argumen pemanggil dibuang diam-diam."""

		@self._build_endpoint()
		def echo(value: str = "default"):
			return value

		with self.assertRaises(BadRequestException) as ctx:
			echo("positional")

		self.assertEqual(ctx.exception.status_code, 400)
		self.assertEqual(ctx.exception.code, "INVALID_REQUEST_PAYLOAD")
