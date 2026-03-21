import socket
from controllers.clearcore_controller import ClearCoreController

HOST = "0.0.0.0"
PORT = 5000

clearcore = ClearCoreController(port="/dev/ttyACM1")


def handle_command(cmd: str) -> str:
    global clearcore

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