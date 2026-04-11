import time

import serial
from serial.tools import list_ports

PROBE_BAUDRATES = (9600, 115200)


def send_probe_command(connection, command: str) -> str:
    connection.reset_input_buffer()
    connection.write((command + "\n").encode())
    return connection.readline().decode(errors="ignore").strip()


def probe_serial_port(device: str, timeout: float = 0.6):
    last_detail = "No handshake response"
    for baudrate in PROBE_BAUDRATES:
        try:
            with serial.Serial(device, baudrate, timeout=timeout) as connection:
                # Opening an Arduino-style serial device can reset it.
                time.sleep(2.0)

                ping_response = send_probe_command(connection, "PING")
                caps_response = send_probe_command(connection, "CAPS")
                if caps_response.startswith("CAPS:ACTUATOR"):
                    return (
                        "Arduino",
                        f"baud={baudrate}, PING={ping_response or 'none'}, CAPS={caps_response}",
                        baudrate,
                    )

                if caps_response.startswith("CAPS:"):
                    return (
                        "ClearCore",
                        f"baud={baudrate}, PING={ping_response or 'none'}, CAPS={caps_response}",
                        baudrate,
                    )

                version_response = send_probe_command(connection, "VERSION")
                if "CLEARCORE" in version_response.upper():
                    return (
                        "ClearCore",
                        f"baud={baudrate}, PING={ping_response or 'none'}, VERSION={version_response}",
                        baudrate,
                    )

                status_response = send_probe_command(connection, "STATUS")
                normalized_status = status_response.upper()
                if normalized_status == "READY":
                    return (
                        "Arduino",
                        f"baud={baudrate}, PING={ping_response or 'none'}, STATUS={status_response or 'none'}",
                        baudrate,
                    )

                if ping_response == "PONG":
                    return "Serial Device", f"baud={baudrate}, PING=PONG", baudrate

                last_detail = (
                    f"baud={baudrate}, PING={ping_response or 'none'}, "
                    f"CAPS={caps_response or 'none'}, VERSION={version_response or 'none'}, "
                    f"STATUS={status_response or 'none'}"
                )
        except Exception as exc:
            last_detail = f"baud={baudrate}, probe failed: {exc}"

    return "Unknown", last_detail, None


def classify_serial_port(device: str, timeout: float = 0.6):
    role, detail, _baudrate = probe_serial_port(device, timeout=timeout)
    return role, detail


def classify_descriptor(description_parts: str):
    if any(token in description_parts for token in ("clearcore", "clearpath", "teknic")):
        return "ClearCore", "USB descriptor"
    if "arduino" in description_parts:
        return "Arduino", "USB descriptor"
    return None, None


def get_serial_ports(probe: bool = False):
    ports = []
    for port in list_ports.comports():
        role = "Unknown"
        role_detail = port.description
        baudrate = None

        description_parts = " ".join(filter(None, [
            port.description,
            getattr(port, "manufacturer", None),
            getattr(port, "product", None),
        ])).lower()

        descriptor_role, descriptor_detail = classify_descriptor(description_parts)
        if descriptor_role is not None:
            role = descriptor_role
            role_detail = descriptor_detail
        elif probe:
            probed_role, probed_detail, probed_baudrate = probe_serial_port(port.device)
            role = probed_role
            role_detail = probed_detail
            baudrate = probed_baudrate

        ports.append({
            "device": port.device,
            "description": port.description,
            "hwid": port.hwid,
            "manufacturer": getattr(port, "manufacturer", None),
            "product": getattr(port, "product", None),
            "role": role,
            "role_detail": role_detail,
            "baudrate": baudrate,
        })
    return ports
