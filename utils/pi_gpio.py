import threading


try:
    import RPi.GPIO as GPIO  # type: ignore
except Exception:  # pragma: no cover - unavailable on non-Pi hosts
    GPIO = None


class PiGpioManager:
    def __init__(self, config):
        gpio_config = config.get("pi_gpio", {})
        self.enabled = bool(gpio_config.get("enabled", True))
        self.button_pins = {
            "START": gpio_config.get("start_button_pin", 17),
            "STOP": gpio_config.get("stop_button_pin", 27),
            "HOME": gpio_config.get("home_button_pin", 22),
        }
        self.led_pins = {
            "READY": gpio_config.get("ready_led_pin", 5),
            "RUNNING": gpio_config.get("running_led_pin", 6),
            "FAULT": gpio_config.get("fault_led_pin", 13),
        }
        self.button_active_high = bool(gpio_config.get("buttons_active_high", True))
        self.led_active_high = bool(gpio_config.get("leds_active_high", True))
        self.available = self.enabled and GPIO is not None
        self._lock = threading.Lock()
        self._pending_event = "NONE"
        self._button_states = {name: False for name in self.button_pins}
        self._led_states = {name: False for name in self.led_pins}

        if self.available:
            GPIO.setwarnings(False)
            GPIO.setmode(GPIO.BCM)
            pull_mode = GPIO.PUD_DOWN if self.button_active_high else GPIO.PUD_UP

            for pin in self.button_pins.values():
                GPIO.setup(pin, GPIO.IN, pull_up_down=pull_mode)

            for pin in self.led_pins.values():
                GPIO.setup(pin, GPIO.OUT, initial=self._encode_output(False))

            self._button_states = self._read_buttons()

    def _encode_output(self, is_on: bool):
        if not self.available:
            return is_on
        return GPIO.HIGH if (is_on == self.led_active_high) else GPIO.LOW

    def _decode_input(self, raw_value: int) -> bool:
        return bool(raw_value) if self.button_active_high else not bool(raw_value)

    def _read_buttons(self):
        if not self.available:
            return dict(self._button_states)
        return {
            name: self._decode_input(GPIO.input(pin))
            for name, pin in self.button_pins.items()
        }

    def _read_button_raws(self):
        if not self.available:
            return {name: "NA" for name in self.button_pins}
        return {
            name: GPIO.input(pin)
            for name, pin in self.button_pins.items()
        }

    def _latch_event(self, event_name: str):
        if self._pending_event == "NONE":
            self._pending_event = event_name
            return
        if self._pending_event == "STOP":
            return
        if event_name == "STOP":
            self._pending_event = event_name
            return
        if self._pending_event == "HOME":
            return
        if event_name == "HOME":
            self._pending_event = event_name

    def poll(self):
        with self._lock:
            current_states = self._read_buttons()
            for name, current in current_states.items():
                previous = self._button_states.get(name, False)
                if current and not previous:
                    self._latch_event(name)
                self._button_states[name] = current

    def get_event(self) -> str:
        self.poll()
        with self._lock:
            event_name = self._pending_event
            self._pending_event = "NONE"
            return event_name

    def input_summary(self) -> str:
        self.poll()
        with self._lock:
            raw_states = self._read_button_raws()
            return (
                f"GPIO_INPUTS:START={int(self._button_states['START'])},"
                f"STOP={int(self._button_states['STOP'])},"
                f"HOME={int(self._button_states['HOME'])},"
                f"START_RAW={raw_states['START']},"
                f"STOP_RAW={raw_states['STOP']},"
                f"HOME_RAW={raw_states['HOME']}"
            )

    def config_summary(self) -> str:
        return (
            f"GPIO_CONFIG:AVAILABLE={int(self.available)},"
            f"ENABLED={int(self.enabled)},"
            f"BUTTON_ACTIVE_HIGH={int(self.button_active_high)},"
            f"START_PIN={self.button_pins['START']},"
            f"STOP_PIN={self.button_pins['STOP']},"
            f"HOME_PIN={self.button_pins['HOME']}"
        )

    def set_leds(self, ready: bool, running: bool, fault: bool):
        with self._lock:
            self._led_states["READY"] = ready
            self._led_states["RUNNING"] = running
            self._led_states["FAULT"] = fault
            if not self.available:
                return
            GPIO.output(self.led_pins["READY"], self._encode_output(ready))
            GPIO.output(self.led_pins["RUNNING"], self._encode_output(running))
            GPIO.output(self.led_pins["FAULT"], self._encode_output(fault))

    def output_summary(self) -> str:
        with self._lock:
            return (
                f"GPIO_OUTPUTS:READY={int(self._led_states['READY'])},"
                f"RUNNING={int(self._led_states['RUNNING'])},"
                f"FAULT={int(self._led_states['FAULT'])}"
            )

    def cleanup(self):
        if self.available:
            GPIO.cleanup()
