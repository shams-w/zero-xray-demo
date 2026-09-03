class ZeroBureaucracyAgent:

    def __init__(self, llm):
        self.llm = llm

    def run(
        self,
        service_analysis,
        gaps,
    ):

        findings = []

        for gap in gaps.get(
            "gaps",
            []
        ):

            findings.append({
                "category":
                    gap.get(
                        "category",
                        ""
                    ),
                "description":
                    gap.get(
                        "description",
                        ""
                    ),
                "severity":
                    gap.get(
                        "severity",
                        "MEDIUM"
                    ),
                "recommendation":
                    gap.get(
                        "recommendation",
                        ""
                    ),
                "related_gap_id":
                    gap.get(
                        "gap_id",
                        ""
                    ),
                "standard_id":
                    gap.get(
                        "standard_id",
                        ""
                    ),
                # MERGED FROM P1: carry the same fixed 8-category
                # classification GapAnalysisAgent already attached
                # (classify_gap, core/framework.py), so this agent's
                # own output speaks the same framework vocabulary
                # instead of only the raw gap "category" free-text
                # label.
                "framework_categories":
                    gap.get(
                        "framework_categories",
                        [],
                    ),
            })

        severity_order = {
            "HIGH": 3,
            "MEDIUM": 2,
            "LOW": 1,
        }

        sorted_findings = sorted(
            findings,
            key=lambda item:
                severity_order.get(
                    item.get(
                        "severity",
                        "LOW"
                    ),
                    0
                ),
            reverse=True,
        )

        priority = [
            {
                "gap_id":
                    item["related_gap_id"],
                "category":
                    item["category"],
                "recommendation":
                    item["recommendation"],
            }
            for item in sorted_findings[:5]
        ]

        # MERGED FROM P1: how many findings fall under each of the 8
        # fixed decision categories -- a service-agnostic summary
        # derived purely from what GapAnalysisAgent already
        # classified, never from a service name or a hardcoded
        # category list.
        framework_category_counts = {}
        for item in findings:
            for category in item.get("framework_categories", []):
                framework_category_counts[category] = (
                    framework_category_counts.get(category, 0) + 1
                )

        return {
            "findings": findings,
            "priority_opportunities":
                priority,
            "framework_category_counts":
                framework_category_counts,
            # MERGED FROM P1: pass through where the underlying gap
            # analysis came from (AI-primary or the deterministic
            # baseline) for traceability -- this agent only aggregates
            # and sorts, so it has no reasoning of its own to
            # attribute.
            "analysis_source":
                gaps.get("analysis_source", "template"),
        }