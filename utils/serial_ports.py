import time

import serial
from serial.tools import list_ports


def send_probe_command(connection, command: str) -> str:
    connection.reset_input_buffer()
    connection.write((command + "\n").encode())
    return connection.readline().decode(errors="ignore").strip()


def classify_serial_port(device: str, timeout: float = 0.6):
    try:
        with serial.Serial(device, 9600, timeout=timeout) as connection:
            # Opening an Arduino-style serial device can reset it.
            time.sleep(2.0)

            ping_response = send_probe_command(connection, "PING")
            caps_response = send_probe_command(connection, "CAPS")
            if caps_response.startswith("CAPS:"):
                return "ClearCore", f"PING={ping_response or 'none'}, CAPS={caps_response}"

            status_response = send_probe_command(connection, "STATUS")
            normalized_status = status_response.upper()
            if normalized_status == "READY" or "UNKNOWN" in normalized_status:
                return "Arduino", f"PING={ping_response or 'none'}, STATUS={status_response or 'none'}"

            if ping_response == "PONG":
                return "Serial Device", "PING=PONG"
        return "Unknown", "No handshake response"
    except Exception as exc:
        return "Unknown", f"Probe failed: {exc}"


def get_serial_ports():
    ports = []
    for port in list_ports.comports():
        role = "Unknown"
        role_detail = port.description

        description_parts = " ".join(filter(None, [
            port.description,
            getattr(port, "manufacturer", None),
            getattr(port, "product", None),
        ])).lower()

        if "clearcore" in description_parts:
            role = "ClearCore"
            role_detail = "USB descriptor"
        elif "arduino" in description_parts:
            role = "Arduino"
            role_detail = "USB descriptor"
        else:
            role, role_detail = classify_serial_port(port.device)

        ports.append({
            "device": port.device,
            "description": port.description,
            "hwid": port.hwid,
            "manufacturer": getattr(port, "manufacturer", None),
            "product": getattr(port, "product", None),
            "role": role,
            "role_detail": role_detail,
        })
    return ports
