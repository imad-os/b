import time
from motion.features import similarity
from motion.storage import load_templates
from motion.types import Match


LEVEL_ACCEPTANCE = {1: .55, 2: .62, 3: .69, 4: .76, 5: .82}


class MotionRecognizer:
    """Segments active IMU data then scores it only against recorded templates."""
    def __init__(self, calibration=None):
        self.calibration = calibration or {}
        self.active = {"LEFT": [], "RIGHT": []}
        self.last_motion = {"LEFT": 0.0, "RIGHT": 0.0}

    def energy(self, frame):
        # Baseline-subtracted magnitude; gyro is down-weighted to prevent small twists.
        calibration = self._calibration_for(frame.hand)
        accel_bias = calibration.get("accel_bias", [0, 0, 0])
        gyro_bias = calibration.get("gyro_bias", [0, 0, 0])
        a = sum((frame.accel[i] - accel_bias[i]) ** 2 for i in range(3)) ** .5
        g = sum((frame.gyro[i] - gyro_bias[i]) ** 2 for i in range(3)) ** .5
        return a + .015 * g

    def feed(self, frame, expected_move, level):
        """Feed every controller frame. Returns a Match only after a complete gesture."""
        hand = frame.hand.upper()
        if hand not in self.active or hand != expected_move.hand:
            return None
        now = frame.timestamp
        start_threshold = float(self.calibration.get("start_threshold", 2.1))
        still_threshold = float(self.calibration.get("still_threshold", .65))
        current = self.active[hand]
        if not current and self.energy(frame) >= start_threshold:
            self.active[hand] = [frame]
            self.last_motion[hand] = now
            return None
        if not current:
            return None
        current.append(frame)
        if self.energy(frame) >= still_threshold:
            self.last_motion[hand] = now
        # 0.18 seconds of stillness ends a gesture; a 2.2-second cap avoids dead captures.
        if (now - self.last_motion[hand] < .18) and (now - current[0].timestamp < 2.2):
            return None
        self.active[hand] = []
        templates = [item for item in load_templates(expected_move.id) if item.get("hand", "").upper() == hand]
        if not templates:
            return Match(expected_move.id, 0.0, False, hand, "no recorded template for this side")
        best_score, detail = max((similarity(current, item["frames_as_objects"], self._calibration_for(hand)) for item in self._objects(templates)), key=lambda item: item[0])
        threshold = max(float(getattr(expected_move, "acceptance", 0.0) or 0.0), LEVEL_ACCEPTANCE.get(level, .82))
        return Match(expected_move.id, best_score, best_score >= threshold, hand, detail)

    def _calibration_for(self, hand):
        return self.calibration.get("hands", {}).get(hand.upper(), self.calibration)

    @staticmethod
    def _objects(templates):
        from motion.types import SensorFrame
        converted = []
        for item in templates:
            item = dict(item)
            item["frames_as_objects"] = [SensorFrame.from_dict(frame) for frame in item["frames"]]
            converted.append(item)
        return converted
