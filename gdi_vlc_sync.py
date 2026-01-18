import os
import re
import time
import json
import signal
import logging
import threading
import requests
from logging.handlers import RotatingFileHandler
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# ----------------------------
# CONFIGURATION
# ----------------------------

WATCH_FOLDER = "./gdi_files"
LOG_FOLDER = "./logs"
VLC_HOST = "http://localhost:8080"
VLC_PASSWORD = "vlcpass"

TEMPLATE_MAP = {
    "deck_status.txt": "%title% %artist% %album% %genre% %label% %key% %orig_artist% %remixer% "
                       "%composer% %comment% %mix_name% %lyricist% %date_created% %date_added% "
                       "%track_number% %bpm% %time% %deck1_bpm% %deck2_bpm% %deck3_bpm% %deck4_bpm% "
                       "%master_bpm% %rt_deck1_bpm% %rt_deck2_bpm% %rt_deck3_bpm% %rt_deck4_bpm% %rt_master_bpm%"
}

latest_file_data = {}
lock = threading.Lock()
shutdown_event = threading.Event()

# ----------------------------
# LOGGING SETUP
# ----------------------------

def setup_logging():
    os.makedirs(LOG_FOLDER, exist_ok=True)
    log_path = os.path.join(LOG_FOLDER, "gdi_vlc_sync.log")

    handler = RotatingFileHandler(log_path, maxBytes=5_000_000, backupCount=3)
    console = logging.StreamHandler()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[handler, console],
    )

    logging.info("Logging initialized. Output → %s", log_path)

# ----------------------------
# FILE PARSING
# ----------------------------

def parse_gdi_file(filepath: str, template: str) -> dict:
    """Extract variable values from GDI text file using the provided template."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read().strip()
    except Exception as e:
        logging.error("Failed to read %s: %s", filepath, e)
        return {}

    regex_pattern = re.escape(template)
    regex_pattern = re.sub(r"%([a-zA-Z0-9_]+)%", r"(?P<\1>.*?)", regex_pattern)
    match = re.match(regex_pattern, content)

    if not match:
        logging.warning("Could not parse GDI file: %s", filepath)
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

        logging.info("File update detected → %s", filename)
        data = parse_gdi_file(event.src_path, TEMPLATE_MAP[filename])
        if data:
            with lock:
                latest_file_data.update(data)
            logging.info("Extracted values from %s", filename)

def start_file_monitor():
    os.makedirs(WATCH_FOLDER, exist_ok=True)
    event_handler = GDIFileHandler()
    observer = Observer()
    observer.schedule(event_handler, WATCH_FOLDER, recursive=False)
    observer.start()
    logging.info("Started monitoring folder: %s", WATCH_FOLDER)

    try:
        while not shutdown_event.is_set():
            time.sleep(1)
    except Exception as e:
        logging.error("File monitor crashed: %s", e)
    finally:
        observer.stop()
        observer.join()
        logging.info("File monitor stopped gracefully.")

# ----------------------------
# VLC INTERFACE
# ----------------------------

def vlc_get_status():
    try:
        response = requests.get(f"{VLC_HOST}/requests/status.json", auth=("", VLC_PASSWORD), timeout=3)
        if response.status_code == 200:
            return response.json()
    except requests.exceptions.RequestException as e:
        logging.warning("VLC status query failed: %s", e)
    return {}

def vlc_set_rate(rate: float):
    try:
        response = requests.get(f"{VLC_HOST}/requests/status.json?command=rate&val={rate}",
                                auth=("", VLC_PASSWORD), timeout=3)
        if response.status_code == 200:
            logging.info("Updated VLC playback rate → %.3f", rate)
    except requests.exceptions.RequestException as e:
        logging.error("VLC rate update failed: %s", e)

# ----------------------------
# SYNC ENGINE
# ----------------------------

def sync_vlc_with_bpm():
    base_bpm = None
    logging.info("Starting VLC-BPM Sync Engine...")

    while not shutdown_event.is_set():
        vlc_status = vlc_get_status()
        if not vlc_status:
            time.sleep(3)
            continue

        state = vlc_status.get("state")
        if state != "playing":
            time.sleep(2)
            continue

        current_rate = vlc_status.get("rate", 1.0)
        info = vlc_status.get("information", {})
        video_meta = info.get("category", {}).get("Stream 0", {})
        frame_rate_str = video_meta.get("Frame rate", "30")

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

        target_rate = master_bpm / base_bpm
        diff = abs(target_rate - current_rate) / current_rate

        if diff > 0.01:
            vlc_set_rate(target_rate)

        time.sleep(2)

    logging.info("VLC-BPM Sync Engine terminated.")

# ----------------------------
# SIGNAL HANDLING
# ----------------------------

def handle_shutdown(signum, frame):
    logging.info("Received shutdown signal (%s). Cleaning up...", signum)
    shutdown_event.set()

# ----------------------------
# MAIN ENTRY POINT
# ----------------------------

if __name__ == "__main__":
    setup_logging()
    logging.info("GDI-VLC Sync Service Starting...")

    # Register graceful shutdown signals
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    t1 = threading.Thread(target=start_file_monitor, daemon=True)
    t2 = threading.Thread(target=sync_vlc_with_bpm, daemon=True)

    t1.start()
    t2.start()

    while not shutdown_event.is_set():
        time.sleep(0.5)

    logging.info("GDI-VLC Sync Service main thread exiting gracefully")
