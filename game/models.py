from dataclasses import dataclass, asdict


@dataclass
class Move:
    id: str
    label: str
    key: str
    min_level: int
    frequency: int
    category: str
    hand: str
    acceptance: float = 0.0  # 0 delegates to the level's progressively stricter threshold

    @classmethod
    def from_dict(cls, value):
        value = dict(value)
        value.setdefault("acceptance", 0.0)
        return cls(**value)

    def to_dict(self):
        return asdict(self)


@dataclass
class Challenge:
    id: str
    title: str
    subtitle: str
    level: int
    rounds: int
    accent: tuple
    sport: str = "Box"
    move_ids: tuple = ()
    move_weights: dict = None
    is_active: bool = True

    @classmethod
    def from_dict(cls, value):
        value = dict(value)
        value["accent"] = tuple(value.get("accent", (255, 91, 83)))
        value["move_ids"] = tuple(value.get("move_ids", ()))
        value.setdefault("move_weights", {})
        value.setdefault("sport", "Box")
        value.setdefault("is_active", True)
        return cls(**value)

    def to_dict(self):
        value = asdict(self)
        value["accent"] = list(self.accent)
        value["move_ids"] = list(self.move_ids)
        return value


# Backward-compatible import for existing game modules and old JSON data.
Workout = Challenge
