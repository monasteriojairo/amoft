import shutil
import subprocess
import threading


try:
    import RPi.GPIO as GPIO  # type: ignore
    GPIO_IMPORT_ERROR = ""
except Exception as exc:  # pragma: no cover - unavailable on non-Pi hosts
    GPIO = None
    GPIO_IMPORT_ERROR = str(exc)


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
        self.gpiod_chip = gpio_config.get("gpiod_chip")
        self.button_active_high = bool(gpio_config.get("buttons_active_high", True))
        self.led_active_high = bool(gpio_config.get("leds_active_high", True))
        self.available = self.enabled and GPIO is not None
        self.backend = "RPi.GPIO" if self.available else None
        self.backend_error = "" if GPIO is not None else GPIO_IMPORT_ERROR
        self._lock = threading.Lock()
        self._pending_event = "NONE"
        self._button_states = {name: False for name in self.button_pins}
        self._led_states = {name: False for name in self.led_pins}

        if self.available:
            try:
                GPIO.setwarnings(False)
                GPIO.setmode(GPIO.BCM)
                pull_mode = GPIO.PUD_DOWN if self.button_active_high else GPIO.PUD_UP

                for pin in self.button_pins.values():
                    GPIO.setup(pin, GPIO.IN, pull_up_down=pull_mode)

                for pin in self.led_pins.values():
                    GPIO.setup(pin, GPIO.OUT, initial=self._encode_output(False))

                self._button_states = self._read_buttons()
            except Exception as exc:
                self.available = False
                self.backend = None
                self.backend_error = str(exc)

        if not self.available and self.enabled and shutil.which("gpioget") is not None:
            self.backend = "gpioget"
            self.available = True
            self.backend_error = ""
            try:
                self._button_states = self._read_buttons()
            except Exception as exc:
                self.available = False
                self.backend = None
                self.backend_error = str(exc)

    def _encode_output(self, is_on: bool):
        if not self.available or self.backend != "RPi.GPIO":
            return is_on
        return GPIO.HIGH if (is_on == self.led_active_high) else GPIO.LOW

    def _decode_input(self, raw_value: int) -> bool:
        return bool(raw_value) if self.button_active_high else not bool(raw_value)

    def _read_buttons(self):
        if not self.available:
            return dict(self._button_states)
        raw_states = self._read_button_raws()
        return {
            name: self._decode_input(raw_states[name])
            for name in self.button_pins
        }

    def _read_button_raws(self):
        if not self.available:
            return {name: "NA" for name in self.button_pins}
        if self.backend == "gpioget":
            return self._read_button_raws_gpioget()
        return {
            name: GPIO.input(pin)
            for name, pin in self.button_pins.items()
        }

    def _read_button_raws_gpioget(self):
        bias = "pull-down" if self.button_active_high else "pull-up"
        pin_numbers = [str(pin) for pin in self.button_pins.values()]
        line_names = [f"GPIO{pin}" for pin in self.button_pins.values()]

        attempts = []
        if self.gpiod_chip:
            attempts.append(["gpioget", "--numeric", "-c", str(self.gpiod_chip), "-b", bias] + pin_numbers)
        attempts.append(["gpioget", "--numeric", "--by-name", "-b", bias] + line_names)
        attempts.append(["gpioget", "--numeric", "-c", "gpiochip0", "-b", bias] + pin_numbers)
        attempts.append(["gpioget", "--numeric", "-c", "gpiochip4", "-b", bias] + pin_numbers)

        last_error = "gpioget failed"
        for command in attempts:
            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    check=True,
                    text=True,
                    timeout=0.5,
                )
                break
            except Exception as exc:
                stderr = getattr(exc, "stderr", "") or ""
                stdout = getattr(exc, "stdout", "") or ""
                detail = (stderr or stdout or str(exc)).strip()
                last_error = f"{' '.join(command)} -> {detail}"
        else:
            raise RuntimeError(last_error)

        values = result.stdout.strip().replace("\n", " ").split()
        if len(values) != len(line_names):
            raise RuntimeError(f"gpioget returned {result.stdout.strip()!r}")
        return {
            name: int(value)
            for name, value in zip(self.button_pins.keys(), values)
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
            try:
                current_states = self._read_buttons()
            except Exception as exc:
                self.backend_error = str(exc)
                return
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
            try:
                raw_states = self._read_button_raws()
            except Exception as exc:
                self.backend_error = str(exc)
                raw_states = {name: "NA" for name in self.button_pins}
            return (
                f"GPIO_INPUTS:START={int(self._button_states['START'])},"
                f"STOP={int(self._button_states['STOP'])},"
                f"HOME={int(self._button_states['HOME'])},"
                f"START_RAW={raw_states['START']},"
                f"STOP_RAW={raw_states['STOP']},"
                f"HOME_RAW={raw_states['HOME']}"
            )

    def config_summary(self) -> str:
        error = self.backend_error.replace(",", ";") if self.backend_error else "none"
        backend = self.backend or "none"
        return (
            f"GPIO_CONFIG:AVAILABLE={int(self.available)},"
            f"ENABLED={int(self.enabled)},"
            f"BACKEND={backend},"
            f"GPIOD_CHIP={self.gpiod_chip or 'auto'},"
            f"BUTTON_ACTIVE_HIGH={int(self.button_active_high)},"
            f"START_PIN={self.button_pins['START']},"
            f"STOP_PIN={self.button_pins['STOP']},"
            f"HOME_PIN={self.button_pins['HOME']},"
            f"ERROR={error}"
        )

    def set_leds(self, ready: bool, running: bool, fault: bool):
        with self._lock:
            self._led_states["READY"] = ready
            self._led_states["RUNNING"] = running
            self._led_states["FAULT"] = fault
            if not self.available or self.backend != "RPi.GPIO":
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
        if self.available and self.backend == "RPi.GPIO":
            GPIO.cleanup()
