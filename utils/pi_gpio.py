import shutil
import subprocess
import threading
import time


BCM_TO_PHYSICAL_PIN = {
    2: 3,
    3: 5,
    4: 7,
    5: 29,
    6: 31,
    7: 26,
    8: 24,
    9: 21,
    10: 19,
    11: 23,
    12: 32,
    13: 33,
    14: 8,
    15: 10,
    16: 36,
    17: 11,
    18: 12,
    19: 35,
    20: 38,
    21: 40,
    22: 15,
    23: 16,
    24: 18,
    25: 22,
    26: 37,
    27: 13,
}


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
        self.home_switch_pins = {
            "M0_HOME": gpio_config.get("m0_home_pin", 23),
            "M1_HOME": gpio_config.get("m1_home_pin", 24),
        }
        self.input_pins = {**self.button_pins, **self.home_switch_pins}
        self.led_pins = {
            "READY": gpio_config.get("ready_led_pin", 5),
            "RUNNING": gpio_config.get("running_led_pin", 6),
            "FAULT": gpio_config.get("fault_led_pin", 13),
        }
        self.gpiod_chip = gpio_config.get("gpiod_chip")
        self.button_active_high = bool(gpio_config.get("buttons_active_high", True))
        self.button_pull_up = bool(gpio_config.get("buttons_pull_up", not self.button_active_high))
        self.home_switches_normally_closed = bool(
            gpio_config.get("home_switches_normally_closed", True)
        )
        self.home_switches_active_high = bool(
            gpio_config.get("home_switches_active_high", self.home_switches_normally_closed)
        )
        self.home_switch_pull_up = bool(gpio_config.get("home_switch_pull_up", True))
        self.default_led_active_high = bool(gpio_config.get("leds_active_high", True))
        self.led_active_high = {
            "READY": bool(gpio_config.get("ready_led_active_high", self.default_led_active_high)),
            "RUNNING": bool(gpio_config.get("running_led_active_high", self.default_led_active_high)),
            "FAULT": bool(gpio_config.get("fault_led_active_high", self.default_led_active_high)),
        }
        self.available = self.enabled and GPIO is not None
        self.backend = "RPi.GPIO" if self.available else None
        self.output_backend = "RPi.GPIO" if self.available else None
        self.backend_error = "" if GPIO is not None else GPIO_IMPORT_ERROR
        self.output_error = ""
        self._lock = threading.Lock()
        self._pending_event = "NONE"
        self._button_states = {name: False for name in self.button_pins}
        self._home_switch_states = {name: False for name in self.home_switch_pins}
        self._led_states = {name: False for name in self.led_pins}
        self._raw_led_levels = None
        self._led_output_states = {name: None for name in self.led_pins}
        self._gpioset_processes = {name: None for name in self.led_pins}

        if self.available:
            try:
                GPIO.setwarnings(False)
                GPIO.setmode(GPIO.BCM)

                button_pull_mode = GPIO.PUD_UP if self.button_pull_up else GPIO.PUD_DOWN
                home_pull_mode = GPIO.PUD_UP if self.home_switch_pull_up else GPIO.PUD_DOWN

                for pin in self.button_pins.values():
                    GPIO.setup(pin, GPIO.IN, pull_up_down=button_pull_mode)

                for pin in self.home_switch_pins.values():
                    if pin not in self.button_pins.values():
                        GPIO.setup(pin, GPIO.IN, pull_up_down=home_pull_mode)

                for name, pin in self.led_pins.items():
                    GPIO.setup(pin, GPIO.OUT, initial=self._encode_output(name, False))

                initial_states = self._read_inputs()
                self._button_states = {
                    name: initial_states[name]
                    for name in self.button_pins
                }
                self._home_switch_states = {
                    name: initial_states[name]
                    for name in self.home_switch_pins
                }
            except Exception as exc:
                self.available = False
                self.backend = None
                self.backend_error = str(exc)

        if not self.available and self.enabled and shutil.which("gpioget") is not None:
            self.backend = "gpioget"
            if shutil.which("pinctrl") is not None:
                self.output_backend = "pinctrl"
            elif shutil.which("gpioset") is not None:
                self.output_backend = "gpioset"
            else:
                self.output_backend = None
            self.available = True
            self.backend_error = ""
            try:
                initial_states = self._read_inputs()
                self._button_states = {
                    name: initial_states[name]
                    for name in self.button_pins
                }
                self._home_switch_states = {
                    name: initial_states[name]
                    for name in self.home_switch_pins
                }
            except Exception as exc:
                self.available = False
                self.backend = None
                self.output_backend = None
                self.backend_error = str(exc)

    def _encode_output(self, name: str, is_on: bool):
        if not self.available or self.backend != "RPi.GPIO":
            return is_on
        return GPIO.HIGH if (is_on == self.led_active_high[name]) else GPIO.LOW

    def _encode_gpioset_output(self, name: str, is_on: bool) -> str:
        return "1" if (is_on == self.led_active_high[name]) else "0"

    def _physical_pin(self, bcm_pin):
        return BCM_TO_PHYSICAL_PIN.get(bcm_pin, "unknown")

    def _decode_input(self, raw_value: int) -> bool:
        return bool(raw_value) if self.button_active_high else not bool(raw_value)

    def _decode_named_input(self, name: str, raw_value: int) -> bool:
        if name in self.home_switch_pins:
            return bool(raw_value) if self.home_switches_active_high else not bool(raw_value)
        return self._decode_input(raw_value)

    def _read_buttons(self):
        if not self.available:
            return dict(self._button_states)
        raw_states = self._read_input_raws()
        return {
            name: self._decode_named_input(name, raw_states[name])
            for name in self.button_pins
        }

    def _read_inputs(self):
        if not self.available:
            return {**self._button_states, **self._home_switch_states}
        raw_states = self._read_input_raws()
        return {
            name: self._decode_named_input(name, raw_states[name])
            for name in self.input_pins
        }

    def _read_input_raws(self):
        if not self.available:
            return {name: "NA" for name in self.input_pins}
        if self.backend == "gpioget":
            return self._read_input_raws_gpioget()
        return {
            name: GPIO.input(pin)
            for name, pin in self.input_pins.items()
        }

    def _gpioget_raws_for_pins(self, pins, pull_up: bool):
        bias = "pull-up" if pull_up else "pull-down"
        pin_numbers = [str(pin) for pin in pins.values()]
        line_names = [f"GPIO{pin}" for pin in pins.values()]
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
            for name, value in zip(pins.keys(), values)
        }

    def _read_input_raws_gpioget(self):
        raw_states = {}
        raw_states.update(self._gpioget_raws_for_pins(self.button_pins, self.button_pull_up))
        raw_states.update(self._gpioget_raws_for_pins(
            self.home_switch_pins,
            self.home_switch_pull_up,
        ))
        return raw_states

    def _stop_gpioset_process(self, name=None):
        if name is None:
            for led_name in list(self._gpioset_processes):
                self._stop_gpioset_process(led_name)
            return

        process = self._gpioset_processes.get(name)
        self._gpioset_processes[name] = None
        self._led_output_states[name] = None
        if process is None:
            return
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=0.5)

    def _gpioset_command_mentions_pin(self, command_text: str, pin: int) -> bool:
        for token in command_text.replace(",", " ").split():
            if token.startswith(f"{pin}=") or token.startswith(f"GPIO{pin}="):
                return True
        return False

    def _clear_stale_gpioset_holders(self, pins=None):
        pins = list(pins or self.led_pins.values())
        if not pins:
            return

        try:
            result = subprocess.run(
                ["pgrep", "-af", "gpioset"],
                capture_output=True,
                check=False,
                text=True,
                timeout=0.3,
            )
        except Exception:
            return

        process_lines = result.stdout.splitlines()
        if not process_lines:
            try:
                ps_result = subprocess.run(
                    ["ps", "-eo", "pid=,args="],
                    capture_output=True,
                    check=False,
                    text=True,
                    timeout=0.5,
                )
                process_lines = [
                    line for line in ps_result.stdout.splitlines()
                    if "gpioset" in line
                ]
            except Exception:
                process_lines = []

        stale_pids = []
        for line in process_lines:
            parts = line.strip().split(maxsplit=1)
            if len(parts) != 2:
                continue

            pid, command_text = parts
            if any(self._gpioset_command_mentions_pin(command_text, pin) for pin in pins):
                stale_pids.append(pid)

        for pid in stale_pids:
            try:
                subprocess.run(
                    ["kill", "-TERM", pid],
                    capture_output=True,
                    check=False,
                    timeout=0.3,
                )
            except Exception:
                pass

        if stale_pids:
            time.sleep(0.05)

    def _gpioset_attempts_for_led(self, name):
        value = self._encode_gpioset_output(name, self._led_states[name])
        pin = self.led_pins[name]
        pin_assignment = f"{pin}={value}"
        line_assignment = f"GPIO{pin}={value}"

        attempts = []
        if self.gpiod_chip:
            attempts.append(["gpioset", "-c", str(self.gpiod_chip), pin_assignment])
        attempts.append(["gpioset", "--by-name", line_assignment])
        attempts.append(["gpioset", "-c", "gpiochip0", pin_assignment])
        attempts.append(["gpioset", "-c", "gpiochip4", pin_assignment])
        return attempts

    def _set_led_gpioset(self, name):
        desired_state = self._led_states[name]
        process = self._gpioset_processes.get(name)
        if (
            self._led_output_states.get(name) == desired_state
            and process is not None
            and process.poll() is None
        ):
            return

        self._stop_gpioset_process(name)
        self._clear_stale_gpioset_holders([self.led_pins[name]])

        last_error = "gpioset failed"
        for command in self._gpioset_attempts_for_led(name):
            try:
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                try:
                    stdout, stderr = process.communicate(timeout=0.15)
                except subprocess.TimeoutExpired:
                    self._gpioset_processes[name] = process
                    self._led_output_states[name] = desired_state
                    return

                detail = (stderr or stdout or f"exit {process.returncode}").strip()
                last_error = f"{' '.join(command)} -> {detail}"
            except Exception as exc:
                last_error = f"{' '.join(command)} -> {exc}"

        self._led_output_states[name] = None
        raise RuntimeError(f"{name}: {last_error}")

    def _set_leds_gpioset(self):
        errors = []
        for name in self.led_pins:
            try:
                self._set_led_gpioset(name)
            except Exception as exc:
                errors.append(str(exc))

        if errors:
            self.output_error = "; ".join(errors)
            raise RuntimeError(self.output_error)

        self.output_error = ""

    def _read_output_level_int(self, pin):
        level = self._read_output_level(pin)
        if level in (0, 1):
            return int(level)
        text = str(level).strip()
        if text in {"0", "1"}:
            return int(text)
        return None

    def _set_pin_pinctrl(self, pin: int, high: bool, label: str = "GPIO"):
        level = "dh" if high else "dl"
        command = ["pinctrl", "set", str(pin), "op", "pn", level]
        last_error = ""

        for _attempt in range(3):
            try:
                subprocess.run(
                    command,
                    capture_output=True,
                    check=True,
                    text=True,
                    timeout=0.5,
                )
            except Exception as exc:
                stderr = getattr(exc, "stderr", "") or ""
                stdout = getattr(exc, "stdout", "") or ""
                detail = (stderr or stdout or str(exc)).strip()
                last_error = f"{' '.join(command)} -> {detail}"
                continue

            actual = self._read_output_level_int(pin)
            if actual is None or actual == int(high):
                return

            last_error = (
                f"{' '.join(command)} -> requested {int(high)} but read back {actual}"
            )
            time.sleep(0.02)

        self.output_error = f"{label}: {last_error}"
        raise RuntimeError(self.output_error)

    def _set_leds_pinctrl(self):
        errors = []
        for name, pin in self.led_pins.items():
            desired_high = self._led_states[name] == self.led_active_high[name]
            if self._led_output_states.get(name) == desired_high:
                continue
            try:
                self._set_pin_pinctrl(pin, desired_high, name)
                self._led_output_states[name] = desired_high
            except Exception as exc:
                self._led_output_states[name] = None
                errors.append(str(exc))

        if errors:
            self.output_error = "; ".join(errors)
            raise RuntimeError(self.output_error)

        self.output_error = ""

    def _set_led_levels_pinctrl(self, levels):
        errors = []
        for name, pin in self.led_pins.items():
            if self._led_output_states.get(name) == levels[name]:
                continue
            try:
                self._set_pin_pinctrl(pin, levels[name], name)
                self._led_output_states[name] = levels[name]
            except Exception as exc:
                self._led_output_states[name] = None
                errors.append(str(exc))

        if errors:
            self.output_error = "; ".join(errors)
            raise RuntimeError(self.output_error)

        self.output_error = ""

    def set_gpio_level(self, pin, high: bool) -> str:
        with self._lock:
            try:
                bcm_pin = int(pin)
            except (TypeError, ValueError):
                raise ValueError(f"invalid GPIO pin {pin!r}")

            if bcm_pin not in BCM_TO_PHYSICAL_PIN:
                raise ValueError(f"GPIO{bcm_pin} is not in the known 40-pin header map")

            if not self.available:
                raise RuntimeError("GPIO is not available")

            if self.output_backend == "RPi.GPIO":
                GPIO.setup(bcm_pin, GPIO.OUT)
                GPIO.output(bcm_pin, GPIO.HIGH if high else GPIO.LOW)
            elif self.output_backend == "pinctrl":
                self._set_pin_pinctrl(bcm_pin, high, f"GPIO{bcm_pin}")
            else:
                self.output_error = "raw GPIO probe requires RPi.GPIO or pinctrl backend"
                raise RuntimeError(self.output_error)

            self.output_error = ""
            return (
                f"GPIO_PIN_LEVEL:GPIO={bcm_pin},"
                f"PHYSICAL_PIN={self._physical_pin(bcm_pin)},"
                f"REQUESTED={int(bool(high))},"
                f"LEVEL={self._read_output_level(bcm_pin)},"
                f"BACKEND={self.output_backend or 'none'},"
                f"ERROR=none"
            )

    def _read_output_level(self, pin):
        if self.output_backend == "RPi.GPIO" and self.available:
            try:
                return int(GPIO.input(int(pin)))
            except Exception:
                return "NA"

        if self.output_backend != "pinctrl":
            return "NA"

        try:
            result = subprocess.run(
                ["pinctrl", "lev", str(pin)],
                capture_output=True,
                check=True,
                text=True,
                timeout=0.5,
            )
            return result.stdout.strip() or "NA"
        except Exception:
            return "NA"

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
                current_states = self._read_inputs()
            except Exception as exc:
                self.backend_error = str(exc)
                return
            for name in self.button_pins:
                current = current_states[name]
                previous = self._button_states.get(name, False)
                if current and not previous:
                    self._latch_event(name)
                self._button_states[name] = current
            for name in self.home_switch_pins:
                self._home_switch_states[name] = current_states[name]

    def get_event(self) -> str:
        self.poll()
        with self._lock:
            event_name = self._pending_event
            self._pending_event = "NONE"
            return event_name

    def input_summary(self) -> str:
        with self._lock:
            try:
                raw_states = self._read_input_raws()
            except Exception as exc:
                self.backend_error = str(exc)
                raw_states = {name: "NA" for name in self.input_pins}
                current_states = {**self._button_states, **self._home_switch_states}
            else:
                current_states = {
                    name: self._decode_named_input(name, raw_states[name])
                    for name in self.input_pins
                }
                for name in self.button_pins:
                    current = current_states[name]
                    previous = self._button_states.get(name, False)
                    if current and not previous:
                        self._latch_event(name)
                    self._button_states[name] = current
                for name in self.home_switch_pins:
                    self._home_switch_states[name] = current_states[name]
            return (
                f"GPIO_INPUTS:START={int(current_states['START'])},"
                f"STOP={int(current_states['STOP'])},"
                f"HOME={int(current_states['HOME'])},"
                f"M0_HOME={int(current_states['M0_HOME'])},"
                f"M1_HOME={int(current_states['M1_HOME'])},"
                f"START_RAW={raw_states['START']},"
                f"STOP_RAW={raw_states['STOP']},"
                f"HOME_RAW={raw_states['HOME']},"
                f"M0_HOME_RAW={raw_states['M0_HOME']},"
                f"M1_HOME_RAW={raw_states['M1_HOME']}"
            )

    def config_summary(self) -> str:
        error_parts = []
        if self.backend_error:
            error_parts.append(self.backend_error)
        if self.output_error:
            error_parts.append(self.output_error)
        error = "; ".join(error_parts).replace(",", ";") if error_parts else "none"
        backend = self.backend or "none"
        output_backend = self.output_backend or "none"
        return (
            f"GPIO_CONFIG:AVAILABLE={int(self.available)},"
            f"ENABLED={int(self.enabled)},"
            f"BACKEND={backend},"
            f"LED_BACKEND={output_backend},"
            f"GPIOD_CHIP={self.gpiod_chip or 'auto'},"
            f"BUTTON_ACTIVE_HIGH={int(self.button_active_high)},"
            f"BUTTON_PULL_UP={int(self.button_pull_up)},"
            f"HOME_SWITCH_NC={int(self.home_switches_normally_closed)},"
            f"HOME_SWITCH_ACTIVE_HIGH={int(self.home_switches_active_high)},"
            f"HOME_SWITCH_PULL_UP={int(self.home_switch_pull_up)},"
            f"LED_ACTIVE_HIGH={int(self.default_led_active_high)},"
            f"READY_LED_ACTIVE_HIGH={int(self.led_active_high['READY'])},"
            f"RUNNING_LED_ACTIVE_HIGH={int(self.led_active_high['RUNNING'])},"
            f"FAULT_LED_ACTIVE_HIGH={int(self.led_active_high['FAULT'])},"
            f"START_PIN={self.button_pins['START']},"
            f"STOP_PIN={self.button_pins['STOP']},"
            f"HOME_PIN={self.button_pins['HOME']},"
            f"M0_HOME_PIN={self.home_switch_pins['M0_HOME']},"
            f"M1_HOME_PIN={self.home_switch_pins['M1_HOME']},"
            f"READY_LED_PIN={self.led_pins['READY']},"
            f"READY_LED_PHYSICAL_PIN={self._physical_pin(self.led_pins['READY'])},"
            f"RUNNING_LED_PIN={self.led_pins['RUNNING']},"
            f"RUNNING_LED_PHYSICAL_PIN={self._physical_pin(self.led_pins['RUNNING'])},"
            f"FAULT_LED_PIN={self.led_pins['FAULT']},"
            f"FAULT_LED_PHYSICAL_PIN={self._physical_pin(self.led_pins['FAULT'])},"
            f"ERROR={error}"
        )

    def set_leds(self, ready: bool, running: bool, fault: bool):
        with self._lock:
            self._raw_led_levels = None
            self._led_states["READY"] = ready
            self._led_states["RUNNING"] = running
            self._led_states["FAULT"] = fault
            if not self.available:
                return
            if self.output_backend == "RPi.GPIO":
                GPIO.output(self.led_pins["READY"], self._encode_output("READY", ready))
                GPIO.output(self.led_pins["RUNNING"], self._encode_output("RUNNING", running))
                GPIO.output(self.led_pins["FAULT"], self._encode_output("FAULT", fault))
            elif self.output_backend == "gpioset":
                self._set_leds_gpioset()
            elif self.output_backend == "pinctrl":
                self._set_leds_pinctrl()
            else:
                self.output_error = "no GPIO output backend available"

    def set_led_levels(self, ready_high: bool, running_high: bool, fault_high: bool):
        with self._lock:
            levels = {
                "READY": bool(ready_high),
                "RUNNING": bool(running_high),
                "FAULT": bool(fault_high),
            }
            self._raw_led_levels = levels
            if not self.available:
                return
            if self.output_backend == "RPi.GPIO":
                GPIO.output(self.led_pins["READY"], GPIO.HIGH if levels["READY"] else GPIO.LOW)
                GPIO.output(self.led_pins["RUNNING"], GPIO.HIGH if levels["RUNNING"] else GPIO.LOW)
                GPIO.output(self.led_pins["FAULT"], GPIO.HIGH if levels["FAULT"] else GPIO.LOW)
            elif self.output_backend == "pinctrl":
                self._set_led_levels_pinctrl(levels)
            else:
                self.output_error = "raw GPIO LED levels require RPi.GPIO or pinctrl backend"

    def test_leds(self, hold_s: float = 0.5) -> str:
        with self._lock:
            original_states = dict(self._led_states)
            steps = [
                ("GREEN", {"READY": True, "RUNNING": False, "FAULT": False}),
                ("BLUE", {"READY": True, "RUNNING": True, "FAULT": False}),
                ("RED", {"READY": True, "RUNNING": False, "FAULT": True}),
                ("RESTORE", original_states),
            ]
            summaries = []

            for label, states in steps:
                self._led_states.update(states)
                if self.available:
                    if self.output_backend == "RPi.GPIO":
                        GPIO.output(
                            self.led_pins["READY"],
                            self._encode_output("READY", self._led_states["READY"]),
                        )
                        GPIO.output(
                            self.led_pins["RUNNING"],
                            self._encode_output("RUNNING", self._led_states["RUNNING"]),
                        )
                        GPIO.output(
                            self.led_pins["FAULT"],
                            self._encode_output("FAULT", self._led_states["FAULT"]),
                        )
                    elif self.output_backend == "gpioset":
                        self._set_leds_gpioset()
                    elif self.output_backend == "pinctrl":
                        self._set_leds_pinctrl()
                    else:
                        self.output_error = "no GPIO output backend available"

                summaries.append(
                    f"{label}:READY={int(self._led_states['READY'])}/L{self._read_output_level(self.led_pins['READY'])},"
                    f"RUNNING={int(self._led_states['RUNNING'])}/L{self._read_output_level(self.led_pins['RUNNING'])},"
                    f"FAULT={int(self._led_states['FAULT'])}/L{self._read_output_level(self.led_pins['FAULT'])}"
                )
                if label != "RESTORE":
                    time.sleep(hold_s)

            return "GPIO_LED_TEST:" + ";".join(summaries)

    def output_summary(self) -> str:
        with self._lock:
            return (
                f"GPIO_OUTPUTS:READY={int(self._led_states['READY'])},"
                f"RUNNING={int(self._led_states['RUNNING'])},"
                f"FAULT={int(self._led_states['FAULT'])},"
                f"RAW_OVERRIDE={int(self._raw_led_levels is not None)},"
                f"READY_RAW={int(self._raw_led_levels['READY']) if self._raw_led_levels else 'NA'},"
                f"RUNNING_RAW={int(self._raw_led_levels['RUNNING']) if self._raw_led_levels else 'NA'},"
                f"FAULT_RAW={int(self._raw_led_levels['FAULT']) if self._raw_led_levels else 'NA'},"
                f"READY_LEVEL={self._read_output_level(self.led_pins['READY'])},"
                f"RUNNING_LEVEL={self._read_output_level(self.led_pins['RUNNING'])},"
                f"FAULT_LEVEL={self._read_output_level(self.led_pins['FAULT'])},"
                f"BACKEND={self.output_backend or 'none'},"
                f"ERROR={self.output_error.replace(',', ';') if self.output_error else 'none'}"
            )

    def cleanup(self):
        self._stop_gpioset_process()
        if self.available and self.backend == "RPi.GPIO":
            GPIO.cleanup()
