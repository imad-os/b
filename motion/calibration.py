import statistics


def build_calibration(frames_by_hand):
    """Build a neutral/rest profile. User and developer profiles can be stored separately."""
    hands = {}
    for hand, frames in frames_by_hand.items():
        if len(frames) < 20:
            continue
        accel = list(zip(*(frame.accel for frame in frames)))
        gyro = list(zip(*(frame.gyro for frame in frames)))
        accel_bias = [statistics.fmean(axis) for axis in accel]
        gyro_bias = [statistics.fmean(axis) for axis in gyro]
        # Noise floor is measured rather than assumed. It controls segmentation sensitivity.
        energy = [sum((frame.accel[i] - accel_bias[i]) ** 2 for i in range(3)) ** .5 +
                  .015 * sum((frame.gyro[i] - gyro_bias[i]) ** 2 for i in range(3)) ** .5 for frame in frames]
        noise = max(.05, statistics.pstdev(energy))
        hands[hand.upper()] = {
            "accel_bias": accel_bias,
            "gyro_bias": gyro_bias,
            "still_threshold": max(.25, noise * 3.0),
            "start_threshold": max(.8, noise * 9.0),
            "sample_count": len(frames),
        }
    return {"version": 1, "hands": hands}
