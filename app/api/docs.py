from app.schemas.common import ErrorResponse

_DESCRIPTIONS = {
    400: "Request is well-formed but breaks a business rule",
    401: "Missing, invalid or expired token (or bad credentials)",
    403: "Admin privileges required",
    404: "Resource not found (also returned for resources owned by someone else)",
    409: "Conflicts with the current state of the resource",
    422: "Validation error",
    429: "Too many requests",
}


def error_responses(*codes: int) -> dict:
    return {code: {"model": ErrorResponse, "description": _DESCRIPTIONS[code]} for code in codes}
