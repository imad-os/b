"""Signal cleanup and template scoring; no game/UI code lives here."""
import math
import numpy as np


SAMPLES = 48


def _vectors(frames, calibration=None):
    raw = np.array([list(frame.accel) + list(frame.gyro) for frame in frames], dtype=float)
    if len(raw) < 6:
        return None
    if calibration:
        accel_bias = np.array(calibration.get("accel_bias", [0, 0, 0]), dtype=float)
        gyro_bias = np.array(calibration.get("gyro_bias", [0, 0, 0]), dtype=float)
        raw[:, :3] -= accel_bias
        raw[:, 3:] -= gyro_bias
    return raw


def resample(frames, calibration=None, count=SAMPLES):
    values = _vectors(frames, calibration)
    if values is None:
        return None
    source = np.linspace(0.0, 1.0, len(values))
    target = np.linspace(0.0, 1.0, count)
    return np.column_stack([np.interp(target, source, values[:, i]) for i in range(6)])


def signature(frames, calibration=None):
    signal = resample(frames, calibration)
    if signal is None:
        return None
    # Direction and shape are retained; absolute resting offsets are discarded.
    energy = np.linalg.norm(signal, axis=1)
    return {
        "series": signal,
        "mean": signal.mean(axis=0),
        "std": signal.std(axis=0),
        "peak": float(energy.max()),
        "duration": max(.05, frames[-1].timestamp - frames[0].timestamp),
    }


def _cosine(a, b):
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / denom) if denom else 0.0


def similarity(candidate_frames, template_frames, calibration=None):
    """Return 0..1 confidence from aligned IMU shape, movement direction and timing.

    This deliberately combines complementary signals: a short move cannot pass merely
    because its peak is large, and a mirrored left/right shape does not score highly.
    """
    candidate = signature(candidate_frames, calibration)
    template = signature(template_frames, calibration)
    if not candidate or not template:
        return 0.0, "recording too short"
    scale = max(template["peak"], 1.0)
    shape_distance = float(np.mean(np.linalg.norm(candidate["series"] - template["series"], axis=1))) / scale
    shape_score = math.exp(-shape_distance)
    direction_score = (_cosine(candidate["mean"], template["mean"]) + 1) / 2
    timing_score = math.exp(-abs(math.log(candidate["duration"] / template["duration"])))
    confidence = max(0.0, min(1.0, .55 * shape_score + .30 * direction_score + .15 * timing_score))
    return confidence, f"shape {shape_score:.0%} · direction {direction_score:.0%} · timing {timing_score:.0%}"
