import socket

from controllers.actuator_controller import ActuatorController
from controllers.clearcore_controller import ClearCoreController
from utils.config_manager import load_config
from utils.pi_gpio import PiGpioManager

HOST = "0.0.0.0"
PORT = 5000

config = load_config()
clearcore = ClearCoreController(port=config["clearcore_port"])
actuator = ActuatorController(port=config["arduino_port"])
gpio = PiGpioManager(config)


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
    }


def handle_gpio_command(cmd: str):
    if cmd == "GPIO_EVENTS":
        return f"EVENT:{gpio.get_event()}"

    if cmd == "GPIO_INPUTS":
        return gpio.input_summary()

    if cmd == "GPIO_OUTPUTS":
        return gpio.output_summary()

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

    return None


def handle_command(cmd: str) -> str:
    global clearcore, actuator

    print(f"Received from GUI: {cmd}")

    if cmd == "PING":
        return "PONG"

    if cmd == "GPIO_CONFIG":
        return gpio.config_summary()

    gpio_response = handle_gpio_command(cmd)
    if gpio_response is not None:
        return gpio_response

    if cmd.startswith("SET_CLEARCORE_PORT:"):
        port = cmd.split(":", 1)[1].strip()
        try:
            clearcore.close()
        except Exception:
            pass

        clearcore = ClearCoreController(port=port)
        return f"OK SET_CLEARCORE_PORT {port}"

    if cmd.startswith("SET_ARDUINO_PORT:"):
        port = cmd.split(":", 1)[1].strip()
        try:
            actuator.close()
        except Exception:
            pass

        actuator = ActuatorController(port=port)
        return f"OK SET_ARDUINO_PORT {port}"

    if is_actuator_command(cmd):
        response = actuator.send_command(cmd)
        print(f"Actuator response: {response}")
        return response

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
