from controllers.clearcore_controller import ClearCoreController

cc = ClearCoreController(port="/dev/ttyACM0", baudrate=115200, timeout=1.0)

print(cc.send_command("PING"))
print(cc.send_command("FWD"))
print(cc.send_command("STOP"))