import os
import re
import time
import json
import threading
import requests
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# ----------------------------
# CONFIGURATION
# ----------------------------

WATCH_FOLDER = "./gdi_files"
VLC_HOST = "http://localhost:8080"
VLC_PASSWORD = "vlcpass"  # set in VLC > Preferences > All > Interface > Main interfaces > Lua > Password

# Mapping: filename -> template
TEMPLATE_MAP = {
    "deck_status.txt": "%title% %artist% %album% %genre% %label% %key% %orig_artist% %remixer% "
                       "%composer% %comment% %mix_name% %lyricist% %date_created% %date_added% "
                       "%track_number% %bpm% %time% %deck1_bpm% %deck2_bpm% %deck3_bpm% %deck4_bpm% "
                       "%master_bpm% %rt_deck1_bpm% %rt_deck2_bpm% %rt_deck3_bpm% %rt_deck4_bpm% %rt_master_bpm%"
}

# Global storage of parsed file data
latest_file_data = {}
lock = threading.Lock()

# ----------------------------
# FILE PARSING
# ----------------------------

def parse_gdi_file(filepath: str, template: str) -> dict:
    """Extract variable values from GDI text file using the provided template."""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read().strip()

    # Build regex from template by converting %var% into named groups
    regex_pattern = re.escape(template)
    regex_pattern = re.sub(r"%([a-zA-Z0-9_]+)%", r"(?P<\1>.*?)", regex_pattern)
    match = re.match(regex_pattern, content)

    if not match:
        print(f"[WARN] Could not parse file: {filepath}")
        return {}

    return match.groupdict()

# ----------------------------
# FILESYSTEM MONITOR
# ----------------------------

class GDIFileHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if event.is_directory:
            return

        filename = os.path.basename(event.src_path)
        if filename not in TEMPLATE_MAP:
            return

        print(f"[INFO] Detected update in {filename}")
        data = parse_gdi_file(event.src_path, TEMPLATE_MAP[filename])
        if data:
            with lock:
                latest_file_data.update(data)
            print(f"[INFO] Parsed data: {json.dumps(data, indent=2)}")


def start_file_monitor():
    os.makedirs(WATCH_FOLDER, exist_ok=True)
    event_handler = GDIFileHandler()
    observer = Observer()
    observer.schedule(event_handler, WATCH_FOLDER, recursive=False)
    observer.start()
    print(f"[INFO] Monitoring folder: {WATCH_FOLDER}")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

# ----------------------------
# VLC INTERFACE
# ----------------------------

def vlc_get_status():
    """Query VLC for playback status and metadata."""
    try:
        response = requests.get(f"{VLC_HOST}/requests/status.json", auth=("", VLC_PASSWORD))
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"[ERROR] VLC status query failed: {e}")
    return {}

def vlc_set_rate(rate: float):
    """Update VLC playback speed."""
    try:
        response = requests.get(f"{VLC_HOST}/requests/status.json?command=rate&val={rate}",
                                auth=("", VLC_PASSWORD))
        if response.status_code == 200:
            print(f"[INFO] Updated VLC rate → {rate:.3f}")
    except Exception as e:
        print(f"[ERROR] VLC rate update failed: {e}")

# ----------------------------
# SYNC ENGINE
# ----------------------------

def sync_vlc_with_bpm():
    """Continuously sync VLC playback speed with master BPM."""
    base_bpm = None

    while True:
        vlc_status = vlc_get_status()
        if not vlc_status:
            time.sleep(3)
            continue

        state = vlc_status.get("state")
        if state != "playing":
            time.sleep(2)
            continue

        # Extract video details
        current_rate = vlc_status.get("rate", 1.0)
        info = vlc_status.get("information", {})
        video_meta = info.get("category", {}).get("Stream 0", {})
        frame_rate_str = video_meta.get("Frame rate", "0")
        try:
            frame_rate = float(frame_rate_str.split()[0])
        except ValueError:
            frame_rate = 30.0

        with lock:
            master_bpm = latest_file_data.get("master_bpm")

        if not master_bpm:
            time.sleep(2)
            continue

        try:
            master_bpm = float(master_bpm)
        except ValueError:
            time.sleep(2)
            continue

        if base_bpm is None:
            base_bpm = master_bpm

        target_rate = (master_bpm / base_bpm)
        diff = abs(target_rate - current_rate) / current_rate

        if diff > 0.01:
            vlc_set_rate(target_rate)

        time.sleep(2)

# ----------------------------
# MAIN
# ----------------------------

if __name__ == "__main__":
    print("[INIT] Starting GDI-VLC Sync Service")
    t1 = threading.Thread(target=start_file_monitor, daemon=True)
    t2 = threading.Thread(target=sync_vlc_with_bpm, daemon=True)

    t1.start()
    t2.start()

    t1.join()
    t2.join()
