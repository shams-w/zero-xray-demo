"""Shared structured error for the Government Future Engine
(Predict -> Simulate -> Challenge -> Evolve -> Prevent -> Monitoring).

WHY THIS EXISTS: several stages used to raise a plain string 400
("This service has no usable simulation graph yet -- run /api/analyze
...") when THEIR OWN prerequisite data simply isn't stored yet -- a
genuinely different situation from a caller mistake (unknown
scenario_type, a step_id that doesn't exist) or a missing referenced
record (a 404 for a wrong prediction_id/challenge_id/evolution_id).
InsufficientDataError gives that specific situation one consistent,
machine-readable shape (`error_code`, `reason`, `missing_requirement`,
`next_action`) instead of an unstructured string, so a caller (or the
frontend) can distinguish "you need to do X first" from "that request
was invalid" or "that ID doesn't exist" -- without guessing from
message text.

This does NOT change which stages depend on which -- Evolve genuinely
needs a real challenge_id (there is nothing to evolve without a
Challenge run), Prevent genuinely needs a real evolution_id, Monitoring
genuinely needs a real prevention_id; those remain ordinary 404s for a
missing/wrong reference, unchanged. InsufficientDataError is only for
"this service's OWN stored data (future_steps/required_integrations)
isn't there yet" -- the one case where the fix is "run an earlier,
independent step" rather than "supply a valid reference."
"""


class InsufficientDataError(Exception):
    """Raised by a Future Engine agent when ITS OWN required stored
    data isn't there yet. `reason` explains what's missing and why;
    `missing_requirement` names the specific stored data that's
    absent; `next_action` tells the caller exactly what to do next.
    All three are always present and human-readable."""

    code = "INSUFFICIENT_DATA"

    def __init__(self, reason, missing_requirement, next_action):
        self.reason = reason
        self.missing_requirement = missing_requirement
        self.next_action = next_action
        super().__init__(reason)

    def to_detail(self):
        """The exact structured body main.py returns as the 400
        response's `detail` -- stable field names, always populated."""
        return {
            "error_code": self.code,
            "reason": self.reason,
            "missing_requirement": self.missing_requirement,
            "next_action": self.next_action,
        }


def insufficient_data_detail(reason, missing_requirement, next_action):
    """Same structured shape as InsufficientDataError.to_detail(), for
    call sites (main.py route handlers) that build the 400 response
    directly rather than catching a raised exception. Keeps both paths
    byte-for-byte consistent."""
    return InsufficientDataError(reason, missing_requirement, next_action).to_detail()
