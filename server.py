import socket

from controllers.actuator_controller import ActuatorController
from controllers.clearcore_controller import ClearCoreController
from utils.config_manager import load_config

HOST = "0.0.0.0"
PORT = 5000

config = load_config()
clearcore = ClearCoreController(port=config["clearcore_port"])
actuator = ActuatorController(port=config["arduino_port"])


def is_actuator_command(cmd: str) -> bool:
    return cmd in {
        "EXTEND",
        "RETRACT",
        "HOME",
        "STOP",
        "STOP_ACTUATOR",
        "STATUS_ACTUATOR",
        "LIMITS",
    }


def handle_command(cmd: str) -> str:
    global clearcore, actuator

    print(f"Received from GUI: {cmd}")

    if cmd == "PING":
        return "PONG"

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
