# Pulsebox

Pulsebox is a local Python/Pygame motion-boxing trainer. It presents configurable boxing challenges, scores timed responses, accepts keyboard input or calibrated Nintendo Joy-Con motion, and can record live heart-rate broadcasts from compatible BLE/Garmin devices.

## What is included

- A local fighter profile, built-in boxing moves, and an editable challenge library with `Box`, `HIIT`, `Dance`, and `Other` challenge types.
- Keyboard play and Joy-Con IMU gesture recognition based on recorded move templates.
- Scrollable, type-filtered challenge library: mouse wheel, arrow keys, and controller D-pad browse every challenge.
- Developer tools for creating/editing/activating/deleting challenges and testing a challenge with a live Joy-Con accelerometer/gyroscope panel.
- A controller reconnect action in the home screen. Pair Joy-Cons in Windows Bluetooth first, then choose **CONNECT CONTROLLERS** to rescan without restarting.
- Motion Studio for controller calibration and recording/reviewing motion templates.
- Optional background BLE heart-rate receiver with local session storage and an in-game live graph.
- SQLite-backed local persistence (with JSON seed/import files) for moves, challenges, profile, sessions, watch selection, and heart-rate readings.

## Run

Python 3.9+ is recommended.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

Other utilities:

```powershell
python motion_studio.py      # calibrate Joy-Cons and record templates
python error_dashboard.py    # inspect application logs
```

## Controls

| Screen | Keyboard | Controller / mouse |
| --- | --- | --- |
| Home | Up/Down select, Enter opens, mouse wheel scrolls, M changes input mode | D-pad selects, A/confirm opens; click Connect Controllers to rescan paired Joy-Cons |
| Challenge details | Enter starts, Esc returns | A/confirm starts, B/back returns |
| Challenge | Press the shown move key; M switches keyboard/Joy-Con; Esc ends | Joy-Con motion is matched against recorded templates |
| Developer mode | F1 opens; click Create/Edit/Delete/Test | Test launches the selected active challenge with raw live IMU telemetry |
| Motion Studio | C calibrates, R records, V reviews, P changes calibration profile | Use after pairing Joy-Cons to build gesture templates |

## Joy-Con setup

1. Pair each Joy-Con in **Windows Settings > Bluetooth & devices**.
2. In Pulsebox, click **CONNECT CONTROLLERS** to retry discovery. The button detects paired controllers; it cannot perform Windows Bluetooth pairing itself.
3. Run `python motion_studio.py`, choose the appropriate profile, and calibrate while holding a relaxed guard.
4. Record one or more clean examples for each move.
5. In a challenge, press `M` to choose Joy-Con motion input.

The development **TEST** action deliberately exposes raw accelerometer and gyroscope values plus a small live motion trace. This is for tuning and verification; normal sessions do not show it.

## Heart rate

Pulsebox listens for the standard Bluetooth Heart Rate Service. On a compatible Garmin watch, enable **Broadcast Heart Rate** and Bluetooth, then use **CONNECT WATCH**. The selected device is remembered locally and later launches attempt a background reconnection. BLE HR broadcasts may expose current BPM, battery/model/manufacturer, but not Garmin health history, steps, or arbitrary watch data.

## Layout

```text
main.py              Pygame screens, challenge flow, developer test telemetry
game/data.py         SQLite/JSON persistence
game/watch.py        background BLE heart-rate receiver
game/models.py       move and challenge models
motion/controller.py Joy-Con discovery and IMU frames
motion/              calibration, template storage, features, recognition
motion_studio.py     calibration/template authoring utility
data/                local user data (do not commit health data)
```

## Privacy

Everything stays locally in `data/`. Heart-rate samples are health data; do not commit or share this directory unintentionally.
