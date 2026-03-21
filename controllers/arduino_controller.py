import serial
import time


class ArduinoController:
    def __init__(self, port='/dev/ttyACM0', baudrate=9600, timeout=1):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.serial_connection = None

    def connect(self):
        """Establish connection to Arduino."""
        try:
            if self.serial_connection and self.serial_connection.is_open:
                return True

            connection = serial.Serial()
            connection.port = self.port
            connection.baudrate = self.baudrate
            connection.timeout = self.timeout
            connection.write_timeout = self.timeout
            connection.dsrdtr = False
            connection.rtscts = False
            connection.open()

            try:
                connection.setDTR(False)
                connection.setRTS(False)
            except Exception:
                pass

            self.serial_connection = connection
            time.sleep(2)  # Allow Arduino to settle if the board resets on open.
            self.serial_connection.reset_input_buffer()
            self.serial_connection.reset_output_buffer()
            self.ensure_safe_stop()
            print(f"Connected to Arduino on {self.port}")
            return True
        except serial.SerialException as e:
            print(f"Failed to connect to Arduino: {e}")
            self.serial_connection = None
            return False

    def disconnect(self):
        """Close the serial connection."""
        if self.serial_connection and self.serial_connection.is_open:
            self.serial_connection.close()
            self.serial_connection = None
            print("Disconnected from Arduino")

    def send_command(self, command):
        """Send a command to Arduino and return the response."""
        if not self.serial_connection or not self.serial_connection.is_open:
            print("Arduino not connected")
            return None

        try:
            self.serial_connection.reset_input_buffer()
            self.serial_connection.write(f"{command}\n".encode())
            response = self.serial_connection.readline().decode().strip()
            return response
        except Exception as e:
            print(f"Error sending command '{command}': {e}")
            return None

    def ensure_safe_stop(self):
        """Force the actuator into a stopped state after connecting."""
        if not self.is_connected():
            return None

        response = self.send_command("STOP")
        if response not in {"STOPPED", None, ""}:
            print(f"Arduino stop check returned '{response}'")
        return response

    def extend(self):
        """Send EXTEND command."""
        return self.send_command("EXTEND")

    def retract(self):
        """Send RETRACT command."""
        return self.send_command("RETRACT")

    def stop(self):
        """Send STOP command."""
        return self.send_command("STOP")

    def status(self):
        """Request the Arduino firmware status string."""
        return self.send_command("STATUS")

    def is_connected(self):
        """Check if the serial connection to Arduino is established and open."""
        return self.serial_connection is not None and self.serial_connection.is_open

    def ping(self):
        """Send a ping command to verify Arduino is responsive."""
        for _ in range(3):
            response = self.send_command("PING")
            if response == "PONG":
                print("Arduino ping successful")
                return True
            time.sleep(0.2)

        print(f"Arduino ping failed: received '{response}'")
        return False

    def verify_connection(self):
        """Verify both the serial link and Arduino responsiveness."""
        if not self.is_connected():
            return False

        return self.ping()

    def get_diagnostics(self):
        """Return a diagnostic snapshot for the current Arduino connection."""
        serial_open = self.is_connected()
        ping_ok = self.ping() if serial_open else False
        status_response = self.status() if serial_open else None

        return {
            "port": self.port,
            "baudrate": self.baudrate,
            "timeout": self.timeout,
            "serial_connected": serial_open,
            "serial_open": serial_open,
            "ping_ok": ping_ok,
            "status": status_response,
        }

    def print_diagnostics(self):
        """Print a readable diagnostic summary and return the raw data."""
        diagnostics = self.get_diagnostics()
        print("Arduino diagnostics:")
        for key, value in diagnostics.items():
            print(f"  {key}: {value}")
        return diagnostics


# Example usage (for testing)
if __name__ == "__main__":
    controller = ArduinoController()
    if controller.connect():
        print(f"Connection established: {controller.is_connected()}")
        print(f"Connection verified: {controller.verify_connection()}")
        controller.print_diagnostics()
        print(controller.extend())
        print(controller.retract())
        controller.disconnect()
