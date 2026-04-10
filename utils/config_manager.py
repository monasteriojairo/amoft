import json
from pathlib import Path

CONFIG_PATH = Path("config.json")

DEFAULT_CONFIG = {
    "clearcore_port": "/dev/ttyACM0",
    "arduino_port": "/dev/ttyUSB0",
    "baud_rate": 115200,
    "m1_enabled": False,
    "simulation_mode": True,
    "auto_sequences": {},
    "pi_gpio": {
        "enabled": True,
        "start_button_pin": 17,
        "stop_button_pin": 27,
        "home_button_pin": 22,
        "ready_led_pin": 5,
        "running_led_pin": 6,
        "fault_led_pin": 13,
        "buttons_active_high": False,
        "leds_active_high": True,
    },
}

def load_config():
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r") as f:
            config = json.load(f)
            merged = DEFAULT_CONFIG.copy()
            merged.update(config)
            return merged
    return DEFAULT_CONFIG.copy()

def save_config(config):
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=4)
