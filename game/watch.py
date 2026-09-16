"""Optional BLE Heart Rate service client.

Garmin watches expose heart-rate broadcasting through the standard Bluetooth
SIG Heart Rate service, so this module also works with other BLE HR monitors.
It intentionally keeps BLE on a background thread: Pygame's render loop must
never wait for a scan or connection.
"""
import asyncio
import threading
import time
from datetime import datetime, timezone

from game.data import load_watch_device, save_watch_device

HEART_RATE_SERVICE = "0000180d-0000-1000-8000-00805f9b34fb"
HEART_RATE_MEASUREMENT = "00002a37-0000-1000-8000-00805f9b34fb"
BATTERY_LEVEL = "00002a19-0000-1000-8000-00805f9b34fb"
MODEL_NUMBER = "00002a24-0000-1000-8000-00805f9b34fb"
MANUFACTURER_NAME = "00002a29-0000-1000-8000-00805f9b34fb"


def parse_heart_rate(payload):
    """Decode the Bluetooth SIG Heart Rate Measurement characteristic."""
    if len(payload) < 2:
        return None
    flags = payload[0]
    return int.from_bytes(payload[1:3], "little") if flags & 1 and len(payload) >= 3 else payload[1]


class WatchReceiver:
    """A best-effort receiver; unavailable BLE support is reported, not fatal."""

    def __init__(self):
        self._lock = threading.Lock()
        self._saved = load_watch_device() or {}
        self._state = "saved" if self._saved else "disconnected"
        self._error = ""
        self._heart_rate = None
        self._last_seen = None
        self._samples = []
        self._details = dict(self._saved.get("details", {}))
        self._thread = None
        self._stop = threading.Event()

    def snapshot(self):
        with self._lock:
            return {
                "state": self._state, "error": self._error, "heart_rate": self._heart_rate,
                "last_seen": self._last_seen, "device": dict(self._saved), "details": dict(self._details),
            }

    @property
    def connected(self):
        with self._lock:
            return self._state == "connected"

    def start(self, discover=False):
        """Start/restart a scan. Saved watches are preferred on later launches."""
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        with self._lock:
            self._state = "scanning"
            self._error = ""
        target = {} if discover else dict(self._saved)
        self._thread = threading.Thread(target=self._run, args=(target,), daemon=True, name="ble-heart-rate")
        self._thread.start()

    def stop(self):
        self._stop.set()

    def start_recording(self):
        with self._lock:
            self._samples = []

    def stop_recording(self):
        with self._lock:
            samples = list(self._samples)
            self._samples = []
        return samples

    def recent_samples(self, limit=60):
        """Return a safe copy for the live chart without exposing shared state."""
        with self._lock:
            return list(self._samples[-limit:])

    def _set_error(self, message):
        with self._lock:
            self._state = "disconnected"
            self._error = message

    def _run(self, target):
        try:
            from bleak import BleakClient, BleakScanner
        except ImportError:
            self._set_error("BLE support unavailable — install bleak")
            return
        try:
            asyncio.run(self._receive(BleakClient, BleakScanner, target))
        except Exception as exc:
            self._set_error(f"Watch connection failed: {type(exc).__name__}")

    async def _receive(self, BleakClient, BleakScanner, target):
        address = target.get("address")
        device = None
        if address:
            devices = await BleakScanner.discover(timeout=6.0, service_uuids=[HEART_RATE_SERVICE])
            device = next((item for item in devices if item.address == address), None)
        else:
            devices = await BleakScanner.discover(timeout=8.0, service_uuids=[HEART_RATE_SERVICE])
            # Prefer a device that identifies itself as Garmin, otherwise let any
            # standards-compliant HR broadcaster work (including Garmin straps).
            device = next((item for item in devices if "garmin" in (item.name or "").lower()), None)
            device = device or (devices[0] if devices else None)
        if not device:
            self._set_error("No BLE heart-rate broadcaster found")
            return

        with self._lock:
            self._state = "connecting"
        async with BleakClient(device) as client:
            if not client.is_connected:
                self._set_error("Could not connect to watch")
                return
            device_data = {"address": device.address, "name": device.name or "Garmin watch"}
            details = await self._read_details(client)
            device_data["details"] = details
            save_watch_device(device_data)
            with self._lock:
                self._saved, self._details, self._state, self._error = device_data, details, "connected", ""
            await client.start_notify(HEART_RATE_MEASUREMENT, self._on_measurement)
            while client.is_connected and not self._stop.is_set():
                await asyncio.sleep(1)
            await client.stop_notify(HEART_RATE_MEASUREMENT)
        with self._lock:
            if not self._error:
                self._state = "saved"

    async def _read_details(self, client):
        details = {"updated_at": datetime.now().astimezone().isoformat(timespec="seconds")}
        for key, characteristic in (("battery_percent", BATTERY_LEVEL), ("model", MODEL_NUMBER), ("manufacturer", MANUFACTURER_NAME)):
            try:
                value = await client.read_gatt_char(characteristic)
                details[key] = int(value[0]) if key == "battery_percent" and value else bytes(value).decode(errors="replace").strip("\0")
            except Exception:
                pass
        return details

    def _on_measurement(self, _sender, payload):
        bpm = parse_heart_rate(payload)
        if bpm is None or not 20 <= bpm <= 255:
            return
        stamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        with self._lock:
            self._heart_rate, self._last_seen = bpm, stamp
            self._samples.append({"timestamp": stamp, "bpm": bpm})
