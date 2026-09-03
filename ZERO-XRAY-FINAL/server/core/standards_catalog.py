STANDARDS_CATALOG = [
    {
        "standard_id": "STD-01",
        "title": "Outcome Before Procedure",
        "requirement": (
            "The customer should express the desired outcome "
            "rather than being required to identify the exact "
            "government service, procedure, or channel."
        ),
        "measurable_test": (
            "The journey can begin from the customer's intended "
            "outcome without requiring knowledge of the internal "
            "service structure."
        ),
    },
    {
        "standard_id": "STD-02",
        "title": "Burden Shifts to the Assistant",
        "requirement": (
            "The assistant should collect and connect available "
            "information instead of requiring unnecessary "
            "administrative work or repeated data entry."
        ),
        "measurable_test": (
            "Customers are not required to repeat information "
            "already available and permitted for reuse."
        ),
    },
    {
        "standard_id": "STD-03",
        "title": "Natural Language as Primary Interface",
        "requirement": (
            "The customer should be able to communicate naturally "
            "without understanding complex government structures, "
            "menus, forms, or technical terminology."
        ),
        "measurable_test": (
            "A customer can request the intended outcome using "
            "natural language."
        ),
    },
    {
        "standard_id": "STD-04",
        "title": "Customer Control",
        "requirement": (
            "The customer must understand what the assistant is "
            "doing and must be able to approve, reject, pause, "
            "or stop actions when appropriate."
        ),
        "measurable_test": (
            "Required consent and control points are visible in "
            "the journey."
        ),
    },
    {
        "standard_id": "STD-05",
        "title": "Continuous Experience",
        "requirement": (
            "The experience should remain continuous across "
            "relevant channels and touchpoints without forcing "
            "the customer to restart unnecessarily."
        ),
        "measurable_test": (
            "Context and information continue across systems, "
            "channels, and employees where permitted."
        ),
    },
    {
        "standard_id": "STD-06",
        "title": "Exceptions Are Designed",
        "requirement": (
            "The journey must account for exceptions, failures, "
            "delays, objections, and cases requiring human "
            "intervention."
        ),
        "measurable_test": (
            "Important exception and human-handoff paths are "
            "defined."
        ),
    },
    {
        "standard_id": "STAGE-01",
        "title": "Journey Start",
        "requirement": (
            "The journey starts from a natural-language outcome "
            "request, or from a clear proactive need, without "
            "requiring the customer to know the service name."
        ),
        "measurable_test": (
            "The initial request is treated as an outcome and not "
            "as an administrative customer step."
        ),
    },
    {
        "standard_id": "STAGE-02",
        "title": "Understand Intent and Context",
        "requirement": (
            "The assistant understands the intended outcome and "
            "uses the permitted customer context before choosing "
            "the service path."
        ),
        "measurable_test": (
            "Only one targeted clarification is requested when "
            "the available context is genuinely insufficient."
        ),
    },
    {
        "standard_id": "STAGE-03",
        "title": "Complete Information",
        "requirement": (
            "Request only necessary information that is not "
            "already available through permitted government "
            "data sources."
        ),
        "measurable_test": (
            "Repeated information collection is avoided."
        ),
    },
    {
        "standard_id": "STAGE-04",
        "title": "Determine Journey and Approvals",
        "requirement": (
            "Determine required actions, dependencies and "
            "approvals, and avoid unnecessary approvals."
        ),
        "measurable_test": (
            "Each approval has a clear reason and unnecessary "
            "approvals are not introduced."
        ),
    },
    {
        "standard_id": "STAGE-05",
        "title": "Execution and Continuity",
        "requirement": (
            "Eligible actions should be executed through "
            "government systems without unnecessary customer "
            "intervention or manual information transfer."
        ),
        "measurable_test": (
            "Manual transfers, unnecessary waiting and repeated "
            "follow-up are minimized."
        ),
    },
    {
        "standard_id": "STAGE-06",
        "title": "Exceptions and Human Handoff",
        "requirement": (
            "When the assistant cannot continue, the case should "
            "be transferred to a human with the relevant context."
        ),
        "measurable_test": (
            "Human handoff does not require the customer to "
            "restart or repeat information."
        ),
    },
    {
        "standard_id": "STAGE-07",
        "title": "Payment Through UAE Government Payment",
        "requirement": (
            "When payment is required, the assistant presents the "
            "fees and beneficiary clearly, obtains explicit consent, "
            "and completes the payment through the approved UAE "
            "government payment journey."
        ),
        "measurable_test": (
            "Payment does not require a branch visit or a separate "
            "customer-operated journey, and failed or incomplete "
            "payments have a recovery path."
        ),
    },
    {
        "standard_id": "STAGE-08",
        "title": "Result, Objection and Customer Pulse",
        "requirement": (
            "The assistant delivers a clear result and provides a "
            "direct path to ask, correct, object or request a human "
            "from the same experience."
        ),
        "measurable_test": (
            "The result, effective date, document location, next "
            "action and objection path are visible to the customer."
        ),
    },
    {
        "standard_id": "READY-01",
        "title": "Testing, Measurement and Improvement",
        "requirement": (
            "The target journey is tested with real users and its "
            "customer effort, completion, trust, exceptions and "
            "outcomes are measured against a baseline."
        ),
        "measurable_test": (
            "A baseline and auditable impact indicators are included "
            "in the redesign output."
        ),
    },
]


STANDARDS_BY_ID = {
    item["standard_id"]: item
    for item in STANDARDS_CATALOG
}


def get_standard(standard_id):
    return STANDARDS_BY_ID.get(standard_id)


def valid_standard_ids():
    return set(STANDARDS_BY_ID.keys())
