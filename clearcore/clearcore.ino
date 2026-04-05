#include "ClearCore.h"

// The INPUT_A_B_FILTER must match the Input A, B filter setting in
// MSP (Advanced >> Input A, B Filtering...)
#define INPUT_A_B_FILTER 20

// Defines the motor connectors used by this project.
#define motor0 ConnectorM0
#define motor1 ConnectorM1

// Select the baud rate to match the target device.
#define baudRate 9600
#define firmwareVersion "clearcore-dual-motor-v1"

// This example has built-in functionality to automatically clear motor faults. 
//	Any uncleared fault will cancel and disallow motion.
// WARNING: enabling automatic fault handling will clear faults immediately when 
//	encountered and return a motor to a state in which motion is allowed. Before 
//	enabling this functionality, be sure to understand this behavior and ensure 
//	your system will not enter an unsafe state. 
// To enable automatic fault handling, #define HANDLE_MOTOR_FAULTS (1)
// To disable automatic fault handling, #define HANDLE_MOTOR_FAULTS (0)
#define HANDLE_MOTOR_FAULTS (0)

// Declares user-defined helper functions.
// The definition/implementations of these functions are at the bottom of the sketch.
bool RampToVelocitySelectionM0(int velocityIndex);
bool RampToVelocitySelectionM1(int velocityIndex);
bool EnableMotorM0();
bool EnableMotorM1();
bool DisableMotorM0();
bool DisableMotorM1();
bool StopMotorM0();
bool StopMotorM1();
void HandleMotorFaultsM0();
void HandleMotorFaultsM1();
String HandleCommand(const String &rawCmd);
String ReadLineFromSerial();
String MotorStatusM0();
String MotorStatusM1();
void WaitForSerialPort(uint32_t timeoutMs);
bool WaitForHlfbM0(String context);
bool WaitForHlfbM1(String context);

bool motor0Enabled = false;
bool motor1Enabled = false;

void setup() {
    // Sets all motor connectors to the correct mode for Ramp Up/Down to
    // Selected Velocity mode.
    MotorMgr.MotorModeSet(MotorManager::MOTOR_ALL,
                          Connector::CPM_MODE_A_DIRECT_B_DIRECT);

    // Set both motors' HLFB mode to bipolar PWM.
    motor0.HlfbMode(MotorDriver::HLFB_MODE_HAS_BIPOLAR_PWM);
    motor1.HlfbMode(MotorDriver::HLFB_MODE_HAS_BIPOLAR_PWM);
    // Set the HLFB carrier frequency to 482 Hz.
    motor0.HlfbCarrier(MotorDriver::HLFB_CARRIER_482_HZ);
    motor1.HlfbCarrier(MotorDriver::HLFB_CARRIER_482_HZ);

    // Enforce the state of each motor's A and B inputs before enabling.
    motor0.MotorInAState(false);
    motor0.MotorInBState(false);
    motor1.MotorInAState(false);
    motor1.MotorInBState(false);

    Serial.begin(baudRate);
    WaitForSerialPort(5000);
    Serial.println("READY");
}


void loop() {
    String cmd = ReadLineFromSerial();
    if (cmd.length() == 0) {
        return;
    }

    String response = HandleCommand(cmd);
    Serial.println(response);
}

String HandleCommand(const String &rawCmd) {
    String cmd = rawCmd;
    cmd.trim();
    cmd.toUpperCase();

    if (cmd == "PING") return "PONG";
    if (cmd == "PING_M0") return "PONG_M0";
    if (cmd == "PING_M1") return "PONG_M1";
    if (cmd == "VERSION") return firmwareVersion;
    if (cmd == "CAPS") return "CAPS:M0,M1,STATUS";
    if (cmd == "ENABLE_M0") return EnableMotorM0() ? "OK ENABLE_M0" : "ERR ENABLE_M0";
    if (cmd == "DISABLE_M0") return DisableMotorM0() ? "OK DISABLE_M0" : "ERR DISABLE_M0";
    if (cmd == "MOVE_POS1_M0") return RampToVelocitySelectionM0(2) ? "OK MOVE_POS1_M0" : "ERR MOVE_POS1_M0";
    if (cmd == "MOVE_POS2_M0") return RampToVelocitySelectionM0(3) ? "OK MOVE_POS2_M0" : "ERR MOVE_POS2_M0";
    if (cmd == "STOP_M0") return StopMotorM0() ? "OK STOP_M0" : "ERR STOP_M0";
    if (cmd == "ENABLE_M1") return EnableMotorM1() ? "OK ENABLE_M1" : "ERR ENABLE_M1";
    if (cmd == "DISABLE_M1") return DisableMotorM1() ? "OK DISABLE_M1" : "ERR DISABLE_M1";
    if (cmd == "MOVE_POS1_M1") return RampToVelocitySelectionM1(2) ? "OK MOVE_POS1_M1" : "ERR MOVE_POS1_M1";
    if (cmd == "MOVE_POS2_M1") return RampToVelocitySelectionM1(3) ? "OK MOVE_POS2_M1" : "ERR MOVE_POS2_M1";
    if (cmd == "STOP_M1") return StopMotorM1() ? "OK STOP_M1" : "ERR STOP_M1";
    if (cmd == "STATUS_M0") return MotorStatusM0();
    if (cmd == "STATUS_M1") return MotorStatusM1();

    return "ERR UNKNOWN_CMD";
}

String ReadLineFromSerial() {
    static String buffer = "";

    while (Serial.available() > 0) {
        char c = (char)Serial.read();

        if (c == '\r') {
            continue;
        }

        if (c == '\n') {
            String line = buffer;
            buffer = "";
            return line;
        }

        buffer += c;
        if (buffer.length() > 120) {
            buffer = "";
            return "";
        }
    }

    return "";
}

void WaitForSerialPort(uint32_t timeoutMs) {
    uint32_t startTime = millis();
    while (!Serial && millis() - startTime < timeoutMs) {
        continue;
    }
}

bool EnableMotorM0() {
    motor0.EnableRequest(true);
    bool ready = WaitForHlfbM0("Enable M0");
    motor0Enabled = ready;
    return ready;
}

bool EnableMotorM1() {
    motor1.EnableRequest(true);
    bool ready = WaitForHlfbM1("Enable M1");
    motor1Enabled = ready;
    return ready;
}

bool DisableMotorM0() {
    motor0.MotorInAState(false);
    motor0.MotorInBState(false);
    motor0.EnableRequest(false);
    motor0Enabled = false;
    return true;
}

bool DisableMotorM1() {
    motor1.MotorInAState(false);
    motor1.MotorInBState(false);
    motor1.EnableRequest(false);
    motor1Enabled = false;
    return true;
}

bool StopMotorM0() {
    if (!motor0Enabled) {
        return false;
    }

    // Assumes velocity selection 1 (A off/B off) is configured as 0 RPM in MSP.
    return RampToVelocitySelectionM0(1);
}

bool StopMotorM1() {
    if (!motor1Enabled) {
        return false;
    }

    // Assumes velocity selection 1 (A off/B off) is configured as 0 RPM in MSP.
    return RampToVelocitySelectionM1(1);
}

/*------------------------------------------------------------------------------
 * RampToVelocitySelection
 *
 *    Move to Velocity Selection number velocityIndex (defined in MSP)
 *    Prints the move status to the USB serial port
 *    Returns when HLFB asserts (indicating the motor has reached the target
 *    velocity)
 *
 * Parameters:
 *    int velocityIndex  - The velocity number to command (defined in MSP)
 *
 * Returns: True/False depending on whether the velocity selection was
 * successfully commanded.
 */
bool RampToVelocitySelectionM0(int velocityIndex) {
    if (!motor0Enabled) {
        Serial.println("Motor M0 is not enabled.");
        return false;
    }

    // Check if a motor fault is currently preventing motion
	// Clear fault if configured to do so 
    if (motor0.StatusReg().bit.MotorInFault) {
		if(HANDLE_MOTOR_FAULTS){
			Serial.println("Motor M0 fault detected. Move canceled.");
			HandleMotorFaultsM0();
		} else {
			Serial.println("Motor M0 fault detected. Move canceled. Enable automatic fault handling by setting HANDLE_MOTOR_FAULTS to 1.");
		}
        return false;
    }

    Serial.print("Moving M0 to Velocity Selection: ");
    Serial.print(velocityIndex);

    switch (velocityIndex) {
        case 1:
            // Sets Input A and B for velocity 1
            motor0.MotorInAState(false);
            motor0.MotorInBState(false);
            Serial.println(" (Inputs A Off/B Off)");
            break;
        case 2:
            // Sets Input A and B for velocity 2
            motor0.MotorInAState(true);
            motor0.MotorInBState(false);
            Serial.println(" (Inputs A On/B Off)");
            break;
        case 3:
            // Sets Input A and B for velocity 3
            motor0.MotorInAState(false);
            motor0.MotorInBState(true);
            Serial.println(" (Inputs A Off/B On)");
            break;
        case 4:
            // Sets Input A and B for velocity 4
            motor0.MotorInAState(true);
            motor0.MotorInBState(true);
            Serial.println(" (Inputs A On/B On)");
            break;
        default:
            // If this case is reached then an incorrect velocityIndex was
            // entered
            return false;
    }

    // Ensures this delay is at least 20ms longer than the Input A, B filter
    // setting in MSP
    delay(20 + INPUT_A_B_FILTER);

    // Waits for HLFB to assert (signaling the move has successfully reached its
    // target velocity)
    Serial.println("Moving.. Waiting for HLFB");
    bool ready = WaitForHlfbM0("Move M0");
	// Check if a motor faulted during move
	// Clear fault if configured to do so 
    if (!ready) {
		Serial.println("Motor M0 fault detected.");		
		if(HANDLE_MOTOR_FAULTS){
			HandleMotorFaultsM0();
		} else {
			Serial.println("Enable automatic fault handling by setting HANDLE_MOTOR_FAULTS to 1.");
		}
		Serial.println("Motion may not have completed as expected. Proceed with caution.");
		Serial.println();
		return false;
    } else {
		Serial.println("Move Done");
		return true;
	}
}
 
bool RampToVelocitySelectionM1(int velocityIndex) {
    if (!motor1Enabled) {
        Serial.println("Motor M1 is not enabled.");
        return false;
    }

    if (motor1.StatusReg().bit.MotorInFault) {
		if(HANDLE_MOTOR_FAULTS){
			Serial.println("Motor M1 fault detected. Move canceled.");
			HandleMotorFaultsM1();
		} else {
			Serial.println("Motor M1 fault detected. Move canceled. Enable automatic fault handling by setting HANDLE_MOTOR_FAULTS to 1.");
		}
        return false;
    }

    Serial.print("Moving M1 to Velocity Selection: ");
    Serial.print(velocityIndex);

    switch (velocityIndex) {
        case 1:
            motor1.MotorInAState(false);
            motor1.MotorInBState(false);
            Serial.println(" (Inputs A Off/B Off)");
            break;
        case 2:
            motor1.MotorInAState(true);
            motor1.MotorInBState(false);
            Serial.println(" (Inputs A On/B Off)");
            break;
        case 3:
            motor1.MotorInAState(false);
            motor1.MotorInBState(true);
            Serial.println(" (Inputs A Off/B On)");
            break;
        case 4:
            motor1.MotorInAState(true);
            motor1.MotorInBState(true);
            Serial.println(" (Inputs A On/B On)");
            break;
        default:
            return false;
    }

    delay(20 + INPUT_A_B_FILTER);

    Serial.println("Moving.. Waiting for HLFB");
    bool ready = WaitForHlfbM1("Move M1");
    if (!ready) {
		Serial.println("Motor M1 fault detected.");		
		if(HANDLE_MOTOR_FAULTS){
			HandleMotorFaultsM1();
		} else {
			Serial.println("Enable automatic fault handling by setting HANDLE_MOTOR_FAULTS to 1.");
		}
		Serial.println("Motion may not have completed as expected. Proceed with caution.");
		Serial.println();
		return false;
    } else {
		Serial.println("Move Done");
		return true;
	}
}
//------------------------------------------------------------------------------

bool WaitForHlfbM0(String context) {
    Serial.print(context);
    Serial.println(".. Waiting for HLFB");

    while (motor0.HlfbState() != MotorDriver::HLFB_ASSERTED &&
           !motor0.StatusReg().bit.MotorInFault) {
        continue;
    }

    return !motor0.StatusReg().bit.MotorInFault;
}

bool WaitForHlfbM1(String context) {
    Serial.print(context);
    Serial.println(".. Waiting for HLFB");

    while (motor1.HlfbState() != MotorDriver::HLFB_ASSERTED &&
           !motor1.StatusReg().bit.MotorInFault) {
        continue;
    }

    return !motor1.StatusReg().bit.MotorInFault;
}

String MotorStatusM0() {
    if (motor0.StatusReg().bit.MotorInFault) {
        return "STATUS_M0:FAULT";
    }
    if (!motor0Enabled) {
        return "STATUS_M0:DISABLED";
    }
    if (motor0.HlfbState() == MotorDriver::HLFB_ASSERTED) {
        return "STATUS_M0:ENABLED";
    }
    return "STATUS_M0:TRANSITION";
}

String MotorStatusM1() {
    if (motor1.StatusReg().bit.MotorInFault) {
        return "STATUS_M1:FAULT";
    }
    if (!motor1Enabled) {
        return "STATUS_M1:DISABLED";
    }
    if (motor1.HlfbState() == MotorDriver::HLFB_ASSERTED) {
        return "STATUS_M1:ENABLED";
    }
    return "STATUS_M1:TRANSITION";
}
 
/*------------------------------------------------------------------------------
 * HandleMotorFaultsM0
 *
 *    Clears motor faults by cycling enable to the motor.
 *    Assumes motor is in fault 
 *      (this function is called when motor.StatusReg.MotorInFault == true)
 *
 * Parameters:
 *    requires "motor" to be defined as a ClearCore motor connector
 *
 * Returns: 
 *    none
 */
 void HandleMotorFaultsM0(){
 	Serial.println("Handling M0 fault: clearing faults by cycling enable signal to motor.");
	motor0.EnableRequest(false);
	Delay_ms(10);
	motor0.EnableRequest(true);
	Delay_ms(100);
}

void HandleMotorFaultsM1(){
	Serial.println("Handling M1 fault: clearing faults by cycling enable signal to motor.");
	motor1.EnableRequest(false);
	Delay_ms(10);
	motor1.EnableRequest(true);
	Delay_ms(100);
}
//------------------------------------------------------------------------------
