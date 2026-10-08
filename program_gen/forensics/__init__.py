"""Domain-fact forensics for STANDARD_TRIM (read-only, no renderer).

The forensics package consumes only already-compiled typed facts
(WorkbookModel / ProductCompilation) and produces evidence reports.  It never
reads Excel raw objects, ``G``, legacy writers, Golden output, or scans the
filesystem, and it never generates tester text, contributions, fragments,
registrations, or compilations.
"""

from program_gen.forensics.standard_trim_matrix import (
    CONTRACTS,
    DomainFact,
    FactStatus,
    StandardTrimFactSnapshot,
    build_fact_matrix,
    extract_snapshot,
    pending_adjudication_questions,
    render_html,
    typed_contracts_complete,
)

__all__ = [
    "CONTRACTS",
    "DomainFact",
    "FactStatus",
    "StandardTrimFactSnapshot",
    "build_fact_matrix",
    "extract_snapshot",
    "pending_adjudication_questions",
    "render_html",
    "typed_contracts_complete",
]
