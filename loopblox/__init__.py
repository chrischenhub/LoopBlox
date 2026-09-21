"""LoopBlox source root and exact implementation snapshots."""

from pathlib import Path
import shutil

from loopblox.runtime.io import digest


ROOT = Path(__file__).resolve().parent.parent


def snapshot_implementation(root):
    sources = sorted([
        *(ROOT / "loopblox").rglob("*.py"),
        *(ROOT / "controllers").glob("*.py"),
        *(ROOT / "experiments").glob("*.json"),
        *(path for path in (ROOT / "docs").rglob("*") if path.suffix in {".md", ".json"}),
        *(ROOT / name for name in ("AGENTS.md", "README.md", "CONTROLLER.md",
                                  "loop.md", "COMPONENTS.md", "experiment.md")),
    ])
    for path in sources:
        target = root / "implementation" / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    return {str(path.relative_to(ROOT)): digest(path.read_bytes()) for path in sources}
