import socket

from controllers.actuator_controller import ActuatorController
from controllers.clearcore_controller import ClearCoreController
from utils.config_manager import load_config, save_config
from utils.pi_gpio import BCM_TO_PHYSICAL_PIN, PiGpioManager
from utils.serial_ports import get_serial_ports, probe_serial_port

HOST = "0.0.0.0"
PORT = 5000

config = load_config()
gpio = PiGpioManager(config)
serial_roles = {}


def is_clearcore_role(role: str) -> bool:
    return role == "ClearCore"


def is_actuator_role(role: str) -> bool:
    return role == "Arduino"


def probe_role(port: str):
    for port_info in get_serial_ports():
        if port_info.get("device") == port:
            role = port_info.get("role", "Unknown")
            detail = port_info.get("role_detail", "")
            baudrate = port_info.get("baudrate")
            if role != "Unknown":
                serial_roles[port] = (role, detail, baudrate)
                return role, detail, baudrate

    role, detail, baudrate = probe_serial_port(port)
    serial_roles[port] = (role, detail, baudrate)
    return role, detail, baudrate


def configure_serial_controllers():
    clearcore_port = config["clearcore_port"]
    actuator_port = config["arduino_port"]

    clearcore_role, clearcore_detail, clearcore_baudrate = probe_role(clearcore_port)
    actuator_role, actuator_detail, actuator_baudrate = probe_role(actuator_port)

    if is_actuator_role(clearcore_role) and is_clearcore_role(actuator_role):
        print(
            "Configured serial ports appear swapped; using "
            f"ClearCore={actuator_port} and Arduino={clearcore_port}"
        )
        clearcore_port, actuator_port = actuator_port, clearcore_port
        clearcore_role, actuator_role = actuator_role, clearcore_role
        clearcore_detail, actuator_detail = actuator_detail, clearcore_detail
        clearcore_baudrate, actuator_baudrate = actuator_baudrate, clearcore_baudrate

    print(f"ClearCore port probe: {clearcore_port} -> {clearcore_role} ({clearcore_detail})")
    print(f"Arduino port probe: {actuator_port} -> {actuator_role} ({actuator_detail})")

    return (
        ClearCoreController(port=clearcore_port, baudrate=clearcore_baudrate or 9600),
        ActuatorController(port=actuator_port, baudrate=actuator_baudrate or 9600),
    )


clearcore, actuator = configure_serial_controllers()


def is_actuator_command(cmd: str) -> bool:
    return cmd in {
        "EXTEND",
        "RETRACT",
        "HOME",
        "HOME_ACTUATOR",
        "RETRACT_TO_HOME",
        "STOP",
        "STOP_ACTUATOR",
        "STATUS_ACTUATOR",
        "LIMITS",
        "CLEAR_FAULT",
        "CYCLE",
        "DIAG",
        "DIAGNOSTICS",
        "SENSORS",
    }


def handle_gpio_command(cmd: str):
    if cmd == "GPIO_EVENTS":
        return f"EVENT:{gpio.get_event()}"

    if cmd == "GPIO_INPUTS":
        return gpio.input_summary()

    if cmd == "GPIO_OUTPUTS":
        return gpio.output_summary()

    if cmd == "GPIO_VALIDATION_INPUTS":
        return gpio.validation_input_summary()

    if cmd.startswith("GPIO_CONFIG_VALIDATION_SENSORS:"):
        payload = cmd.split(":", 1)[1]
        parts = [part.strip() for part in payload.split(",")]
        if len(parts) != 5:
            return "ERR GPIO_CONFIG_VALIDATION_SENSORS"

        try:
            enabled = parts[0] == "1"
            roll_pin = int(parts[1])
            tilt_pin = int(parts[2])
            active_high = parts[3] == "1"
            pull_up = parts[4] == "1"
        except ValueError:
            return "ERR GPIO_CONFIG_VALIDATION_SENSORS invalid value"
        if roll_pin == tilt_pin:
            return "ERR GPIO_CONFIG_VALIDATION_SENSORS roll and tilt pins must differ"
        if roll_pin not in BCM_TO_PHYSICAL_PIN or tilt_pin not in BCM_TO_PHYSICAL_PIN:
            return "ERR GPIO_CONFIG_VALIDATION_SENSORS pin is not on the known 40-pin header"

        gpio_config = config.setdefault("pi_gpio", {})
        gpio_config["validation_sensors_enabled"] = enabled
        gpio_config["roll_prox_pin"] = roll_pin
        gpio_config["tilt_prox_pin"] = tilt_pin
        gpio_config["validation_sensor_active_high"] = active_high
        gpio_config["validation_sensor_pull_up"] = pull_up
        save_config(config)
        return gpio.configure_validation_sensors(
            enabled,
            roll_pin,
            tilt_pin,
            active_high,
            pull_up,
        )

    if cmd == "GPIO_TEST_LEDS":
        return gpio.test_leds()

    if cmd.startswith("GPIO_SET_LEDS:"):
        payload = cmd.split(":", 1)[1]
        parts = [part.strip() for part in payload.split(",")]
        if len(parts) != 3:
            return "ERR GPIO_SET_LEDS"

        ready = parts[0] == "1"
        running = parts[1] == "1"
        fault = parts[2] == "1"
        gpio.set_leds(ready, running, fault)
        return "OK GPIO_SET_LEDS"

    if cmd.startswith("GPIO_SET_LED_LEVELS:"):
        payload = cmd.split(":", 1)[1]
        parts = [part.strip() for part in payload.split(",")]
        if len(parts) != 3:
            return "ERR GPIO_SET_LED_LEVELS"

        ready_high = parts[0] == "1"
        running_high = parts[1] == "1"
        fault_high = parts[2] == "1"
        gpio.set_led_levels(ready_high, running_high, fault_high)
        return "OK GPIO_SET_LED_LEVELS"

    if cmd.startswith("GPIO_SET_PIN_LEVEL:"):
        payload = cmd.split(":", 1)[1]
        parts = [part.strip() for part in payload.split(",")]
        if len(parts) != 2:
            return "ERR GPIO_SET_PIN_LEVEL"

        try:
            pin = int(parts[0])
            high = parts[1] == "1"
            return gpio.set_gpio_level(pin, high)
        except Exception as exc:
            return f"ERR GPIO_SET_PIN_LEVEL {str(exc).replace(',', ';')}"

    return None


def serial_ports_summary() -> str:
    parts = []
    for port in get_serial_ports():
        parts.append(
            f"{port['device']}={port.get('role', 'Unknown')}({port.get('role_detail', '')})"
        )
    return "SERIAL_PORTS:" + (";".join(parts) if parts else "none")


def validate_controller_role(controller, expected_role: str):
    role, detail, _baudrate = serial_roles.get(controller.port, ("Unknown", "not probed", None))
    if expected_role == "ClearCore" and not is_clearcore_role(role):
        return f"ERR CLEARCORE_PORT_MISMATCH {controller.port} role={role} detail={detail}"
    if expected_role == "Arduino" and not is_actuator_role(role):
        return f"ERR ARDUINO_PORT_MISMATCH {controller.port} role={role} detail={detail}"
    return None


def handle_command(cmd: str) -> str:
    global clearcore, actuator

    print(f"Received from GUI: {cmd}")

    if cmd == "PING":
        return "PONG"

    if cmd == "GPIO_CONFIG":
        return gpio.config_summary()

    if cmd == "SERIAL_PORTS":
        return serial_ports_summary()

    gpio_response = handle_gpio_command(cmd)
    if gpio_response is not None:
        return gpio_response

    if cmd.startswith("SET_CLEARCORE_PORT:"):
        port = cmd.split(":", 1)[1].strip()
        role, detail, baudrate = probe_role(port)
        if not is_clearcore_role(role):
            return f"ERR CLEARCORE_PORT_MISMATCH {port} role={role} detail={detail}"
        try:
            clearcore.close()
        except Exception:
            pass

        clearcore = ClearCoreController(port=port, baudrate=baudrate or 9600)
        return f"OK SET_CLEARCORE_PORT {port}"

    if cmd.startswith("SET_ARDUINO_PORT:"):
        port = cmd.split(":", 1)[1].strip()
        role, detail, baudrate = probe_role(port)
        if not is_actuator_role(role):
            return f"ERR ARDUINO_PORT_MISMATCH {port} role={role} detail={detail}"
        try:
            actuator.close()
        except Exception:
            pass

        actuator = ActuatorController(port=port, baudrate=baudrate or 9600)
        return f"OK SET_ARDUINO_PORT {port}"

    if is_actuator_command(cmd):
        mismatch = validate_controller_role(actuator, "Arduino")
        if mismatch is not None:
            return mismatch
        response = actuator.send_command(cmd)
        print(f"Actuator response: {response}")
        return response

    mismatch = validate_controller_role(clearcore, "ClearCore")
    if mismatch is not None:
        return mismatch

    response = clearcore.send_command(cmd)
    print(f"ClearCore response: {response}")
    return response


with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((HOST, PORT))
    s.listen()

    print(f"Server listening on {HOST}:{PORT}")

    try:
        while True:
            conn, addr = s.accept()
            with conn:
                print(f"Connected by {addr}")
                while True:
                    data = conn.recv(1024)
                    if not data:
                        break

                    command = data.decode().strip()
                    try:
                        response = handle_command(command)
                    except Exception as e:
                        response = f"ERR {e}"

                    conn.sendall((response + "\n").encode())
    finally:
        gpio.cleanup()
