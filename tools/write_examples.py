"""Write example configuration files (config/) and experiment templates (experimental_data/templates)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.project import ProjectFile, save_project  # noqa: E402
from core.validation import write_templates  # noqa: E402
from scenarios import SCENARIOS  # noqa: E402

save_project(ProjectFile(name="default_system", config=SCENARIOS[10].build()), ROOT / "config" / "default_system.json")
save_project(ProjectFile(name="default_system", config=SCENARIOS[10].build()), ROOT / "config" / "default_system.yaml")
for s in SCENARIOS:
    save_project(ProjectFile(name=s.title, config=s.build()), ROOT / "scenarios" / "configs" / f"{s.key}.json")
write_templates(ROOT / "experimental_data" / "templates")
print("written")
