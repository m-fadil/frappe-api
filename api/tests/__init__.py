from importlib import import_module, reload
from unittest.mock import patch


def stub_whitelist(**options):
	def decorate(fn):
		fn.whitelist_options = options
		return fn

	return decorate


def load_endpoint_module(name: str, calls: list | None = None):
	"""Reload module endpoint dengan log & frappe.whitelist yang di-stub."""
	import api.api.core.decorators as decorators

	def stub_log():
		def decorate(fn):
			def wrapped(*args, **kwargs):
				if calls is not None:
					calls.append((args, kwargs))
				return fn(*args, **kwargs)

			wrapped.is_logged = True
			return wrapped

		return decorate

	with (
		patch.object(decorators, "log", stub_log),
		patch.object(decorators.frappe, "whitelist", stub_whitelist),
	):
		return reload(import_module(name))
