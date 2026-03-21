from serial.tools import list_ports


def get_serial_ports():
    ports = []
    for port in list_ports.comports():
        ports.append({
            "device": port.device,
            "description": port.description,
            "hwid": port.hwid,
        })
    return ports