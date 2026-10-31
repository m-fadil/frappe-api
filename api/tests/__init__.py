from importlib import import_module, reload
from unittest.mock import patch


def stub_whitelist(**options):
	def decorate(fn):
		return fn

	return decorate


def load_endpoint_module(name: str):
	"""Load a business endpoint without telemetry or access-policy side effects."""
	import api.api.core.decorators as decorators

	with (
		patch.object(decorators, "log", lambda **options: lambda fn: fn),
		patch.object(decorators, "DEFAULT_POLICIES", ()),
		patch.object(decorators.frappe, "whitelist", stub_whitelist),
	):
		return reload(import_module(name))
