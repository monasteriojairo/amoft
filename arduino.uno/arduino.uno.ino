const int EnablePin = 8;
const int PWMPinA = 11;
const int PWMPinB = 3;
const int RetractConfirmPin = 4;

const int forwardSpeed = 255;
const int reverseSpeed = 255;

const unsigned long retractTime = 8000;
const unsigned long extendTime = 8000;
const unsigned long cyclePauseTime = 500;
const bool retractConfirmActiveLow = true;

String command = "";

enum MotionState {
  IDLE,
  EXTENDING,
  RETRACTING,
  HOMING_RETRACTING,
  CYCLE_RETRACTING,
  CYCLE_PAUSE,
  CYCLE_EXTENDING,
  FAULTED
};

MotionState motionState = IDLE;
unsigned long motionStartedAt = 0;
unsigned long pauseStartedAt = 0;
String lastFault = "";

void setup() {
  pinMode(EnablePin, OUTPUT);
  digitalWrite(EnablePin, LOW);
  pinMode(PWMPinA, OUTPUT);
  analogWrite(PWMPinA, 0);
  pinMode(PWMPinB, OUTPUT);
  analogWrite(PWMPinB, 0);
  pinMode(RetractConfirmPin, INPUT_PULLUP);

  stopMotor();
  Serial.begin(9600);
  Serial.setTimeout(100);
}

void loop() {
  updateMotion();

  if (Serial.available() > 0) {
    command = Serial.readStringUntil('\n');
    command.trim();

    if (command == "EXTEND") {
      if (motionState == FAULTED) {
        Serial.println("ERR FAULTED");
      }
      else {
        startExtend();
        Serial.println("STARTED EXTEND");
      }
    }

    else if (command == "RETRACT") {
      if (motionState == FAULTED) {
        Serial.println("ERR FAULTED");
      }
      else {
        startRetract();
        Serial.println("STARTED RETRACT");
      }
    }

    else if (command == "HOME" || command == "HOME_ACTUATOR" || command == "RETRACT_TO_HOME") {
      if (motionState == FAULTED) {
        Serial.println("ERR FAULTED");
      }
      else if (retractConfirmActive()) {
        stopMotor();
        motionState = IDLE;
        Serial.println("DONE HOME");
      }
      else {
        startHomeRetract();
        Serial.println("STARTED HOME");
      }
    }

    else if (command == "CYCLE") {
      if (motionState == FAULTED) {
        Serial.println("ERR FAULTED");
      }
      else {
        startCycle();
        Serial.println("STARTED CYCLE");
      }
    }

    else if (command == "STOP" || command == "STOP_ACTUATOR") {
      stopMotor();
      motionState = IDLE;
      Serial.println("STOPPED");
    }

    else if (command == "PING") {
      Serial.println("PONG");
    }

    else if (command == "STATUS" || command == "STATUS_ACTUATOR") {
      Serial.println(currentStatus());
    }

    else if (command == "LIMITS") {
      Serial.println(limitSummary());
    }

    else if (command == "CLEAR_FAULT") {
      if (!retractConfirmActive()) {
        lastFault = "";
      }
      motionState = IDLE;
      Serial.println("OK CLEAR_FAULT");
    }

    else if (command == "CAPS") {
      Serial.println("CAPS:ACTUATOR,STATUS,LIMITS,HOME");
    }

    else {
      Serial.println("ERR UNKNOWN_CMD");
    }
  }
}

bool retractConfirmActive() {
  int raw = digitalRead(RetractConfirmPin);
  return retractConfirmActiveLow ? raw == LOW : raw == HIGH;
}

void startExtend() {
  lastFault = "";
  runForward(forwardSpeed);
  motionState = EXTENDING;
  motionStartedAt = millis();
}

void startRetract() {
  lastFault = "";
  runReverse(reverseSpeed);
  motionState = RETRACTING;
  motionStartedAt = millis();
}

void startHomeRetract() {
  lastFault = "";
  runReverse(reverseSpeed);
  motionState = HOMING_RETRACTING;
  motionStartedAt = millis();
}

void startCycle() {
  lastFault = "";
  runReverse(reverseSpeed);
  motionState = CYCLE_RETRACTING;
  motionStartedAt = millis();
}

void faultStop(const char *reason, const char *message) {
  stopMotor();
  motionState = FAULTED;
  lastFault = reason;
  Serial.println(message);
}

void updateMotion() {
  unsigned long now = millis();

  if (motionState == EXTENDING && now - motionStartedAt >= extendTime) {
    stopMotor();
    motionState = IDLE;
    Serial.println("DONE EXTEND");
  }
  else if (motionState == RETRACTING) {
    if (retractConfirmActive()) {
      stopMotor();
      motionState = IDLE;
      Serial.println("DONE RETRACT");
    }
    else if (now - motionStartedAt >= retractTime) {
      faultStop("RETRACT_TIMEOUT", "ERR RETRACT TIMEOUT");
    }
  }
  else if (motionState == HOMING_RETRACTING) {
    if (retractConfirmActive()) {
      stopMotor();
      motionState = IDLE;
      Serial.println("DONE HOME");
    }
    else if (now - motionStartedAt >= retractTime) {
      faultStop("HOME_TIMEOUT", "ERR HOME TIMEOUT");
    }
  }
  else if (motionState == CYCLE_RETRACTING) {
    if (retractConfirmActive()) {
      stopMotor();
      motionState = CYCLE_PAUSE;
      pauseStartedAt = now;
    }
    else if (now - motionStartedAt >= retractTime) {
      faultStop("CYCLE_RETRACT_TIMEOUT", "ERR CYCLE RETRACT TIMEOUT");
    }
  }
  else if (motionState == CYCLE_PAUSE && now - pauseStartedAt >= cyclePauseTime) {
    runForward(forwardSpeed);
    motionState = CYCLE_EXTENDING;
    motionStartedAt = now;
  }
  else if (motionState == CYCLE_EXTENDING && now - motionStartedAt >= extendTime) {
    stopMotor();
    motionState = IDLE;
    Serial.println("DONE CYCLE");
  }
}

const char *currentStatus() {
  switch (motionState) {
    case EXTENDING:
      return "EXTENDING";
    case RETRACTING:
      return "RETRACTING";
    case HOMING_RETRACTING:
      return "HOMING";
    case CYCLE_RETRACTING:
    case CYCLE_PAUSE:
    case CYCLE_EXTENDING:
      return "CYCLING";
    case FAULTED:
      return "FAULT";
    case IDLE:
    default:
      return retractConfirmActive() ? "RETRACTED" : "READY";
  }
}

String limitSummary() {
  return String("LIMITS:RETRACT=") + (retractConfirmActive() ? "1" : "0") +
         ",FAULT=" + (motionState == FAULTED ? "1" : "0");
}

void runForward(int speedVal) {
  digitalWrite(EnablePin, HIGH);
  analogWrite(PWMPinA, speedVal);
  analogWrite(PWMPinB, 0);
}

void runReverse(int speedVal) {
  digitalWrite(EnablePin, HIGH);
  analogWrite(PWMPinA, 0);
  analogWrite(PWMPinB, speedVal);
}

void stopMotor() {
  digitalWrite(EnablePin, LOW);
  analogWrite(PWMPinA, 0);
  analogWrite(PWMPinB, 0);
}
