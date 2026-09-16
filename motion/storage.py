import json
from pathlib import Path
from motion.types import SensorFrame


ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CALIBRATION_FILE = DATA / "motion_calibration.json"
TEMPLATE_DIR = DATA / "motion_templates"


def _ensure():
    DATA.mkdir(exist_ok=True)
    TEMPLATE_DIR.mkdir(exist_ok=True)


def load_calibration(profile="user"):
    _ensure()
    if not CALIBRATION_FILE.exists():
        return None
    return json.loads(CALIBRATION_FILE.read_text(encoding="utf-8")).get(profile)


def save_calibration(profile, calibration):
    _ensure()
    all_profiles = json.loads(CALIBRATION_FILE.read_text(encoding="utf-8")) if CALIBRATION_FILE.exists() else {}
    all_profiles[profile] = calibration
    CALIBRATION_FILE.write_text(json.dumps(all_profiles, indent=2), encoding="utf-8")


def load_templates(move_id):
    _ensure()
    path = TEMPLATE_DIR / f"{move_id}.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def add_template(move_id, hand, frames, metadata=None):
    """Append a labelled, portable motion recording to its move file."""
    _ensure()
    path = TEMPLATE_DIR / f"{move_id}.json"
    templates = load_templates(move_id)
    templates.append({
        "hand": hand,
        "frames": [frame.to_dict() if isinstance(frame, SensorFrame) else frame for frame in frames],
        "metadata": metadata or {},
    })
    path.write_text(json.dumps(templates, indent=2), encoding="utf-8")
    return len(templates)


def delete_templates(move_id):
    """Remove recordings only when their owning move is explicitly deleted."""
    path = TEMPLATE_DIR / f"{move_id}.json"
    if path.exists():
        path.unlink()
