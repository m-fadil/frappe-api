### REST API

Enterprise REST API toolkit for Frappe with comprehensive audit logs and runtime controls.

### API documentation (Bruno)

Open [`bruno/`](bruno/README.md) as a Bruno collection for request payloads, saved
response examples, JWT flow, and app administration APIs. Public smoke:
`cd bruno && bru run Public --env Local --disable-cookies --bail`.
JWT identity changes preserve parsed request payloads, including protected
Customer DTO/validation requests.

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch version-16
bench install-app api
```

### Architecture

- `api/api/` is the HTTP layer: whitelisted handlers, request policies, DTOs,
  pipes, and rate limits delegate reusable authentication work to
  `api/services/auth/`.
- `jwt.py` issues and validates access JWTs; `password.py` handles native
  password/MFA login; `refresh_tokens.py` manages refresh-token families;
  `settings.py` resolves and initializes JWT configuration; `audit.py` records
  authentication audit events; `users.py` checks active users and builds the
  allowlisted user profile.
- DocTypes and their controllers remain under `api/rest_api/doctype/` unchanged.

The auth hook is now `api.services.auth.jwt.validate`; the install/migrate hook
is `api.services.auth.settings.initialize_jwt_settings`. Public RPC aliases
`api.auth.login`, `api.auth.issue`, `api.auth.refresh`, and `api.auth.revoke`
still map to `api.api.auth.*`; request URLs and behavior are unchanged.

For this source-only reorganization, run `bench --site <site> clear-cache` and
`bench restart` after deployment. No schema migration, signing-key regeneration,
or data deletion is required; retain existing settings, tokens, and audit data.

### Public RPC names

Public URLs use explicit `override_whitelisted_methods` mappings in `api/hooks.py`.
Endpoint files remain under `api/api/`; reusable auth services live under
`api/services/auth/`.

| Public RPC name | Python implementation |
| --- | --- |
| `api.auth.login` | `api.api.auth.login` |
| `api.auth.issue` | `api.api.auth.issue` |
| `api.auth.refresh` | `api.api.auth.refresh` |
| `api.auth.revoke` | `api.api.auth.revoke` |
| `api.ping.ping` | `api.api.ping.ping.ping` |
| `api.calculator.calculate` | `api.api.calculator.calculate.calculate` |
| `api.customer.create` | `api.api.customer.create_customer.create_customer` |

Call `/api/method/<public-name>` (v1, `message` envelope) or
`/api/v2/method/<public-name>` (v2, `data` envelope). Both dispatch to the same
whitelisted handler, policies, DTO/pipes and rate limiter. Long implementation
URLs remain callable; these mappings add public aliases, not a Python rename.
Python imports and direct `frappe.get_attr`/`frappe.call` must still use the
implementation path. Log endpoint names, `excluded_endpoints`, and rate-limit
keys also retain the implementation name.

After changing RPC mappings, run `bench --site <site> clear-cache` and restart
long-running web workers. This routing change does not require schema migration.

### JWT authentication

Open **API Settings → Authentication** to configure JWT signing. Configuration
precedence is **nonempty API Settings field → `site_config.json` → defaults**.
TTL fields treat zero as empty; invalid nonempty values are rejected.

| Field / site-config key | Default when both sources are empty |
| --- | --- |
| `api_jwt_secret` | Cryptographically random, encrypted Password field |
| `api_jwt_issuer` | Current site name |
| `api_jwt_audience` | `api` |
| `api_jwt_access_token_ttl` | 900 seconds |
| `api_jwt_refresh_token_ttl` | 2592000 seconds |

`after_install` and `after_migrate` initialize missing values in the Single
DocType without overwriting either configured source. A site-config secret is
not copied into the document. If both secrets are empty, initialization
generates one and saves it encrypted in API Settings. No request generates keys,
and there is no fallback to the site's encryption key. Signing secrets must
contain at least 32 UTF-8 bytes. Changing the signing secret invalidates existing
access tokens. Restrict API Settings access to trusted System Managers.

The JWT auth hook assigns the Frappe user only after verifying the HS256
signature, required claims, issuer, audience, token type, and active user.
Its `frappe.set_user` call has a single-line Semgrep exception for the
Frappe manual-audit rule; other occurrences remain subject to that rule.

On Frappe 15, token issuance retains the 20-per-minute per-user limit using
an atomic Redis counter; login, refresh, and revoke retain their IP limits.

For upgrades that introduce DocType changes, run `bench --site <site> migrate`
and `bench restart`. The auth service reorganization alone only needs the
clear-cache and restart deployment steps above.

#### Password login with own profile

`POST /api/method/api.auth.login` accepts native Frappe user credentials without
an API key/secret and returns the existing JWT pair plus an allowlisted `user`
profile. It does not create an authenticated Frappe session or return a `sid`.

```bash
curl -X POST https://example.test/api/method/api.auth.login \
  -H 'Content-Type: application/json' \
  -d '{"usr":"user@example.com","pwd":"<password>","client_id":"mobile-app"}'
```

```json
{
  "message": {
    "access_token": "<jwt-access-token>",
    "refresh_token": "<opaque-refresh-token>",
    "token_type": "Bearer",
    "expires_in": 900,
    "user": {
      "name": "user@example.com",
      "email": "user@example.com",
      "first_name": "Example",
      "last_name": "User",
      "full_name": "Example User",
      "user_image": null,
      "language": "en",
      "time_zone": "Asia/Jakarta",
      "user_type": "Website User",
      "roles": ["All"]
    }
  }
}
```

The profile above is illustrative. Only those explicit profile fields are
returned; never the complete User document, password/hash, API key or API secret.
Use native username/mobile login identifiers only when enabled in Frappe System
Settings. Passwords are not trimmed or HTML-sanitized: login explicitly uses
`xss_safe=True` to bypass Frappe's guest string rewriting, while retaining strict
input validation and JSON-only response data. Rate limit: 10 login attempts per
IP/minute, plus native Frappe user/IP failure tracking and lockout.

The service reuses native `LoginManager.login` checks: password-login disable,
enabled user, MFA, IP/login hours, password expiry and before/on-login hooks.
Only native session creation is replaced by JWT issuance. Existing caller
sessions are not logged out or overwritten. Native cookie session lifetime and
simultaneous-session limits are not JWT refresh-family settings.

If MFA is required, the response contains **no tokens or profile**:

```json
{
  "message": {
    "mfa_required": true,
    "tmp_id": "<private-native-challenge-id>",
    "verification": {"method": "OTP App", "setup": true}
  }
}
```

Complete the same endpoint with `{"tmp_id":"<challenge-id>","otp":"<code>","client_id":"mobile-app"}`.
Do not send the password again. Native OTP App/Email/SMS delivery and challenge
expiry apply. A successful verification consumes the challenge, including when
a password reset is then required; replay/expired challenge returns 401.
Forced password reset returns 401 without JWT/profile or a reset key: finish the
native reset procedure before logging in again. Invalid credentials return 401;
blocked/locked accounts retain native Frappe error status.

Login uses `@endpoint`, `LoginDTO`, a non-transforming validation pipe,
`policies=(api_enabled,)`, and `AUTH_METADATA_ONLY`. `enable_api=0` blocks login,
while `allow_guest_access=0` does not block this credential-based operation.
Responses are no-store and credential payloads are never passed to API Log.
Bruno examples are in `bruno/Login/`; use `--tags password-login` for the
non-MFA lifecycle and the separate Complete MFA request when challenged.

#### Issue and use tokens

Exchange existing Frappe API key/secret authentication for a token pair:

```bash
curl -X POST https://example.test/api/method/api.auth.issue \
  -H 'Authorization: token <api-key>:<api-secret>' \
  -H 'Content-Type: application/json' \
  -d '{"client_id":"my-integration"}'
```

The Frappe `message` response contains `access_token`, `refresh_token`,
`token_type: "Bearer"`, and `expires_in` (seconds). Native authenticated sessions
can also issue tokens using normal Frappe CSRF protection. JWT-authenticated
requests cannot issue a new refresh family. `client_id` is an optional descriptive
label, not a separate client identity or permission grant.

Use `Authorization: Bearer <access_token>` for subsequent requests. Existing
session, API key and OAuth authentication remain supported; Frappe roles and
document permissions remain authoritative. The verifier rejects invalid
signature, issuer, audience, expiry, not-before, token type, and disabled users.

#### Refresh and revoke

```bash
curl -X POST https://example.test/api/method/api.auth.refresh \
  -H 'Content-Type: application/json' \
  -d '{"refresh_token":"<refresh-token>"}'

curl -X POST https://example.test/api/method/api.auth.revoke \
  -H 'Content-Type: application/json' \
  -d '{"refresh_token":"<refresh-token>"}'
```

Do not send an expired access-token header to these endpoints. Refresh tokens are
opaque, stored only as SHA-256 hashes in **API Refresh Token**, and consumed
atomically using database family locks. Refresh rotates both credentials without
extending the family's original expiry. Reusing any consumed refresh token
durably revokes its entire family, including the latest descendant. Clients must
serialize refresh calls; concurrent retries are treated as replay. Lost refresh
responses require native authentication to issue a new family.

Logout/revoke is idempotent and revokes the entire refresh family. Existing
access JWTs remain valid until their short expiry; logout is not an immediate
access-token denylist. Disabled users are rejected on subsequent JWT requests.
Refresh lifecycle transactions are independent of request rollback, so replay
revocation cannot be undone by an authentication error.

Token endpoints use the shared `@endpoint` pipeline with DTOs, validation pipes,
explicit access policies and `AUTH_METADATA_ONLY` telemetry. They return
`Cache-Control: no-store`, including policy/validation failures. Payloads,
credential headers, results and tracebacks are never passed to API Log in this
mode, even if masking is disabled. Metadata-only security events go to
`api_auth.log`. Rate limits are 20 issue requests per user/minute and 30 refresh
or revoke requests per IP/minute. Use HTTPS and secure client-side credential
storage; never persist raw tokens in URLs or logs.

System Managers can review token metadata, expiry, consumption and revocation in
**API Refresh Token**; token hashes are restricted from ordinary metadata reads.
Used rows remain available for replay detection. Retain complete families until
their absolute expiry; never delete a live family's root or used-token history.

### Composable endpoint policies

`@endpoint` separates access checks (`policies`), payload validation/transformation
(`pipes` and `dto`), normalization, and telemetry. Policies receive an immutable
`RequestContext(user, method, endpoint)`, return `None` on success and raise on
denial. They must not modify payloads or identities.

```python
import frappe

from api.api.core.decorators import endpoint
from api.api.core.policies import api_enabled, authenticated, require_roles


@endpoint(
    methods=("GET",),
    policies=(api_enabled, authenticated, require_roles("Sales User", "Sales Manager")),
)
def sales_identity():
    return {"user": frappe.session.user}
```

Policies run in declaration order, fail-fast, **before** payload normalization,
pipes, DTO construction and handler execution. All listed policies must allow;
`require_roles` allows any one of its listed roles. Custom policy functions follow
the same context-to-None/exception contract.

- `policies=None` (default): `(api_enabled, guest_access_allowed)`, preserving
  business endpoint switches.
- An explicit tuple **replaces**, not appends to, default policies.
- `policies=()` intentionally bypasses all decorator access policies, including
  `enable_api`; Frappe whitelist and native permission checks still apply.
- `guest=True` controls the Frappe whitelist only, not proof of authentication.
- `normalize=True` retains string trimming for business payloads; `False` skips
  that default transform while keeping custom pipes and DTO binding.
- `xss_safe=False` (default) retains Frappe's guest HTML sanitization.
  Credential login explicitly sets it to `True` so valid passwords containing
  HTML characters reach the password verifier unchanged. Do not enable this
  for endpoints that render untrusted input as HTML.

JWT issue uses `(api_enabled, native_authenticated)`, while refresh/revoke use
`(api_enabled,)` because refresh-token credentials are validated by the service.
Consequently `enable_api=0` blocks all three, but `allow_guest_access=0` does not
block credential-based refresh/logout. Authentication endpoints disable
normalization so credential strings are never silently trimmed.

Telemetry defaults to `STANDARD` (existing configurable API Log behavior).
`AUTH_METADATA_ONLY` is a fixed allowlisted-metadata mode, independent of payload
logging/masking settings. Unknown modes fail at decoration rather than silently
enabling payload logging. Native Frappe HTTP errors retain their status and error
contract; standard custom `ApiException` errors retain the legacy error envelope.
Access-policy `ApiException` failures now use that same standard envelope rather
than the previous framework exception envelope; HTTP status/code remain intact.
Metadata mode propagates HTTP exceptions and sanitizes unexpected failures without
logging exception messages or local-variable tracebacks.

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/api
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### License

mit
