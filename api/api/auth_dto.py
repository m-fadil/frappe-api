from dataclasses import dataclass


@dataclass(slots=True)
class IssueTokenDTO:
	client_id: str | None = None


@dataclass(slots=True)
class RefreshTokenDTO:
	refresh_token: str


@dataclass(slots=True)
class RevokeTokenDTO:
	refresh_token: str


@dataclass(slots=True)
class LoginDTO:
	usr: str | None = None
	pwd: str | None = None
	otp: str | None = None
	tmp_id: str | None = None
	client_id: str | None = None
