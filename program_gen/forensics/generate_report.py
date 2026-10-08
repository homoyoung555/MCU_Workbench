"""Generate the STANDARD_TRIM / Hsi_8M CP1 fact-matrix HTML report artifact.

This driver is the sanctioned harness: it reads the formal master through
``WorkbookReader`` (one WorkbookModel snapshot), compiles it with
``ProductCompiler`` (the typed ProductCompilation), and hands the compilation
to the PURE report generator in ``standard_trim_matrix``.  It never touches
``G``, legacy writers, Golden output, or any filesystem scanning, and it does
not generate tester text / contributions / fragments / registrations.

The matrix facts are CP-scoped with explicit platform scope per fact, so one
report (chroma target identity, matching the Gap Model's ``TargetKey``) covers
both platforms.

Run from the repository root:
    python -m program_gen.forensics.generate_report
"""

from __future__ import annotations

from pathlib import Path

from program_gen.compiler import ProductCompiler
from program_gen.forensics.standard_trim_matrix import (
    build_fact_matrix,
    extract_snapshot,
    pending_adjudication_questions,
    render_html,
)
from program_gen.workbook import WorkbookReader
from tests.workspace_paths import FORMAL_MASTER

OUTPUT = Path(__file__).resolve().parent / "STANDARD_TRIM_Hsi_8M_CP1_fact_matrix.html"


def main() -> None:
    workbook = WorkbookReader().read(FORMAL_MASTER)
    compilation = ProductCompiler().compile(workbook).require_success()

    snapshot = extract_snapshot(
        compilation,
        cp="CP1",
        item="Hsi_8M",
        platform="chroma",
        variant="lab",
        program_name="V_TEST_CP1",
    )
    facts = build_fact_matrix(snapshot)
    questions = pending_adjudication_questions(snapshot, facts)
    document = render_html(snapshot, facts, questions)
    OUTPUT.write_text(document, encoding="utf-8", newline="\n")
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
