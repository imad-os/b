import json
import sqlite3
from pathlib import Path
from .models import Move, Challenge


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
MOVES_FILE = DATA_DIR / "moves.json"
PROFILE_FILE = DATA_DIR / "profile.json"
SESSION_FILE = DATA_DIR / "session_history.json"
HEART_RATE_HISTORY_FILE = DATA_DIR / "heart_rate_history.json"
WATCH_FILE = DATA_DIR / "watch.json"
WORKOUT_FILE = DATA_DIR / "workouts.json"
DATABASE_FILE = DATA_DIR / "pulsebox.db"

DEFAULT_MOVES = [
    {"id": "left_jab", "label": "Left jab", "key": "a", "min_level": 1, "frequency": 10, "category": "Punch", "hand": "LEFT"},
    {"id": "right_cross", "label": "Right cross", "key": "b", "min_level": 1, "frequency": 10, "category": "Punch", "hand": "RIGHT"},
    {"id": "left_hook", "label": "Left hook", "key": "c", "min_level": 2, "frequency": 7, "category": "Punch", "hand": "LEFT"},
    {"id": "right_hook", "label": "Right hook", "key": "d", "min_level": 2, "frequency": 7, "category": "Punch", "hand": "RIGHT"},
    {"id": "left_uppercut", "label": "Left uppercut", "key": "e", "min_level": 3, "frequency": 5, "category": "Punch", "hand": "LEFT"},
    {"id": "right_uppercut", "label": "Right uppercut", "key": "f", "min_level": 3, "frequency": 5, "category": "Punch", "hand": "RIGHT"},
    {"id": "slip_left", "label": "Slip left", "key": "g", "min_level": 4, "frequency": 4, "category": "Defense", "hand": "LEFT"},
    {"id": "slip_right", "label": "Slip right", "key": "h", "min_level": 4, "frequency": 4, "category": "Defense", "hand": "RIGHT"},
    {"id": "roll_left", "label": "Roll left", "key": "i", "min_level": 5, "frequency": 3, "category": "Defense", "hand": "LEFT"},
    {"id": "roll_right", "label": "Roll right", "key": "j", "min_level": 5, "frequency": 3, "category": "Defense", "hand": "RIGHT"},
]

DEFAULT_WORKOUTS = [
    {"id":"first_bell","title":"First Bell","subtitle":"Two-move rhythm builder","level":1,"rounds":12,"accent":[255,91,83],"sport":"Box","move_ids":["left_jab","right_cross"],"move_weights":{"left_jab":50,"right_cross":50}},
    {"id":"jab_lab","title":"Jab Lab","subtitle":"Speed and clean form","level":1,"rounds":18,"accent":[28,191,177],"sport":"Box","move_ids":["left_jab","right_cross"],"move_weights":{"left_jab":65,"right_cross":35}},
    {"id":"cross_current","title":"Cross Current","subtitle":"Alternating straight punches","level":1,"rounds":20,"accent":[79,122,255],"sport":"Box","move_ids":["left_jab","right_cross"],"move_weights":{"left_jab":50,"right_cross":50}},
    {"id":"hook_theory","title":"Hook Theory","subtitle":"Introduce hooks with intent","level":2,"rounds":20,"accent":[255,181,71],"sport":"Box","move_ids":["left_jab","right_cross","left_hook","right_hook"],"move_weights":{"left_jab":25,"right_cross":25,"left_hook":25,"right_hook":25}},
    {"id":"side_step","title":"Side Step","subtitle":"Hooks and directional reactions","level":2,"rounds":24,"accent":[255,91,83],"sport":"Box","move_ids":["left_jab","right_cross","left_hook","right_hook"],"move_weights":{"left_jab":20,"right_cross":20,"left_hook":30,"right_hook":30}},
    {"id":"upper_line","title":"Upper Line","subtitle":"Uppercuts join the sequence","level":3,"rounds":24,"accent":[28,191,177],"sport":"Box","move_ids":["left_jab","right_cross","left_hook","right_hook","left_uppercut","right_uppercut"],"move_weights":{}},
    {"id":"power_phrase","title":"Power Phrase","subtitle":"Three-punch combinations","level":3,"rounds":28,"accent":[79,122,255],"sport":"Box","move_ids":["left_jab","right_cross","left_hook","right_hook","left_uppercut","right_uppercut"],"move_weights":{}},
    {"id":"slipstream","title":"Slipstream","subtitle":"Defense under pressure","level":4,"rounds":26,"accent":[255,181,71],"sport":"Box","move_ids":["left_jab","right_cross","left_hook","right_hook","slip_left","slip_right"],"move_weights":{}},
    {"id":"ring_iq","title":"Ring IQ","subtitle":"Full reaction vocabulary","level":4,"rounds":32,"accent":[255,91,83],"sport":"Box","move_ids":[],"move_weights":{}},
    {"id":"championship","title":"Championship Set","subtitle":"Endurance and precision","level":5,"rounds":40,"accent":[28,191,177],"sport":"Box","move_ids":[],"move_weights":{}}
]


def _connection():
    connection = sqlite3.connect(DATABASE_FILE)
    connection.execute("CREATE TABLE IF NOT EXISTS moves (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
    connection.execute("CREATE TABLE IF NOT EXISTS challenges (id TEXT PRIMARY KEY, payload TEXT NOT NULL, is_active INTEGER NOT NULL, position INTEGER NOT NULL)")
    connection.execute("CREATE TABLE IF NOT EXISTS user_data (key TEXT PRIMARY KEY, payload TEXT NOT NULL)")
    connection.execute("CREATE TABLE IF NOT EXISTS sessions (challenge_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
    connection.execute("CREATE TABLE IF NOT EXISTS heart_rate_sessions (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
    return connection


def ensure_data():
    DATA_DIR.mkdir(exist_ok=True)
    if not MOVES_FILE.exists():
        MOVES_FILE.write_text(json.dumps(DEFAULT_MOVES, indent=2), encoding="utf-8")
    if not WORKOUT_FILE.exists():
        WORKOUT_FILE.write_text(json.dumps(DEFAULT_WORKOUTS, indent=2), encoding="utf-8")
    with _connection() as db:
        if not db.execute("SELECT 1 FROM moves LIMIT 1").fetchone():
            values = json.loads(MOVES_FILE.read_text(encoding="utf-8"))
            db.executemany("INSERT INTO moves VALUES (?, ?)", [(item["id"], json.dumps(item)) for item in values])
        if not db.execute("SELECT 1 FROM challenges LIMIT 1").fetchone():
            values = json.loads(WORKOUT_FILE.read_text(encoding="utf-8"))
            db.executemany("INSERT INTO challenges VALUES (?, ?, ?, ?)", [(item["id"], json.dumps(item), int(item.get("is_active", True)), index) for index, item in enumerate(values)])
        # Older saved challenges predate the visible challenge-type feature.
        # Normalize them once so every existing record is explicitly a Box set.
        for challenge_id, payload in db.execute("SELECT id, payload FROM challenges").fetchall():
            item = json.loads(payload)
            if item.get("sport") not in ("Box", "HIIT", "Dance", "Other"):
                item["sport"] = "Box"
                db.execute("UPDATE challenges SET payload = ? WHERE id = ?", (json.dumps(item), challenge_id))
        if PROFILE_FILE.exists() and not db.execute("SELECT 1 FROM user_data WHERE key = 'profile'").fetchone():
            db.execute("INSERT INTO user_data VALUES ('profile', ?)", (PROFILE_FILE.read_text(encoding="utf-8"),))
        if SESSION_FILE.exists() and not db.execute("SELECT 1 FROM sessions LIMIT 1").fetchone():
            history = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
            db.executemany("INSERT INTO sessions VALUES (?, ?)", [(key, json.dumps(value)) for key, value in history.items()])


def load_moves():
    ensure_data()
    with _connection() as db:
        return [Move.from_dict(json.loads(row[0])) for row in db.execute("SELECT payload FROM moves ORDER BY rowid")]


def save_moves(moves):
    ensure_data()
    with _connection() as db:
        db.execute("DELETE FROM moves")
        db.executemany("INSERT INTO moves VALUES (?, ?)", [(move.id, json.dumps(move.to_dict())) for move in moves])


def load_challenges():
    ensure_data()
    with _connection() as db:
        return [Challenge.from_dict(json.loads(row[0])) for row in db.execute("SELECT payload FROM challenges ORDER BY position")]


def save_challenges(challenges):
    ensure_data()
    with _connection() as db:
        db.execute("DELETE FROM challenges")
        db.executemany("INSERT INTO challenges VALUES (?, ?, ?, ?)", [(challenge.id, json.dumps(challenge.to_dict()), int(challenge.is_active), index) for index, challenge in enumerate(challenges)])


# Compatibility aliases for integrations written before the Challenge rename.
load_workouts = load_challenges
save_workouts = save_challenges


def load_profile():
    ensure_data()
    with _connection() as db:
        row = db.execute("SELECT payload FROM user_data WHERE key = 'profile'").fetchone()
        return json.loads(row[0]) if row else None


def save_profile(profile):
    ensure_data()
    with _connection() as db:
        db.execute("INSERT OR REPLACE INTO user_data VALUES ('profile', ?)", (json.dumps(profile),))


def load_session_history():
    ensure_data()
    with _connection() as db:
        return {row[0]: json.loads(row[1]) for row in db.execute("SELECT challenge_id, payload FROM sessions")}


def save_session_result(workout_id, result):
    history = load_session_history()
    previous = history.get(workout_id, {})
    result["completed_count"] = int(previous.get("completed_count", 0)) + 1
    result["total_score"] = int(previous.get("total_score", previous.get("score", 0))) + int(result["score"])
    history[workout_id] = result
    with _connection() as db:
        db.execute("INSERT OR REPLACE INTO sessions VALUES (?, ?)", (workout_id, json.dumps(result)))


def load_watch_device():
    ensure_data()
    with _connection() as db:
        row = db.execute("SELECT payload FROM user_data WHERE key = 'watch'").fetchone()
        return json.loads(row[0]) if row else None


def save_watch_device(device):
    ensure_data()
    with _connection() as db:
        db.execute("INSERT OR REPLACE INTO user_data VALUES ('watch', ?)", (json.dumps(device),))


def save_heart_rate_session(workout_id, started_at, samples):
    """Append raw timestamped readings; this is separate from last-session stats."""
    ensure_data()
    payload = {"challenge_id": workout_id, "started_at": started_at, "samples": samples}
    with _connection() as db:
        db.execute("INSERT INTO heart_rate_sessions (payload) VALUES (?)", (json.dumps(payload),))
