"""Optional Joy-Con IMU provider. The rest of Pulsebox never imports pyjoycon."""
import time
from motion.types import SensorFrame


def _axis(value, key):
    return float(value.get(key, 0.0)) if isinstance(value, dict) else 0.0


class JoyConProvider:
    def __init__(self):
        self.left = self.right = None
        self.error = None
        self.refresh()

    def refresh(self):
        """Try to discover paired Joy-Cons again without restarting Pulsebox."""
        self.left = self.right = None
        self.error = None
        try:
            from pyjoycon import JoyCon, get_L_id, get_R_id
            try:
                self.left = JoyCon(*get_L_id())
            except Exception as exc:
                self.error = f"Left Joy-Con: {exc}"
            try:
                self.right = JoyCon(*get_R_id())
            except Exception as exc:
                message = f"Right Joy-Con: {exc}"
                self.error = f"{self.error}; {message}" if self.error else message
        except Exception as exc:  # no hardware / unsupported driver is an expected state
            self.error = str(exc)
        return self.connected

    @property
    def connected(self):
        return bool(self.left or self.right)

    def poll(self):
        frames = []
        for hand, joycon in (("LEFT", self.left), ("RIGHT", self.right)):
            if not joycon:
                continue
            try:
                status = joycon.get_status()
                accel, gyro = status.get("accel", {}), status.get("gyro", {})
                frames.append(SensorFrame(time.monotonic(), hand,
                    (_axis(accel, "x"), _axis(accel, "y"), _axis(accel, "z")),
                    (_axis(gyro, "x"), _axis(gyro, "y"), _axis(gyro, "z"))))
            except Exception as exc:
                self.error = str(exc)
        return frames
