"""Write documentation/verification_report.md from the analytical reference cases."""
import datetime
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import APP_NAME, SOFTWARE_VERSION  # noqa: E402
from core.verification import report_markdown, run_reference_cases  # noqa: E402

cases = run_reference_cases()
text = f"""# Verification report - analytical reference cases

{APP_NAME} V{SOFTWARE_VERSION} - generated {datetime.datetime.now():%Y-%m-%d %H:%M}

Each case compares the software result with an analytical solution (or, where marked
*empirical*, with tabulated reference values / an alternative correlation). Tolerances are
relative unless marked otherwise. Regenerate with `python tools/generate_verification_report.py`.

**Result: {sum(c.passed for c in cases)} of {len(cases)} cases passed.**

{report_markdown(cases)}
"""
(ROOT / "documentation" / "verification_report.md").write_text(text, encoding="utf-8")
print(f"{sum(c.passed for c in cases)}/{len(cases)} passed")
