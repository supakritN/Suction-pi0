/*
 * Suction Training Probe - Dry Prototype
 * Arduino UNO sensor node
 *
 * Sensors:
 *   - 10x IR sensors (digital HIGH/LOW), depth landmarks S1..S5 etc.
 *   - 1x HX710B pressure module (24-bit digital, 2-wire SCK/DOUT)
 *
 * Output: one JSON line per sample over USB serial to the Raspberry Pi.
 *
 * The HX710B is NOT analog - it has its own 24-bit ADC and is read by
 * bit-banging a clock. So the UNO's internal 10-bit ADC is never used and
 * pressure resolution is far higher than any MCU's built-in ADC.
 *
 * Serial commands (send a single character + newline):
 *   z  -> tare / re-zero pressure to current reading (use after reinstall)
 *   ?  -> print the config/hello line again
 */

// ---------------- Pin map ----------------
//   Arduino pin  ->  Sensor
//   D0  (RX)     ->  reserved (USB serial)
//   D1  (TX)     ->  reserved (USB serial)
//   D2           ->  IR  S1   (shallowest / first landmark)
//   D3           ->  IR  S2
//   D4           ->  IR  S3
//   D5           ->  IR  S4
//   D6           ->  IR  S5
//   D7           ->  IR  S6
//   D8           ->  IR  S7
//   D9           ->  IR  S8
//   D10          ->  IR  S9
//   D11          ->  IR  S10  (deepest / last landmark)
//   D12          ->  HX710B  DOUT (data)
//   D13          ->  HX710B  SCK  (clock)
//   5V / GND     ->  sensor power rails
//
// Rename the S1..S10 labels below to your real landmark names.

// ---------------- Configuration ----------------
#define NUM_IR 10

// IR sensor pins (D2..D11). Keep D0/D1 free for USB serial.
const uint8_t IR_PINS[NUM_IR] = {2, 3, 4, 5, 6, 7, 8, 9, 10, 11};

// Human-readable name for each IR sensor (used as the JSON key).
// Must line up 1:1 with IR_PINS above. Edit these to your landmark names.
const char* const IR_NAMES[NUM_IR] = {
  "S1", "S2", "S3", "S4", "S5",
  "S6", "S7", "S8", "S9", "S10"
};

// Most cheap IR modules pull the line LOW when a target is detected.
// Set false if yours goes HIGH on detect.
const bool IR_ACTIVE_LOW = true;

// Use internal pull-ups on IR pins (safe for open-collector outputs).
const bool IR_USE_PULLUP = true;

// HX710B pins
const uint8_t HX_DOUT = 12;   // data out from module
const uint8_t HX_SCK  = 13;   // clock into module (also drives onboard LED - fine)

const unsigned long BAUD = 115200;

// Output format:
//   0 = human-readable line (pins + full-word status). Good for eyeballing.
//   1 = JSON line. Good for the Raspberry Pi to parse.
#define OUTPUT_JSON 0

// Full-word status labels for the readable format.
#define TXT_DETECT "DETECT"   // IR sees the probe
#define TXT_CLEAR  "clear"    // IR sees nothing
#define TXT_POK    "OK"       // pressure sensor responded
#define TXT_PERR   "BROKEN"   // pressure sensor timed out / unplugged

// Averaging: number of HX710B samples to average per reported value.
// 1 = report every ~25ms (native 40Hz). Increase to smooth noise (lower rate).
#define P_AVG 1

// Pressure calibration (raw counts -> kPa).
//   kpa = (raw - P_OFFSET) * P_SCALE
// P_OFFSET is auto-tared at boot (assumes atmospheric at power-on) and by 'z'.
// P_SCALE must be set from a 2-point calibration - see CALIBRATION note below.
float P_SCALE = 0.000050;   // <-- PLACEHOLDER. Calibrate for your sensor.
long  P_OFFSET = 0;         // set automatically at boot / on 'z'

// HX710B extra-pulse mode: 1 = differential input @ ~40Hz (standard for pressure)
const uint8_t HX_MODE_PULSES = 1;

// Read timeout so a disconnected/broken sensor never hangs the loop.
const unsigned long HX_TIMEOUT_MS = 100;

// ---------------- Globals ----------------
char cmdBuf[8];
uint8_t cmdLen = 0;

// ---------------- HX710B driver ----------------
bool hxReady() {
  return digitalRead(HX_DOUT) == LOW;   // DOUT goes LOW when a sample is ready
}

// Reads one 24-bit two's-complement sample. Returns false on timeout.
bool hxReadRaw(long &out) {
  unsigned long start = millis();
  while (!hxReady()) {
    if (millis() - start > HX_TIMEOUT_MS) return false;
  }

  long value = 0;
  for (uint8_t i = 0; i < 24; i++) {
    digitalWrite(HX_SCK, HIGH);
    delayMicroseconds(1);
    value = (value << 1) | digitalRead(HX_DOUT);
    digitalWrite(HX_SCK, LOW);
    delayMicroseconds(1);
  }

  // Extra pulses select input/rate for the NEXT conversion.
  for (uint8_t i = 0; i < HX_MODE_PULSES; i++) {
    digitalWrite(HX_SCK, HIGH);
    delayMicroseconds(1);
    digitalWrite(HX_SCK, LOW);
    delayMicroseconds(1);
  }

  // Sign-extend 24-bit value to 32-bit.
  if (value & 0x800000L) value |= 0xFF000000L;

  out = value;
  return true;
}

// Averaged read. Returns false if any sub-read times out.
bool hxReadAvg(long &out) {
  long sum = 0;
  for (uint8_t i = 0; i < P_AVG; i++) {
    long v;
    if (!hxReadRaw(v)) return false;
    sum += v;
  }
  out = sum / (long)P_AVG;
  return true;
}

// Tare: set P_OFFSET to the current reading. Returns false on timeout.
bool hxTare() {
  long v;
  if (!hxReadAvg(v)) return false;
  P_OFFSET = v;
  return true;
}

// ---------------- Serial command handling ----------------
void printHello() {
#if OUTPUT_JSON
  Serial.print(F("{\"hello\":\"suction_probe\",\"fw\":\"1.0\",\"ir\":"));
  Serial.print(NUM_IR);
  Serial.print(F(",\"p_avg\":"));
  Serial.print(P_AVG);
  Serial.print(F(",\"p_offset\":"));
  Serial.print(P_OFFSET);
  Serial.println(F("}"));
#else
  Serial.print(F("# suction_probe fw 1.0 | IR sensors: "));
  Serial.print(NUM_IR);
  Serial.print(F(" | p_avg: "));
  Serial.print(P_AVG);
  Serial.print(F(" | p_offset: "));
  Serial.println(P_OFFSET);
#endif
}

void handleCommand(char c) {
  if (c == 'z') {                 // re-zero pressure
    bool ok = hxTare();
#if OUTPUT_JSON
    Serial.print(F("{\"ack\":\"tare\",\"ok\":"));
    Serial.print(ok ? F("true") : F("false"));
    Serial.print(F(",\"p_offset\":"));
    Serial.print(P_OFFSET);
    Serial.println(F("}"));
#else
    Serial.print(F("# tare "));
    Serial.print(ok ? F("OK") : F("FAILED"));
    Serial.print(F(" | p_offset: "));
    Serial.println(P_OFFSET);
#endif
  } else if (c == '?') {
    printHello();
  }
}

void pollSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (cmdLen > 0) { handleCommand(cmdBuf[0]); cmdLen = 0; }
    } else if (cmdLen < sizeof(cmdBuf) - 1) {
      cmdBuf[cmdLen++] = c;
    }
  }
}

// ---------------- Setup / Loop ----------------
void setup() {
  Serial.begin(BAUD);

  for (uint8_t i = 0; i < NUM_IR; i++) {
    pinMode(IR_PINS[i], IR_USE_PULLUP ? INPUT_PULLUP : INPUT);
  }

  pinMode(HX_SCK, OUTPUT);
  pinMode(HX_DOUT, INPUT);
  digitalWrite(HX_SCK, LOW);

  delay(50);
  hxTare();        // assume atmospheric at power-on
  printHello();
}

void loop() {
  pollSerial();

  // --- IR sensors (instant digital reads) ---
  uint8_t ir[NUM_IR];
  for (uint8_t i = 0; i < NUM_IR; i++) {
    bool raw = digitalRead(IR_PINS[i]);
    bool detected = IR_ACTIVE_LOW ? (raw == LOW) : (raw == HIGH);
    ir[i] = detected ? 1 : 0;
  }

  // --- Pressure (paces the loop to ~40Hz) ---
  long praw;
  bool pok = hxReadAvg(praw);
  float kpa = pok ? (float)(praw - P_OFFSET) * P_SCALE : 0.0f;

  // --- Emit one line ---
#if OUTPUT_JSON
  // Machine-readable JSON for the Raspberry Pi.
  Serial.print(F("{\"t\":"));
  Serial.print(millis());
  Serial.print(F(",\"ir\":{"));
  for (uint8_t i = 0; i < NUM_IR; i++) {
    Serial.print('"');
    Serial.print(IR_NAMES[i]);
    Serial.print(F("\":"));
    Serial.print(ir[i]);
    if (i < NUM_IR - 1) Serial.print(',');
  }
  Serial.print(F("},\"p_ok\":"));
  Serial.print(pok ? F("true") : F("false"));
  Serial.print(F(",\"p_raw\":"));
  Serial.print(praw);
  Serial.print(F(",\"kpa\":"));
  Serial.print(kpa, 3);
  Serial.println(F("}"));
#else
  // Human-readable line: tstamp | each IR as  D<pin>/<name>:STATUS | pressure
  Serial.print(F("tstamp: "));
  Serial.print(millis());
  Serial.print(F("ms | IRs: "));
  for (uint8_t i = 0; i < NUM_IR; i++) {
    Serial.print('D');
    Serial.print(IR_PINS[i]);
    Serial.print('/');
    Serial.print(IR_NAMES[i]);
    Serial.print(':');
    Serial.print(ir[i] ? F(TXT_DETECT) : F(TXT_CLEAR));
    if (i < NUM_IR - 1) Serial.print(F("  "));
  }
  Serial.print(F(" | P(D"));
  Serial.print(HX_DOUT);
  Serial.print(F("/D"));
  Serial.print(HX_SCK);
  Serial.print(F("): "));
  if (pok) {
    Serial.print(kpa, 3);
    Serial.print(F(" kPa  "));
    Serial.println(F(TXT_POK));
  } else {
    Serial.print(F("--- kPa  "));   // no reading available
    Serial.println(F(TXT_PERR));    // sensor timed out / unplugged
  }
#endif

  // If the pressure sensor timed out, avoid a tight busy-loop.
  if (!pok) delay(25);
}

/*
 * ---------------- CALIBRATION (do this once per sensor) ----------------
 * 1. Power up at atmospheric pressure. Boot auto-tares P_OFFSET (or send 'z').
 * 2. Note raw0 = p_raw at 0 kPa (should be ~0 after tare).
 * 3. Apply a known pressure Pk (kPa) with a reference gauge/manometer.
 *    Note raw1 = p_raw at that pressure.
 * 4. P_SCALE = Pk / (raw1 - raw0). Put that number in P_SCALE above and reflash.
 *
 * Tip: for the wet prototype, send 'z' after every reinstall to null out any
 * offset shift from re-seating the sensor - this protects your scoring
 * baseline without touching the sensor element.
 */
