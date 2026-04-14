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
        "m0_home_pin": 23,
        "m1_home_pin": 24,
        "ready_led_pin": 5,
        "running_led_pin": 6,
        "fault_led_pin": 13,
        "buttons_active_high": False,
        "buttons_pull_up": True,
        "home_switches_normally_closed": True,
        "home_switches_active_high": True,
        "home_switch_pull_up": True,
        "validation_sensors_enabled": True,
        "roll_prox_pin": 20,
        "tilt_prox_pin": 21,
        "validation_sensor_active_high": False,
        "validation_sensor_pull_up": True,
        "leds_active_high": True,
        "ready_led_active_high": True,
        "running_led_active_high": True,
        "fault_led_active_high": True,
    },
}

def load_config():
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r") as f:
            config = json.load(f)
            merged = DEFAULT_CONFIG.copy()
            merged.update(config)
            merged["pi_gpio"] = DEFAULT_CONFIG["pi_gpio"].copy()
            merged["pi_gpio"].update(config.get("pi_gpio", {}))
            return merged
    return DEFAULT_CONFIG.copy()

def save_config(config):
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=4)
