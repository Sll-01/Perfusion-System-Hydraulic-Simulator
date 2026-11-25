"""Run the test-suite and write documentation/test_results.md (test id, outcome, duration)."""
import datetime
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
xml = ROOT / "results" / "pytest_junit.xml"
xml.parent.mkdir(exist_ok=True)
subprocess.run([sys.executable, "-m", "pytest", "-q", f"--junitxml={xml}"], cwd=ROOT)
tree = ET.parse(xml)
rows, n_pass, n_fail = [], 0, 0
for tc in tree.iter("testcase"):
    failed = tc.find("failure") is not None or tc.find("error") is not None
    skipped = tc.find("skipped") is not None
    outcome = "FAIL" if failed else "SKIP" if skipped else "PASS"
    n_pass += outcome == "PASS"
    n_fail += outcome == "FAIL"
    rows.append(f"| {tc.get('classname').replace('tests.', '')} | {tc.get('name')} | {outcome} | {float(tc.get('time')):.2f} |")
from core import SOFTWARE_VERSION  # noqa: E402

text = (f"# Test results\n\nSoftware version {SOFTWARE_VERSION} - run {datetime.datetime.now():%Y-%m-%d %H:%M} - "
        f"Python {sys.version.split()[0]}\n\n**{n_pass} passed, {n_fail} failed, {len(rows)} total.**\n\n"
        "| Module | Test | Result | Time [s] |\n|---|---|---|---|\n" + "\n".join(rows) + "\n")
(ROOT / "documentation" / "test_results.md").write_text(text, encoding="utf-8")
print(f"{n_pass} passed, {n_fail} failed")
