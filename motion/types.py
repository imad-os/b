from dataclasses import dataclass, asdict


@dataclass
class SensorFrame:
    timestamp: float
    hand: str
    accel: tuple
    gyro: tuple

    def to_dict(self):
        data = asdict(self)
        data["accel"] = list(self.accel)
        data["gyro"] = list(self.gyro)
        return data

    @classmethod
    def from_dict(cls, data):
        return cls(data["timestamp"], data["hand"], tuple(data["accel"]), tuple(data["gyro"]))


@dataclass
class Match:
    move_id: str
    confidence: float
    accepted: bool
    hand: str
    detail: str = ""
