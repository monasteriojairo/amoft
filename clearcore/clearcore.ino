#include "ClearCore.h"

#define INPUT_A_B_FILTER 20
#define motor0 ConnectorM0
#define motor1 ConnectorM1

// ClearCore owns servo safety/status inputs. IO-0 watches the E-stop OK signal.
#define estopStatus ConnectorIO0
#define m0HomeSwitch ConnectorDI7
#define m0LimitSwitch ConnectorDI8
#define m1HomeSwitch ConnectorA9
#define m1LimitSwitch ConnectorA10

#define baudRate 9600
#define firmwareVersion "clearcore-dual-motor-v10"

static const int STOP_SELECTION = 1;
static const int POSITIVE_SELECTION = 2;
static const int NEGATIVE_SELECTION = 3;
static const int M0_HOME_SELECTION = NEGATIVE_SELECTION;
static const int M0_LIMIT_SELECTION = POSITIVE_SELECTION;
static const int M1_HOME_SELECTION = NEGATIVE_SELECTION;
static const int M1_LIMIT_SELECTION = POSITIVE_SELECTION;

static const uint32_t HOMING_SEEK_TIMEOUT_MS = 15000;
static const uint32_t HOMING_RELEASE_TIMEOUT_MS = 5000;
static const uint32_t HLFB_TIMEOUT_MS = 5000;

static const bool ESTOP_ACTIVE_LOW = true;
static const bool M0_HOME_ACTIVE_LOW = true;
static const bool M0_LIMIT_ACTIVE_LOW = true;
static const bool M1_HOME_ACTIVE_LOW = true;
static const bool M1_LIMIT_ACTIVE_LOW = true;
static const bool LIMIT_INTERLOCK_ENABLED = false;

bool RampToVelocitySelectionM0(int velocityIndex);
bool RampToVelocitySelectionM1(int velocityIndex);
bool EnableMotorM0();
bool EnableMotorM1();
bool DisableMotorM0();
bool DisableMotorM1();
bool StopMotorM0();
bool StopMotorM1();
bool HomeMotorM0();
bool HomeMotorM1();
String HandleCommand(const String &rawCmd);
String ReadLineFromSerial();
String MotorStatusM0();
String MotorStatusM1();
String HomeStatusM0();
String HomeStatusM1();
String LimitStatusM0();
String LimitStatusM1();
String InputSummary();
String ControllerStateSummary();
String FaultSummary();
String EstopOverrideSummary();
String LimitOverrideSummary();
void WaitForSerialPort(uint32_t timeoutMs);
bool WaitForHlfbM0();
bool WaitForHlfbM1();
bool ApplyVelocitySelectionM0(int velocityIndex, bool waitForHlfb = true);
bool ApplyVelocitySelectionM1(int velocityIndex, bool waitForHlfb = true);
bool CheckMotionAllowedM0(int velocityIndex);
bool CheckMotionAllowedM1(int velocityIndex);
bool MoveUntilHomeStateM0(bool targetState, int velocityIndex, uint32_t timeoutMs);
bool MoveUntilHomeStateM1(bool targetState, int velocityIndex, uint32_t timeoutMs);
void ConfigureInputs();
void MonitorSafetyInputs();
bool SignalActive(int16_t rawState, bool activeLow);
bool RawEstopActive();
bool EstopActive();
bool RawM0HomeActive();
bool RawM0LimitActive();
bool RawM1HomeActive();
bool RawM1LimitActive();
bool M0HomeActive();
bool M0LimitActive();
bool M1HomeActive();
bool M1LimitActive();
bool Motor0MovingTowardHome();
bool Motor0MovingTowardLimit();
bool Motor1MovingTowardHome();
bool Motor1MovingTowardLimit();

bool motor0Enabled = false;
bool motor1Enabled = false;
bool motor0Homed = false;
bool motor1Homed = false;
bool motor0Homing = false;
bool motor1Homing = false;
bool controllerFaultLatched = false;
bool controllerFaultFromEstop = false;
bool estopOverrideEnabled = false;
bool limitOverrideEnabled = false;
int motor0VelocitySelection = STOP_SELECTION;
int motor1VelocitySelection = STOP_SELECTION;

void setup() {
    MotorMgr.MotorModeSet(MotorManager::MOTOR_ALL, Connector::CPM_MODE_A_DIRECT_B_DIRECT);

    motor0.HlfbMode(MotorDriver::HLFB_MODE_HAS_BIPOLAR_PWM);
    motor1.HlfbMode(MotorDriver::HLFB_MODE_HAS_BIPOLAR_PWM);
    motor0.HlfbCarrier(MotorDriver::HLFB_CARRIER_482_HZ);
    motor1.HlfbCarrier(MotorDriver::HLFB_CARRIER_482_HZ);

    motor0.MotorInAState(false);
    motor0.MotorInBState(false);
    motor1.MotorInAState(false);
    motor1.MotorInBState(false);

    ConfigureInputs();

    Serial.begin(baudRate);
    WaitForSerialPort(5000);
    Serial.println("READY");
}

void loop() {
    MonitorSafetyInputs();

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
    if (cmd == "CAPS") return "CAPS:M0,M1,STATUS,HOME,LIMITS,INPUTS,FAULTS,ESTOP_IO0,SOFTWARE_HOME,LIMITS_REPORT_ONLY,PI_LIMIT_OWNER,ESTOP_OVERRIDE";
    if (cmd == "INPUTS") return InputSummary();
    if (cmd == "CONTROLLER_STATE") return ControllerStateSummary();
    if (cmd == "FAULTS") return FaultSummary();
    if (cmd == "ESTOP_OVERRIDE") return EstopOverrideSummary();
    if (cmd == "LIMIT_OVERRIDE") return LimitOverrideSummary();
    if (cmd.startsWith("SET_ESTOP_OVERRIDE:")) {
        String value = cmd.substring(cmd.indexOf(':') + 1);
        value.trim();
        estopOverrideEnabled = value == "1" || value == "ON" || value == "TRUE";
        if (estopOverrideEnabled && controllerFaultFromEstop &&
            !motor0.StatusReg().bit.MotorInFault && !motor1.StatusReg().bit.MotorInFault) {
            controllerFaultLatched = false;
            controllerFaultFromEstop = false;
        }
        return EstopOverrideSummary();
    }
    if (cmd.startsWith("SET_LIMIT_OVERRIDE:")) {
        String value = cmd.substring(cmd.indexOf(':') + 1);
        value.trim();
        limitOverrideEnabled = value == "1" || value == "ON" || value == "TRUE";
        return LimitOverrideSummary();
    }
    if (cmd == "CLEAR_FAULTS") {
        if (!EstopActive()) {
            controllerFaultLatched = false;
            controllerFaultFromEstop = false;
        }
        return controllerFaultLatched ? "ERR CLEAR_FAULTS" : "OK CLEAR_FAULTS";
    }
    if (cmd == "ENABLE_M0") return EnableMotorM0() ? "OK ENABLE_M0" : "ERR ENABLE_M0";
    if (cmd == "DISABLE_M0") return DisableMotorM0() ? "OK DISABLE_M0" : "ERR DISABLE_M0";
    if (cmd == "MOVE_POS1_M0") return RampToVelocitySelectionM0(POSITIVE_SELECTION) ? "OK MOVE_POS1_M0" : "ERR MOVE_POS1_M0";
    if (cmd == "MOVE_POS2_M0") return RampToVelocitySelectionM0(NEGATIVE_SELECTION) ? "OK MOVE_POS2_M0" : "ERR MOVE_POS2_M0";
    if (cmd == "STOP_M0") return StopMotorM0() ? "OK STOP_M0" : "ERR STOP_M0";
    if (cmd == "HOME_M0") return HomeMotorM0() ? "OK HOME_M0" : "ERR HOME_M0";
    if (cmd == "HOME_STATUS_M0") return HomeStatusM0();
    if (cmd == "LIMITS_M0") return LimitStatusM0();
    if (cmd == "MARK_HOMED_M0" || cmd == "SET_HOME_M0:1") {
        motor0Homed = true;
        return "OK MARK_HOMED_M0";
    }
    if (cmd == "RESET_HOME_M0" || cmd == "SET_HOME_M0:0") {
        motor0Homed = false;
        return "OK RESET_HOME_M0";
    }
    if (cmd == "ENABLE_M1") return EnableMotorM1() ? "OK ENABLE_M1" : "ERR ENABLE_M1";
    if (cmd == "DISABLE_M1") return DisableMotorM1() ? "OK DISABLE_M1" : "ERR DISABLE_M1";
    if (cmd == "MOVE_POS1_M1") return RampToVelocitySelectionM1(POSITIVE_SELECTION) ? "OK MOVE_POS1_M1" : "ERR MOVE_POS1_M1";
    if (cmd == "MOVE_POS2_M1") return RampToVelocitySelectionM1(NEGATIVE_SELECTION) ? "OK MOVE_POS2_M1" : "ERR MOVE_POS2_M1";
    if (cmd == "STOP_M1") return StopMotorM1() ? "OK STOP_M1" : "ERR STOP_M1";
    if (cmd == "HOME_M1") return HomeMotorM1() ? "OK HOME_M1" : "ERR HOME_M1";
    if (cmd == "HOME_STATUS_M1") return HomeStatusM1();
    if (cmd == "LIMITS_M1") return LimitStatusM1();
    if (cmd == "MARK_HOMED_M1" || cmd == "SET_HOME_M1:1") {
        motor1Homed = true;
        return "OK MARK_HOMED_M1";
    }
    if (cmd == "RESET_HOME_M1" || cmd == "SET_HOME_M1:0") {
        motor1Homed = false;
        return "OK RESET_HOME_M1";
    }
    if (cmd == "STATUS_M0") return MotorStatusM0();
    if (cmd == "STATUS_M1") return MotorStatusM1();
    if (cmd == "RESET_HOME") {
        motor0Homed = false;
        motor1Homed = false;
        return "OK RESET_HOME";
    }

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
        if (buffer.length() > 160) {
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

void ConfigureInputs() {
    estopStatus.Mode(Connector::INPUT_DIGITAL);
    m0HomeSwitch.Mode(Connector::INPUT_DIGITAL);
    m0LimitSwitch.Mode(Connector::INPUT_DIGITAL);
    m1HomeSwitch.Mode(Connector::INPUT_DIGITAL);
    m1LimitSwitch.Mode(Connector::INPUT_DIGITAL);

    estopStatus.FilterLength(5, DigitalIn::FILTER_UNIT_MS);
    m0HomeSwitch.FilterLength(5, DigitalIn::FILTER_UNIT_MS);
    m0LimitSwitch.FilterLength(5, DigitalIn::FILTER_UNIT_MS);
    m1HomeSwitch.FilterLength(5, DigitalIn::FILTER_UNIT_MS);
    m1LimitSwitch.FilterLength(5, DigitalIn::FILTER_UNIT_MS);
}

bool SignalActive(int16_t rawState, bool activeLow) {
    return activeLow ? rawState == 0 : rawState != 0;
}

bool RawEstopActive() { return SignalActive(estopStatus.State(), ESTOP_ACTIVE_LOW); }
bool EstopActive() { return !estopOverrideEnabled && RawEstopActive(); }
bool RawM0HomeActive() { return SignalActive(m0HomeSwitch.State(), M0_HOME_ACTIVE_LOW); }
bool RawM0LimitActive() { return SignalActive(m0LimitSwitch.State(), M0_LIMIT_ACTIVE_LOW); }
bool RawM1HomeActive() { return SignalActive(m1HomeSwitch.State(), M1_HOME_ACTIVE_LOW); }
bool RawM1LimitActive() { return SignalActive(m1LimitSwitch.State(), M1_LIMIT_ACTIVE_LOW); }
bool M0HomeActive() { return RawM0HomeActive(); }
bool M0LimitActive() { return RawM0LimitActive(); }
bool M1HomeActive() { return RawM1HomeActive(); }
bool M1LimitActive() { return RawM1LimitActive(); }

bool Motor0MovingTowardHome() { return motor0VelocitySelection == M0_HOME_SELECTION; }
bool Motor0MovingTowardLimit() { return motor0VelocitySelection == M0_LIMIT_SELECTION; }
bool Motor1MovingTowardHome() { return motor1VelocitySelection == M1_HOME_SELECTION; }
bool Motor1MovingTowardLimit() { return motor1VelocitySelection == M1_LIMIT_SELECTION; }

void MonitorSafetyInputs() {
    if (EstopActive()) {
        if (!controllerFaultLatched) {
            controllerFaultFromEstop = true;
        }
        controllerFaultLatched = true;
        DisableMotorM0();
        DisableMotorM1();
        return;
    }

    if (controllerFaultFromEstop &&
        !motor0.StatusReg().bit.MotorInFault &&
        !motor1.StatusReg().bit.MotorInFault) {
        controllerFaultLatched = false;
        controllerFaultFromEstop = false;
    }

    if (LIMIT_INTERLOCK_ENABLED && motor0Enabled && motor0VelocitySelection != STOP_SELECTION) {
        if (Motor0MovingTowardLimit() && M0LimitActive()) {
            controllerFaultLatched = true;
            controllerFaultFromEstop = false;
            DisableMotorM0();
        } else if (Motor0MovingTowardHome() && M0HomeActive() && !motor0Homing) {
            StopMotorM0();
        }
    }

    if (LIMIT_INTERLOCK_ENABLED && motor1Enabled && motor1VelocitySelection != STOP_SELECTION) {
        if (Motor1MovingTowardLimit() && M1LimitActive()) {
            controllerFaultLatched = true;
            controllerFaultFromEstop = false;
            DisableMotorM1();
        } else if (Motor1MovingTowardHome() && M1HomeActive() && !motor1Homing) {
            StopMotorM1();
        }
    }
}

bool EnableMotorM0() {
    if (EstopActive() || controllerFaultLatched) return false;
    motor0.EnableRequest(true);
    bool ready = WaitForHlfbM0();
    motor0Enabled = ready;
    return ready;
}

bool EnableMotorM1() {
    if (EstopActive() || controllerFaultLatched) return false;
    motor1.EnableRequest(true);
    bool ready = WaitForHlfbM1();
    motor1Enabled = ready;
    return ready;
}

bool DisableMotorM0() {
    motor0.MotorInAState(false);
    motor0.MotorInBState(false);
    motor0.EnableRequest(false);
    motor0Enabled = false;
    motor0VelocitySelection = STOP_SELECTION;
    return true;
}

bool DisableMotorM1() {
    motor1.MotorInAState(false);
    motor1.MotorInBState(false);
    motor1.EnableRequest(false);
    motor1Enabled = false;
    motor1VelocitySelection = STOP_SELECTION;
    return true;
}

bool StopMotorM0() {
    if (!motor0Enabled) {
        motor0VelocitySelection = STOP_SELECTION;
        motor0.MotorInAState(false);
        motor0.MotorInBState(false);
        return true;
    }
    return ApplyVelocitySelectionM0(STOP_SELECTION);
}

bool StopMotorM1() {
    if (!motor1Enabled) {
        motor1VelocitySelection = STOP_SELECTION;
        motor1.MotorInAState(false);
        motor1.MotorInBState(false);
        return true;
    }
    return ApplyVelocitySelectionM1(STOP_SELECTION);
}

bool CheckMotionAllowedM0(int velocityIndex) {
    if (velocityIndex == STOP_SELECTION) return true;
    if (EstopActive() || controllerFaultLatched) return false;
    if (LIMIT_INTERLOCK_ENABLED && !limitOverrideEnabled &&
        velocityIndex == M0_HOME_SELECTION && M0HomeActive()) return false;
    if (LIMIT_INTERLOCK_ENABLED && !limitOverrideEnabled &&
        velocityIndex == M0_LIMIT_SELECTION && M0LimitActive()) return false;
    return true;
}

bool CheckMotionAllowedM1(int velocityIndex) {
    if (velocityIndex == STOP_SELECTION) return true;
    if (EstopActive() || controllerFaultLatched) return false;
    if (LIMIT_INTERLOCK_ENABLED && !limitOverrideEnabled &&
        velocityIndex == M1_HOME_SELECTION && M1HomeActive()) return false;
    if (LIMIT_INTERLOCK_ENABLED && !limitOverrideEnabled &&
        velocityIndex == M1_LIMIT_SELECTION && M1LimitActive()) return false;
    return true;
}

bool ApplyVelocitySelectionM0(int velocityIndex, bool waitForHlfb) {
    if (!motor0Enabled) return false;
    if (!CheckMotionAllowedM0(velocityIndex)) return false;
    if (motor0.StatusReg().bit.MotorInFault) return false;

    switch (velocityIndex) {
        case 1: motor0.MotorInAState(false); motor0.MotorInBState(false); break;
        case 2: motor0.MotorInAState(true);  motor0.MotorInBState(false); break;
        case 3: motor0.MotorInAState(false); motor0.MotorInBState(true);  break;
        case 4: motor0.MotorInAState(true);  motor0.MotorInBState(true);  break;
        default: return false;
    }

    motor0VelocitySelection = velocityIndex;
    delay(20 + INPUT_A_B_FILTER);
    return !waitForHlfb || WaitForHlfbM0();
}

bool ApplyVelocitySelectionM1(int velocityIndex, bool waitForHlfb) {
    if (!motor1Enabled) return false;
    if (!CheckMotionAllowedM1(velocityIndex)) return false;
    if (motor1.StatusReg().bit.MotorInFault) return false;

    switch (velocityIndex) {
        case 1: motor1.MotorInAState(false); motor1.MotorInBState(false); break;
        case 2: motor1.MotorInAState(true);  motor1.MotorInBState(false); break;
        case 3: motor1.MotorInAState(false); motor1.MotorInBState(true);  break;
        case 4: motor1.MotorInAState(true);  motor1.MotorInBState(true);  break;
        default: return false;
    }

    motor1VelocitySelection = velocityIndex;
    delay(20 + INPUT_A_B_FILTER);
    return !waitForHlfb || WaitForHlfbM1();
}

bool RampToVelocitySelectionM0(int velocityIndex) { return ApplyVelocitySelectionM0(velocityIndex); }
bool RampToVelocitySelectionM1(int velocityIndex) { return ApplyVelocitySelectionM1(velocityIndex); }

bool MoveUntilHomeStateM0(bool targetState, int velocityIndex, uint32_t timeoutMs) {
    motor0Homing = true;
    if (!ApplyVelocitySelectionM0(velocityIndex)) {
        motor0Homing = false;
        return false;
    }
    uint32_t startTime = millis();
    while (millis() - startTime < timeoutMs) {
        MonitorSafetyInputs();
        if (EstopActive() || motor0.StatusReg().bit.MotorInFault) break;
        if (M0HomeActive() == targetState) {
            StopMotorM0();
            motor0Homing = false;
            return true;
        }
        Delay_ms(5);
    }
    StopMotorM0();
    motor0Homing = false;
    return false;
}

bool MoveUntilHomeStateM1(bool targetState, int velocityIndex, uint32_t timeoutMs) {
    motor1Homing = true;
    if (!ApplyVelocitySelectionM1(velocityIndex)) {
        motor1Homing = false;
        return false;
    }
    uint32_t startTime = millis();
    while (millis() - startTime < timeoutMs) {
        MonitorSafetyInputs();
        if (EstopActive() || motor1.StatusReg().bit.MotorInFault) break;
        if (M1HomeActive() == targetState) {
            StopMotorM1();
            motor1Homing = false;
            return true;
        }
        Delay_ms(5);
    }
    StopMotorM1();
    motor1Homing = false;
    return false;
}

bool HomeMotorM0() {
    motor0Homed = false;
    if (!EnableMotorM0()) return false;
    if (M0HomeActive()) {
        if (!MoveUntilHomeStateM0(false, M0_LIMIT_SELECTION, HOMING_RELEASE_TIMEOUT_MS)) return false;
    }
    if (!MoveUntilHomeStateM0(true, M0_HOME_SELECTION, HOMING_SEEK_TIMEOUT_MS)) return false;
    motor0Homed = true;
    return true;
}

bool HomeMotorM1() {
    motor1Homed = false;
    if (!EnableMotorM1()) return false;
    if (M1HomeActive()) {
        if (!MoveUntilHomeStateM1(false, M1_LIMIT_SELECTION, HOMING_RELEASE_TIMEOUT_MS)) return false;
    }
    if (!MoveUntilHomeStateM1(true, M1_HOME_SELECTION, HOMING_SEEK_TIMEOUT_MS)) return false;
    motor1Homed = true;
    return true;
}

bool WaitForHlfbM0() {
    uint32_t startTime = millis();
    while (motor0.HlfbState() != MotorDriver::HLFB_ASSERTED &&
           !motor0.StatusReg().bit.MotorInFault) {
        MonitorSafetyInputs();
        if (EstopActive()) return false;
        if (millis() - startTime > HLFB_TIMEOUT_MS) {
            controllerFaultLatched = true;
            controllerFaultFromEstop = false;
            return false;
        }
    }
    return !motor0.StatusReg().bit.MotorInFault;
}

bool WaitForHlfbM1() {
    uint32_t startTime = millis();
    while (motor1.HlfbState() != MotorDriver::HLFB_ASSERTED &&
           !motor1.StatusReg().bit.MotorInFault) {
        MonitorSafetyInputs();
        if (EstopActive()) return false;
        if (millis() - startTime > HLFB_TIMEOUT_MS) {
            controllerFaultLatched = true;
            controllerFaultFromEstop = false;
            return false;
        }
    }
    return !motor1.StatusReg().bit.MotorInFault;
}

String MotorStatusM0() {
    if (EstopActive() || controllerFaultLatched || motor0.StatusReg().bit.MotorInFault) return "STATUS_M0:FAULT";
    if (!motor0Enabled) return "STATUS_M0:DISABLED";
    if (motor0.HlfbState() == MotorDriver::HLFB_ASSERTED) return "STATUS_M0:ENABLED";
    return "STATUS_M0:TRANSITION";
}

String MotorStatusM1() {
    if (EstopActive() || controllerFaultLatched || motor1.StatusReg().bit.MotorInFault) return "STATUS_M1:FAULT";
    if (!motor1Enabled) return "STATUS_M1:DISABLED";
    if (motor1.HlfbState() == MotorDriver::HLFB_ASSERTED) return "STATUS_M1:ENABLED";
    return "STATUS_M1:TRANSITION";
}

String HomeStatusM0() { return motor0Homed ? "HOME_M0:HOMED" : "HOME_M0:NOT_HOMED"; }
String HomeStatusM1() { return motor1Homed ? "HOME_M1:HOMED" : "HOME_M1:NOT_HOMED"; }

String LimitStatusM0() {
    return String("LIMITS_M0:HOME=") + (M0HomeActive() ? "1" : "0") +
           ",HOME_RAW=" + (RawM0HomeActive() ? "1" : "0") +
           ",LIMIT=" + (M0LimitActive() ? "1" : "0") +
           ",LIMIT_RAW=" + (RawM0LimitActive() ? "1" : "0") +
           ",INTERLOCK=" + (LIMIT_INTERLOCK_ENABLED ? "1" : "0") +
           ",OVERRIDE=" + (limitOverrideEnabled ? "1" : "0");
}

String LimitStatusM1() {
    return String("LIMITS_M1:HOME=") + (M1HomeActive() ? "1" : "0") +
           ",HOME_RAW=" + (RawM1HomeActive() ? "1" : "0") +
           ",LIMIT=" + (M1LimitActive() ? "1" : "0") +
           ",LIMIT_RAW=" + (RawM1LimitActive() ? "1" : "0") +
           ",INTERLOCK=" + (LIMIT_INTERLOCK_ENABLED ? "1" : "0") +
           ",OVERRIDE=" + (limitOverrideEnabled ? "1" : "0");
}

String InputSummary() {
    return String("INPUTS:ESTOP=") + (EstopActive() ? "1" : "0") +
           ",ESTOP_RAW=" + (RawEstopActive() ? "1" : "0") +
           ",ESTOP_OVERRIDE=" + (estopOverrideEnabled ? "1" : "0") +
           ",LIMIT_OWNER=PI" +
           ",LIMIT_INTERLOCK=" + (LIMIT_INTERLOCK_ENABLED ? "1" : "0") +
           ",LIMIT_OVERRIDE=" + (limitOverrideEnabled ? "1" : "0") +
           ",M0_HOME=" + (M0HomeActive() ? "1" : "0") +
           ",M0_HOME_RAW=" + (RawM0HomeActive() ? "1" : "0") +
           ",M0_LIMIT=" + (M0LimitActive() ? "1" : "0") +
           ",M0_LIMIT_RAW=" + (RawM0LimitActive() ? "1" : "0") +
           ",M1_HOME=" + (M1HomeActive() ? "1" : "0") +
           ",M1_HOME_RAW=" + (RawM1HomeActive() ? "1" : "0") +
           ",M1_LIMIT=" + (M1LimitActive() ? "1" : "0") +
           ",M1_LIMIT_RAW=" + (RawM1LimitActive() ? "1" : "0");
}

String ControllerStateSummary() {
    return String("CONTROLLER_STATE:FAULT=") + (controllerFaultLatched ? "1" : "0") +
           ",ESTOP=" + (EstopActive() ? "1" : "0") +
           ",ESTOP_RAW=" + (RawEstopActive() ? "1" : "0") +
           ",ESTOP_OVERRIDE=" + (estopOverrideEnabled ? "1" : "0") +
           ",LIMIT_OWNER=PI" +
           ",LIMIT_INTERLOCK=" + (LIMIT_INTERLOCK_ENABLED ? "1" : "0") +
           ",LIMIT_OVERRIDE=" + (limitOverrideEnabled ? "1" : "0") +
           ",M0_HOMED=" + (motor0Homed ? "1" : "0") +
           ",M1_HOMED=" + (motor1Homed ? "1" : "0");
}

String FaultSummary() {
    return String("FAULTS:ESTOP=") + (EstopActive() ? "1" : "0") +
           ",ESTOP_RAW=" + (RawEstopActive() ? "1" : "0") +
           ",ESTOP_OVERRIDE=" + (estopOverrideEnabled ? "1" : "0") +
           ",LIMIT_OWNER=PI" +
           ",LIMIT_INTERLOCK=" + (LIMIT_INTERLOCK_ENABLED ? "1" : "0") +
           ",LIMIT_OVERRIDE=" + (limitOverrideEnabled ? "1" : "0") +
           ",LATCH=" + (controllerFaultLatched ? "1" : "0") +
           ",LATCH_ESTOP=" + (controllerFaultFromEstop ? "1" : "0") +
           ",M0_DRIVER=" + (motor0.StatusReg().bit.MotorInFault ? "1" : "0") +
           ",M1_DRIVER=" + (motor1.StatusReg().bit.MotorInFault ? "1" : "0");
}

String EstopOverrideSummary() {
    return String("ESTOP_OVERRIDE:") + (estopOverrideEnabled ? "1" : "0");
}

String LimitOverrideSummary() {
    return String("LIMIT_OVERRIDE:") + (limitOverrideEnabled ? "1" : "0") +
           ",INTERLOCK=" + (LIMIT_INTERLOCK_ENABLED ? "1" : "0") +
           ",OWNER=PI";
}
