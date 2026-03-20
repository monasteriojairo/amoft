import json
from pathlib import Path

CONFIG_PATH = Path("config.json")

DEFAULT_CONFIG = {
    "clearcore_port": "/dev/ttyACM0",
    "arduino_port": "/dev/ttyUSB0",
    "baud_rate": 115200,
    "m1_enabled": False,
    "simulation_mode": True
}

def load_config():
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    return DEFAULT_CONFIG.copy()

def save_config(config):
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=4)