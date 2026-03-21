import socket


class PiClient:
    def __init__(self, host="192.168.1.95", port=5000, timeout=2.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock = None

    def connect(self):
        if self.sock is not None:
            self.close()

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect((self.host, self.port))

    def send(self, command: str) -> str:
        if self.sock is None:
            raise RuntimeError("Not connected to Pi")

        self.sock.sendall((command + "\n").encode())
        response = self.sock.recv(1024).decode().strip()
        return response

    def close(self):
        if self.sock:
            self.sock.close()
            self.sock = None
