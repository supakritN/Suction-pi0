#include <WiFi.h>
#include <WebServer.h>
#include <Preferences.h>
#include <DNSServer.h>
#include <esp_log.h>
#include "SensorStats.h"

WebServer server(80);
Preferences prefs;
DNSServer dnsServer;

IPAddress apIP(192, 168, 4, 1);
IPAddress gateway(192, 168, 4, 1);
IPAddress subnet(255, 255, 255, 0);
IPAddress dhcpStartIP(192, 168, 4, 2);

static const char* AP_SSID = "ESP32-Setup";
static const char* AP_PASSWORD = "12345678";
static const char* APP_LOG_TAG = "SUCTION_APP";
static const unsigned long WIFI_CONNECT_TIMEOUT_MS = 15000;

static const int LIGHT_SENSOR_PINS[5] = {15, 16, 9, 17, 10};
// Map distance and IR sensor
static const int SENSOR_DEPTH_CM[5] = {0, 6, 6, 8, 8};

// pressure
static const int HX_DOUT_PIN = 4;   // use a free GPIO
static const int HX_SCK_PIN  = 5;   // use a free GPIO

static const int PRESSURE_HX710_READ_PULSES = 27;      // 27 = differential input, 40Hz on HX710B
static const uint32_t PRESSURE_HX710_READY_TIMEOUT_MS = 120;
static const uint32_t PRESSURE_DEBUG_READY_TIMEOUT_MS = 30;
static const int32_t PRESSURE_REFERENCE_REST_DELTA_RAW = 65000;     // suction on, tube open, after zero deadband
static const int32_t PRESSURE_REFERENCE_FOLD_MIN_DELTA_RAW = 152000;
static const int32_t PRESSURE_REFERENCE_70_MMHG_DELTA_RAW = 515000;
static const int32_t PRESSURE_REFERENCE_80_MMHG_DELTA_RAW = 561000;
static const int32_t PRESSURE_REFERENCE_120_MMHG_DELTA_RAW = 757000;
static const int32_t PRESSURE_REFERENCE_130_MMHG_DELTA_RAW = 770000;
static const int PRESSURE_ACTIVE_RAW_DIRECTION = -1;    // diagnostic delta rises when the raw sensor value drops
static const int32_t PRESSURE_FOLD_MIN_RAW =
  (PRESSURE_REFERENCE_REST_DELTA_RAW + PRESSURE_REFERENCE_FOLD_MIN_DELTA_RAW) / 2;
static const int32_t PRESSURE_READY_MIN_RAW = PRESSURE_REFERENCE_80_MMHG_DELTA_RAW - 20000;
static const int32_t PRESSURE_RELEASE_DROP_RAW = 60000; // required drop from folded reference
static const int PRESSURE_RELEASE_MAX_RATIO_PERCENT = 70; // tune: current <= this % of folded reference
static const int PRESSURE_FOLDED_REFERENCE_UPDATE_MIN_RATIO_PERCENT = 85;
static const uint32_t PRESSURE_RELEASE_HOLD_MS = 200;  // tune: debounce release detection
static const int PRESSURE_SCORE_BUFFER_SIZE = 5;       // latest folded samples before release
static const int PRESSURE_MAX_FAILS_PER_READ = 3;
static const int PRESSURE_MAX_AVERAGE_SAMPLES = 256;
static const int PRESSURE_CALIBRATION_SAMPLES = 200;
static const int PRESSURE_CALIBRATION_DELAY_MS = 50;
static const int32_t PRESSURE_CAL_STABLE_MAX_TRIMMED_RANGE_RAW = 12000;
static const int PRESSURE_READY_CHECK_SAMPLES = 20;
static const int PRESSURE_READY_CHECK_DELAY_MS = 20;
static const int32_t PRESSURE_READY_STABLE_MAX_TRIMMED_RANGE_RAW = 5000;
static const int32_t PRESSURE_READY_MAX_ZERO_DRIFT_RAW = 12000;
static const int32_t PRESSURE_READY_OPEN_SUCTION_BUFFER_RAW = 25000;
static const int32_t PRESSURE_ZERO_DEADBAND_MIN_RAW = 8000;
static const int32_t PRESSURE_ZERO_DEADBAND_MAX_RAW = 12000;
static const int PRESSURE_ZERO_DEADBAND_RANGE_MULTIPLIER = 8;
static const int32_t PRESSURE_ZERO_TRACK_MAX_RAW = 12000;
static const int PRESSURE_ZERO_TRACK_DIVISOR = 4;
static const int PRESSURE_INSERT_READ_SAMPLES = 3;
static const int PRESSURE_INSERT_READ_DELAY_MS = 0;
static const int PRESSURE_DEBUG_READ_SAMPLES = 1;
static const bool PRESSURE_SCORE_ENABLED = true;
static const int PRESSURE_MAX_SCORE = 20;
static const int CONTACT_MAX_SCORE = 30;
static const float PRESSURE_CAL_LOW_MMHG = 80.0f;
static const float PRESSURE_CAL_PRE_LOW_MMHG = 70.0f;
static const int32_t PRESSURE_CAL_PRE_LOW_DELTA_RAW = PRESSURE_REFERENCE_70_MMHG_DELTA_RAW;
static const int32_t PRESSURE_CAL_LOW_DELTA_RAW = PRESSURE_REFERENCE_80_MMHG_DELTA_RAW;
static const float PRESSURE_CAL_HIGH_MMHG = 120.0f;
static const int32_t PRESSURE_CAL_HIGH_DELTA_RAW = PRESSURE_REFERENCE_120_MMHG_DELTA_RAW;
static const float PRESSURE_CAL_POST_HIGH_MMHG = 130.0f;
static const int32_t PRESSURE_CAL_POST_HIGH_DELTA_RAW = PRESSURE_REFERENCE_130_MMHG_DELTA_RAW;

// IR sensor
static const int LIGHT_DELTA_DISABLED_POSITIVE = 4096;
static const int LIGHT_DELTA_DISABLED_NEGATIVE = -4096;
static const int LIGHT_SENSOR0_DETECT_ABS_DELTA = 200;
static const int LIGHT_SENSOR0_OPAQUE_DELTA_MIN = LIGHT_SENSOR0_DETECT_ABS_DELTA;
static const int LIGHT_SENSOR0_TRANSPARENT_DELTA_MAX = -LIGHT_SENSOR0_DETECT_ABS_DELTA;
static const int LIGHT_SENSOR0_CLEAR_ABS_DELTA = 20;
static const int LIGHT_DETECT_ON_POSITIVE_DELTA[5] = {
  LIGHT_SENSOR0_OPAQUE_DELTA_MIN,
  LIGHT_DELTA_DISABLED_POSITIVE,
  LIGHT_DELTA_DISABLED_POSITIVE,
  LIGHT_DELTA_DISABLED_POSITIVE,
  LIGHT_DELTA_DISABLED_POSITIVE
};
static const int LIGHT_DETECT_ON_NEGATIVE_DELTA[5] = {LIGHT_SENSOR0_TRANSPARENT_DELTA_MAX, -200, -200, -200, -200};
static const int LIGHT_DETECT_OFF_POSITIVE_DELTA[5] = {
  LIGHT_SENSOR0_CLEAR_ABS_DELTA,
  LIGHT_DELTA_DISABLED_POSITIVE,
  LIGHT_DELTA_DISABLED_POSITIVE,
  LIGHT_DELTA_DISABLED_POSITIVE,
  LIGHT_DELTA_DISABLED_POSITIVE
};
static const int LIGHT_DETECT_OFF_NEGATIVE_DELTA[5] = {-LIGHT_SENSOR0_CLEAR_ABS_DELTA, -80, -80, -80, -80};
static const int LIGHT_DETECT_ON_THRESHOLDS[5] = {LIGHT_SENSOR0_DETECT_ABS_DELTA, 200, 200, 200, 200};
static const int LIGHT_DETECT_OFF_THRESHOLDS[5] = {LIGHT_SENSOR0_CLEAR_ABS_DELTA, 80, 80, 80, 80};
static const int LIGHT_READY_CLEAR_ABS_DELTA[5] = {LIGHT_SENSOR0_CLEAR_ABS_DELTA, 80, 80, 80, 80};
static const uint8_t LIGHT_DEBOUNCE_COUNT = 3;
static const int LIGHT_CALIBRATION_SAMPLES = 1000;
static const int LIGHT_CALIBRATION_DELAY_MS = 10;
static const int LIGHT_READY_CHECK_SAMPLES = 20;
static const int LIGHT_READY_CHECK_DELAY_MS = 10;
static const uint16_t LIGHT_READY_STABLE_MAX_RANGE[5] = {80, 20, 20, 50, 50};

// contact logic
static const int CONTACT_BAND_ON_SIGNED_DELTA = 1500;   // neck sensor enters black band
static const int CONTACT_BAND_OFF_SIGNED_DELTA = 1000;  // neck sensor leaves black band
static const uint8_t CONTACT_BAND_DEBOUNCE_COUNT = 2;
static const int CONTACT_MARKER_COUNT = 2;
static const int CONTACT_MARKER_DEPTH_CM[CONTACT_MARKER_COUNT] = {6, 8}; // depth marker order after the front entry marker

static const bool DEBUG_LIVE_LOG = false;
static const unsigned long SERIAL_DEBUG_INTERVAL_MS = 250;
static const unsigned long STARTUP_DELAY_MS = 500;


// =========================
// Data model
// =========================
enum AppMode : uint8_t {
  MODE_UNSET   = 0,
  MODE_OFFLINE = 1,
  MODE_ONLINE  = 2
};

enum CalibrateStep : uint8_t {
  CAL_STEP_LIGHT = 0,
  CAL_STEP_PRESSURE = 1,
  CAL_STEP_DONE = 2
};

struct DeviceConfig {
  bool configured = false;
  AppMode mode = MODE_UNSET;
  String ssid = "";
  String password = "";

  CalibrateStep calibrateStep = CAL_STEP_LIGHT;

  bool lightCalibrated = false;
  uint16_t lightBaselines[5] = {0, 0, 0, 0, 0};

  bool pressureCalibrated = false;
  int32_t pressureZeroRaw = 0;
  int32_t pressureZeroDeadbandRaw = PRESSURE_ZERO_DEADBAND_MIN_RAW;

  bool serialDebugEnabled = false;
};

// =========================
// Forward declarations
// =========================
class SetupContext;

class AppState {
public:
  virtual ~AppState() {}
  virtual const char* name() const = 0;
  virtual bool ownsSerialSensorSampling() const { return false; }

  virtual void enter(SetupContext& ctx) {}
  virtual void update(SetupContext& ctx) {}

  virtual void onModeSelected(SetupContext& ctx, const String& mode) {}
  virtual void onConnectWifi(SetupContext& ctx, const String& ssid, const String& password) {}
  virtual void onBack(SetupContext& ctx) {}
  virtual void onReset(SetupContext& ctx) {}
  virtual void onStartInsert(SetupContext& ctx) {}

  virtual String renderPage(SetupContext& ctx) = 0;
};

class SetupFlowState : public AppState {
};

class WorkingFlowState : public AppState {
protected:
  static const unsigned long SAMPLE_INTERVAL_MS = 100;
};

AppState& modeSelectState();
AppState& wifiConfigState();
AppState& wifiConnectingState();
AppState& readyState();
AppState& calibrateState();
AppState& insertState();
AppState& suctionState();
AppState& scoreState();

// =========================
// Helpers
// =========================
String htmlEscape(const String& s) {
  String out = s;
  out.replace("&", "&amp;");
  out.replace("<", "&lt;");
  out.replace(">", "&gt;");
  out.replace("\"", "&quot;");
  out.replace("'", "&#39;");
  return out;
}

String jsonEscape(const String& s) {
  String out = s;
  out.replace("\\", "\\\\");
  out.replace("\"", "\\\"");
  out.replace("\r", "\\r");
  out.replace("\n", "\\n");
  return out;
}

void appendJsonString(String& json, const char* key, const String& value) {
  if (json.length() > 1) json += ",";
  json += "\"";
  json += key;
  json += "\":\"";
  json += jsonEscape(value);
  json += "\"";
}

String modeLabel(AppMode mode) {
  switch (mode) {
    case MODE_OFFLINE: return "offline";
    case MODE_ONLINE:  return "online";
    default:           return "unset";
  }
}

void appLogLine(const String& message) {
  Serial.println(message);
  Serial.flush();
  ESP_LOGE(APP_LOG_TAG, "%s", message.c_str());
}

String pageStart(const String& title, bool autoRefresh = false) {
  String p;
  p += "<!doctype html><html><head>";
  p += "<meta charset='utf-8'>";
  p += "<meta name='viewport' content='width=device-width, initial-scale=1'>";
  if (autoRefresh) {
    p += "<meta http-equiv='refresh' content='2'>";
  }
  p += "<title>" + title + "</title>";
  p += "<style>";
  p += ":root{color-scheme:light;--bg:#f4f6f8;--card:#fff;--text:#172026;--muted:#64717d;--line:#d9e0e6;--primary:#14532d;--primaryText:#fff;--soft:#eef3f5;--okBg:#e7f7ed;--ok:#14532d;--warnBg:#fff6dd;--warn:#7a4b00;--errBg:#fdebed;--err:#991b1b;}";
  p += "*{box-sizing:border-box;}";
  p += "body{font-family:Arial,sans-serif;margin:0;background:var(--bg);color:var(--text);line-height:1.45;}";
  p += ".card{width:min(760px,calc(100% - 24px));margin:12px auto 20px;background:var(--card);padding:22px;border:1px solid var(--line);border-radius:8px;box-shadow:0 8px 24px rgba(23,32,38,.08);}";
  p += "h2{margin:0 0 8px;font-size:28px;line-height:1.15;letter-spacing:0;}";
  p += "h3{margin:20px 0 10px;font-size:17px;}";
  p += ".lead{margin:0 0 18px;color:var(--muted);font-size:15px;}";
  p += ".row{margin-bottom:16px;}";
  p += ".section{padding-top:4px;margin-top:18px;border-top:1px solid var(--line);}";
  p += "label{display:block;margin-bottom:8px;font-weight:700;}";
  p += "input[type=text],input[type=password],select{width:100%;padding:12px;border:1px solid #b8c3cc;border-radius:8px;background:#fff;color:var(--text);font-size:16px;}";
  p += "button,.button{min-height:44px;padding:12px 16px;border:0;border-radius:8px;cursor:pointer;font-weight:700;font-size:15px;display:inline-flex;align-items:center;justify-content:center;text-decoration:none;}";
  p += ".primary{background:var(--primary);color:var(--primaryText);}";
  p += ".secondary{background:var(--soft);color:var(--text);border:1px solid var(--line);}";
  p += ".status{padding:13px 14px;border-radius:8px;background:var(--soft);border:1px solid var(--line);font-weight:700;}";
  p += ".small{font-size:14px;color:var(--muted);}";
  p += ".ok{background:var(--okBg);color:var(--ok);border-color:#bde6cc;}";
  p += ".warn{background:var(--warnBg);color:var(--warn);border-color:#f2d486;}";
  p += ".err{background:var(--errBg);color:var(--err);border-color:#f2b8c0;}";
  p += ".inline{display:inline-block;margin-right:8px;margin-bottom:8px;vertical-align:top;}";
  p += ".actions{display:flex;flex-wrap:wrap;gap:8px;align-items:center;}";
  p += ".actions.spaced{margin-top:16px;}";
  p += ".actions form{display:inline-block;margin:0;}";
  p += ".mode-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;}";
  p += ".mode-card{padding:14px;border:1px solid var(--line);border-radius:8px;background:#fbfcfd;}";
  p += ".mode-card input{margin-right:8px;}";
  p += ".mode-card span{display:block;margin-left:24px;font-weight:400;color:var(--muted);font-size:13px;}";
  p += ".steps{display:grid;gap:8px;margin:12px 0 18px;}";
  p += ".step{display:flex;gap:10px;align-items:flex-start;padding:11px;border:1px solid var(--line);border-radius:8px;background:#fbfcfd;}";
  p += ".step b{display:grid;place-items:center;flex:0 0 26px;height:26px;border-radius:50%;background:var(--soft);color:var(--text);font-size:13px;}";
  p += ".step.done b{background:var(--ok);color:#fff;}";
  p += ".step.active{border-color:#9dc9ad;background:#f3fbf6;}";
  p += ".metric-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin:14px 0 18px;}";
  p += ".metric{padding:12px;border:1px solid var(--line);border-radius:8px;background:#fbfcfd;min-width:0;}";
  p += ".metric .label{font-size:12px;color:var(--muted);font-weight:700;text-transform:uppercase;}";
  p += ".metric .value{font-size:22px;font-weight:800;overflow-wrap:anywhere;}";
  p += ".score-hero{padding:16px;border:1px solid #bde6cc;border-radius:8px;background:var(--okBg);margin-bottom:14px;}";
  p += ".score-hero .value{font-size:44px;font-weight:800;line-height:1;}";
  p += "details{border:1px solid var(--line);border-radius:8px;background:#fbfcfd;padding:10px 12px;margin:14px 0;}";
  p += "summary{cursor:pointer;font-weight:700;color:var(--text);}";
  p += ".diagnostic-row{padding:8px 0;border-top:1px solid var(--line);font-size:13px;color:var(--muted);overflow-wrap:anywhere;}";
  p += "@media(max-width:560px){.card{width:100%;min-height:100vh;margin:0;border:0;border-radius:0;padding:18px;}h2{font-size:24px;}.mode-grid,.metric-grid{grid-template-columns:1fr;}button,.actions form,.actions a{width:100%;}.actions button,.actions .button{width:100%;}.inline{display:block;margin-right:0;}}";
  p += "</style></head><body><div class='card'>";
  return p;
}

String pageEnd() {
  return "</div></body></html>";
}

String statusHtml(const String& message, const String& tone = "") {
  String p = "<div class='row status";
  if (tone.length() > 0) {
    p += " ";
    p += tone;
  }
  p += "'>";
  p += htmlEscape(message);
  p += "</div>";
  return p;
}

String statusHtmlWithId(const String& message, const String& tone, const String& id) {
  String p = "<div id='";
  p += id;
  p += "' class='row status";
  if (tone.length() > 0) {
    p += " ";
    p += tone;
  }
  p += "'>";
  p += htmlEscape(message);
  p += "</div>";
  return p;
}

String metricHtml(const String& label, const String& value) {
  String p = "<div class='metric'><div class='label'>";
  p += htmlEscape(label);
  p += "</div><div class='value'>";
  p += htmlEscape(value);
  p += "</div></div>";
  return p;
}

String metricHtmlWithId(const String& label, const String& value, const String& valueId) {
  String p = "<div class='metric'><div class='label'>";
  p += htmlEscape(label);
  p += "</div><div id='";
  p += valueId;
  p += "' class='value'>";
  p += htmlEscape(value);
  p += "</div></div>";
  return p;
}

String liveUpdateScriptHtml(const char* expectedState) {
  String p;
  p += "<script>(function(){";
  p += "const expected='";
  p += expectedState;
  p += "';";
  p += "function set(id,v){const e=document.getElementById(id);if(e)e.textContent=v;}";
  p += "function poll(){fetch('/live.json?t='+Date.now(),{cache:'no-store'}).then(function(r){if(!r.ok)return null;return r.json();}).then(function(d){if(!d)return;if(d.state!==expected){location.replace('/');return;}set('live-status',d.status);const s=document.getElementById('live-status');if(s)s.className='row status '+d.statusTone;set('live-pressure',d.pressure);set('live-tube',d.tube);set('live-time',d.time);set('live-max-depth',d.maxDepth);set('live-current-depth',d.currentDepth);set('live-contact',d.contact);set('live-inside-index',d.insideIndex);set('live-inside-delta',d.insideDelta);set('live-tracking',d.tracking);set('live-depth',d.currentDepth);set('live-ready-suction',d.readySuction);set('live-pressure-raw',d.pressureRaw);set('live-pressure-zero',d.pressureZero);set('live-pressure-delta',d.pressureDelta);set('live-pressure-folded',d.pressureFolded);set('live-pressure-ready',d.pressureReady);set('live-folded-ref',d.foldedRef);set('live-score-pressure',d.scorePressure);set('live-pressure-captured',d.pressureCaptured);set('live-release',d.release);set('live-buffer',d.buffer);set('live-contact-entry',d.contactEntry);set('live-contact-bands',d.contactBands);set('live-contact-active',d.contactActive);set('live-contact-miss',d.contactMiss);set('live-contact-extra',d.contactExtra);set('live-neck-delta',d.neckDelta);set('live-contact-detected',d.contactDetected);set('live-contact-error',d.contactError);set('live-suction-started',d.suctionStarted);set('live-suction-completed',d.suctionCompleted);for(let i=0;i<5;i++){set('live-s'+i+'-cur',d['s'+i+'Cur']);set('live-s'+i+'-base',d['s'+i+'Base']);set('live-s'+i+'-signed',d['s'+i+'Signed']);set('live-s'+i+'-abs',d['s'+i+'Abs']);set('live-s'+i+'-detected',d['s'+i+'Detected']);}}).catch(function(){});}";
  p += "poll();setInterval(poll,250);";
  p += "})();</script>";
  return p;
}

String calibrationWaitAlertScriptHtml() {
  String p;
  p += "<script>(function(){";
  p += "const forms=document.querySelectorAll('form[data-calibrate]');";
  p += "if(!forms.length)return;";
  p += "forms.forEach(function(form){form.addEventListener('submit',function(ev){";
  p += "alert('Please wait 10 seconds while calibration runs.');";
  p += "});});";
  p += "})();</script>";
  return p;
}

String stepHtml(int number, const String& label, const String& detail, const String& state = "") {
  String p = "<div class='step";
  if (state.length() > 0) {
    p += " ";
    p += state;
  }
  p += "'><b>";
  p += String(number);
  p += "</b><div><strong>";
  p += htmlEscape(label);
  p += "</strong><div class='small'>";
  p += htmlEscape(detail);
  p += "</div></div></div>";
  return p;
}

String actionPostHtml(const String& action, const String& label, const String& className = "primary") {
  String p = "<form method='POST' action='";
  p += action;
  p += "'><button class='";
  p += className;
  p += "' type='submit'>";
  p += htmlEscape(label);
  p += "</button></form>";
  return p;
}

String actionLinkHtml(const String& href, const String& label, const String& className = "secondary") {
  String p = "<a class='button ";
  p += className;
  p += "' href='";
  p += href;
  p += "'>";
  p += htmlEscape(label);
  p += "</a>";
  return p;
}

String sensorRawControlHtml() {
  String p = "<div class='row actions spaced'>";
  p += actionLinkHtml("/sensors", "Real-time Sensors");
  p += "</div>";
  return p;
}

String sensorRawPageHtml() {
  String p = pageStart("Real-time Sensors");
  p += "<h2>Real-time Sensors</h2>";
  p += "<p class='lead'>Current raw sensor values.</p>";

  p += "<div class='metric-grid'>";
  p += metricHtmlWithId("Pressure raw", "--", "sensor-pressure");
  p += metricHtmlWithId("Neck GPIO15", "--", "sensor-l0");
  p += metricHtmlWithId("6 cm GPIO16", "--", "sensor-l1");
  p += metricHtmlWithId("6 cm GPIO9", "--", "sensor-l2");
  p += metricHtmlWithId("8 cm GPIO17", "--", "sensor-l3");
  p += metricHtmlWithId("8 cm GPIO10", "--", "sensor-l4");
  p += "</div>";

  p += "<div class='row actions'>";
  p += actionLinkHtml("/", "Back");
  p += "</div>";

  p += "<script>(function(){";
  p += "function set(id,v){const e=document.getElementById(id);if(e)e.textContent=v;}";
  p += "function poll(){fetch('/sensor-raw.json?t='+Date.now(),{cache:'no-store'}).then(function(r){if(!r.ok)return null;return r.json();}).then(function(d){if(!d)return;set('sensor-pressure',d.pressure);set('sensor-l0',d.l0);set('sensor-l1',d.l1);set('sensor-l2',d.l2);set('sensor-l3',d.l3);set('sensor-l4',d.l4);}).catch(function(){});}";
  p += "poll();setInterval(poll,250);";
  p += "})();</script>";
  p += pageEnd();
  return p;
}

String wifiOptionsHtml(const String& selectedSsid) {
  String options = "<option value=''>-- Select Wi-Fi --</option>";

  int n = WiFi.scanNetworks(false, true);  // sync scan
  if (n <= 0) {
    return options;
  }

  for (int i = 0; i < n; i++) {
    String ssid = WiFi.SSID(i);
    if (ssid.isEmpty()) continue;

    options += "<option value='";
    options += htmlEscape(ssid);
    options += "'";

    if (ssid == selectedSsid) {
      options += " selected";
    }

    options += ">";
    options += htmlEscape(ssid);
    options += " (";
    options += String(WiFi.RSSI(i));
    options += " dBm)";
    options += "</option>";
  }

  WiFi.scanDelete();
  return options;
}

void readLightBaselines(uint16_t outBaselines[5], int samples = 100, int delayMs = 10) {
  uint32_t sums[5] = {0, 0, 0, 0, 0};

  for (int i = 0; i < samples; i++) {
    for (int k = 0; k < 5; k++) {
      sums[k] += analogRead(LIGHT_SENSOR_PINS[k]);
    }
    delay(delayMs);
  }

  for (int k = 0; k < 5; k++) {
    outBaselines[k] = (uint16_t)(sums[k] / samples);
  }
}

void readCurrentLightValues(uint16_t outValues[5]) {
  for (int i = 0; i < 5; i++) {
    outValues[i] = analogRead(LIGHT_SENSOR_PINS[i]);
  }
}

bool readLightStats(int samples, int delayMs, LightReadStats& stats) {
  if (samples <= 0) return false;

  uint32_t sums[5] = {0, 0, 0, 0, 0};
  bool initialized = false;

  stats = LightReadStats();

  for (int i = 0; i < samples; i++) {
    for (int k = 0; k < 5; k++) {
      uint16_t value = analogRead(LIGHT_SENSOR_PINS[k]);
      sums[k] += value;

      if (!initialized) {
        stats.minValue[k] = value;
        stats.maxValue[k] = value;
      } else {
        if (value < stats.minValue[k]) stats.minValue[k] = value;
        if (value > stats.maxValue[k]) stats.maxValue[k] = value;
      }
    }

    initialized = true;

    if (delayMs > 0) {
      delay(delayMs);
    }
  }

  for (int k = 0; k < 5; k++) {
    stats.average[k] = (uint16_t)(sums[k] / samples);
    stats.range[k] = stats.maxValue[k] - stats.minValue[k];
  }

  return true;
}

bool waitHXReady(uint32_t timeoutMs = 1000) {
  uint32_t start = millis();
  while (digitalRead(HX_DOUT_PIN) == HIGH) {
    if (millis() - start >= timeoutMs) return false;
    delay(1);
  }
  return true;
}

int lightSignedDelta(uint16_t currentValue, uint16_t baselineValue) {
  return (int)currentValue - (int)baselineValue;
}

int lightAbsDelta(uint16_t currentValue, uint16_t baselineValue) {
  return abs(lightSignedDelta(currentValue, baselineValue));
}

bool isLightDetectCandidate(int index, uint16_t currentValue, uint16_t baselineValue) {
  int signedDelta = lightSignedDelta(currentValue, baselineValue);
  int delta = abs(signedDelta);

  if (index == 0) {
    return
      (signedDelta >= LIGHT_SENSOR0_OPAQUE_DELTA_MIN) ||
      (signedDelta <= LIGHT_SENSOR0_TRANSPARENT_DELTA_MAX);
  }

  return delta >= LIGHT_DETECT_ON_THRESHOLDS[index];
}

bool isLightClearCandidate(int index, uint16_t currentValue, uint16_t baselineValue) {
  int delta = lightAbsDelta(currentValue, baselineValue);

  if (index == 0) {
    return delta <= LIGHT_SENSOR0_CLEAR_ABS_DELTA;
  }

  return delta <= LIGHT_DETECT_OFF_THRESHOLDS[index];
}

uint32_t readHX24WithTimeout(int pulseCount, uint32_t readyTimeoutMs) {
  uint32_t count = 0;

  if (!waitHXReady(readyTimeoutMs)) return 0xFFFFFFFF;

  if (pulseCount < 25) pulseCount = 25;
  if (pulseCount > 27) pulseCount = 27;

  digitalWrite(HX_SCK_PIN, LOW);
  delayMicroseconds(5);

  for (int i = 0; i < 24; i++) {
    digitalWrite(HX_SCK_PIN, HIGH);
    delayMicroseconds(5);

    count <<= 1;

    digitalWrite(HX_SCK_PIN, LOW);
    delayMicroseconds(5);

    if (digitalRead(HX_DOUT_PIN)) count++;
  }

  for (int i = 24; i < pulseCount; i++) {
    digitalWrite(HX_SCK_PIN, HIGH);
    delayMicroseconds(5);
    digitalWrite(HX_SCK_PIN, LOW);
    delayMicroseconds(5);
  }

  return count;
}

uint32_t readHX24(int pulseCount) {
  return readHX24WithTimeout(pulseCount, PRESSURE_HX710_READY_TIMEOUT_MS);
}

uint32_t readHX24() {
  return readHX24(PRESSURE_HX710_READ_PULSES);
}

int32_t signExtend24(uint32_t x) {
  if (x & 0x800000) x |= 0xFF000000;
  return (int32_t)x;
}

bool readPressureRawStatsWithTimeout(
  int samples,
  int delayMs,
  PressureReadStats& stats,
  uint32_t readyTimeoutMs
) {
  if (samples <= 0) return false;
  if (samples > PRESSURE_MAX_AVERAGE_SAMPLES) samples = PRESSURE_MAX_AVERAGE_SAMPLES;

  stats = PressureReadStats();

  int32_t values[PRESSURE_MAX_AVERAGE_SAMPLES];
  int valid = 0;
  int fails = 0;

  for (int i = 0; i < samples; i++) {
    uint32_t raw24 = readHX24WithTimeout(PRESSURE_HX710_READ_PULSES, readyTimeoutMs);
    if (raw24 == 0xFFFFFFFF) {
      fails++;
      if (fails >= PRESSURE_MAX_FAILS_PER_READ) return false;
      continue;
    }

    values[valid++] = signExtend24(raw24);
    if (delayMs > 0) {
      delay(delayMs);
    }
  }

  stats.validCount = valid;
  stats.failCount = fails;

  if (valid == 0) return false;

  int64_t sum = 0;
  int32_t minValue = values[0];
  int32_t maxValue = values[0];
  int minIndex = 0;
  int maxIndex = 0;

  for (int i = 0; i < valid; i++) {
    if (values[i] < minValue) {
      minValue = values[i];
      minIndex = i;
    }

    if (values[i] > maxValue) {
      maxValue = values[i];
      maxIndex = i;
    }
  }

  stats.minRaw = minValue;
  stats.maxRaw = maxValue;
  stats.rangeRaw = maxValue - minValue;

  if (valid >= 5) {
    int trimmedCount = 0;
    bool hasTrimmedValue = false;
    int32_t trimmedMin = 0;
    int32_t trimmedMax = 0;

    for (int i = 0; i < valid; i++) {
      if (i == minIndex || i == maxIndex) continue;

      sum += values[i];

      if (!hasTrimmedValue) {
        trimmedMin = values[i];
        trimmedMax = values[i];
        hasTrimmedValue = true;
      } else {
        if (values[i] < trimmedMin) trimmedMin = values[i];
        if (values[i] > trimmedMax) trimmedMax = values[i];
      }

      trimmedCount++;
    }

    if (trimmedCount == 0) return false;

    stats.averageRaw = (int32_t)(sum / trimmedCount);
    stats.trimmedMinRaw = trimmedMin;
    stats.trimmedMaxRaw = trimmedMax;
    stats.trimmedRangeRaw = trimmedMax - trimmedMin;
    stats.trimmed = true;
    return true;
  }

  for (int i = 0; i < valid; i++) {
    sum += values[i];
  }

  stats.averageRaw = (int32_t)(sum / valid);
  stats.trimmedMinRaw = minValue;
  stats.trimmedMaxRaw = maxValue;
  stats.trimmedRangeRaw = stats.rangeRaw;
  stats.trimmed = false;
  return true;
}

bool readPressureRawStats(int samples, int delayMs, PressureReadStats& stats) {
  return readPressureRawStatsWithTimeout(
    samples,
    delayMs,
    stats,
    PRESSURE_HX710_READY_TIMEOUT_MS
  );
}

bool readPressureRawAverage(int samples, int delayMs, int32_t& outValue) {
  PressureReadStats stats;
  if (!readPressureRawStats(samples, delayMs, stats)) return false;

  outValue = stats.averageRaw;
  return true;
}

bool isPressureStable(const PressureReadStats& stats, int32_t maxTrimmedRangeRaw) {
  return stats.validCount > 0 && stats.trimmedRangeRaw <= maxTrimmedRangeRaw;
}

int32_t clampPressureDeadbandRaw(int32_t deadbandRaw) {
  if (deadbandRaw < PRESSURE_ZERO_DEADBAND_MIN_RAW) return PRESSURE_ZERO_DEADBAND_MIN_RAW;
  if (deadbandRaw > PRESSURE_ZERO_DEADBAND_MAX_RAW) return PRESSURE_ZERO_DEADBAND_MAX_RAW;
  return deadbandRaw;
}

int32_t pressureDeadbandFromStats(const PressureReadStats& stats) {
  int32_t deadbandRaw = stats.trimmedRangeRaw * PRESSURE_ZERO_DEADBAND_RANGE_MULTIPLIER;
  return clampPressureDeadbandRaw(deadbandRaw);
}

bool trackPressureZeroIfResting(DeviceConfig& config, int32_t raw) {
  int32_t signedDelta = raw - config.pressureZeroRaw;
  int32_t absDelta = abs(signedDelta);

  if (absDelta == 0 || absDelta > PRESSURE_ZERO_TRACK_MAX_RAW) {
    return false;
  }

  int32_t step = signedDelta / PRESSURE_ZERO_TRACK_DIVISOR;
  if (step == 0) {
    step = (signedDelta > 0) ? 1 : -1;
  }

  config.pressureZeroRaw += step;
  return true;
}

int32_t rawToDeltaRaw(int32_t raw, int32_t rawZero, int32_t deadbandRaw) {
  int32_t signedDelta = raw - rawZero;
  int32_t delta = (PRESSURE_ACTIVE_RAW_DIRECTION >= 0) ? signedDelta : -signedDelta;
  int32_t deadband = clampPressureDeadbandRaw(deadbandRaw);
  if (delta <= deadband) return 0;
  return delta - deadband;
}

int32_t rawToDeltaRaw(int32_t raw, int32_t rawZero) {
  return rawToDeltaRaw(raw, rawZero, PRESSURE_ZERO_DEADBAND_MIN_RAW);
}

bool isPressureReadyRaw(int32_t deltaRaw) {
  return deltaRaw >= PRESSURE_READY_MIN_RAW;
}

bool isPressureFoldedRaw(int32_t deltaRaw) {
  return deltaRaw >= PRESSURE_FOLD_MIN_RAW;
}

int pressureRatioPercent(int32_t currentDeltaRaw, int32_t referenceDeltaRaw) {
  if (referenceDeltaRaw <= 0) return 100;
  if (currentDeltaRaw <= 0) return 0;
  return (int)((int64_t)currentDeltaRaw * 100 / referenceDeltaRaw);
}

bool isReleaseCandidateRaw(int32_t currentDeltaRaw, int32_t referenceDeltaRaw) {
  if (referenceDeltaRaw < PRESSURE_FOLD_MIN_RAW) return false;

  int32_t dropRaw = referenceDeltaRaw - currentDeltaRaw;
  if (dropRaw < PRESSURE_RELEASE_DROP_RAW) return false;

  return pressureRatioPercent(currentDeltaRaw, referenceDeltaRaw) <= PRESSURE_RELEASE_MAX_RATIO_PERCENT;
}

bool isPressureFallingFromReferenceRaw(int32_t currentDeltaRaw, int32_t referenceDeltaRaw) {
  if (referenceDeltaRaw < PRESSURE_FOLD_MIN_RAW) return false;
  if (currentDeltaRaw >= referenceDeltaRaw) return false;

  int32_t dropRaw = referenceDeltaRaw - currentDeltaRaw;
  if (dropRaw >= PRESSURE_RELEASE_DROP_RAW) return true;

  return pressureRatioPercent(currentDeltaRaw, referenceDeltaRaw) < PRESSURE_FOLDED_REFERENCE_UPDATE_MIN_RATIO_PERCENT;
}

bool shouldUpdateFoldedPressureReferenceRaw(int32_t currentDeltaRaw, int32_t referenceDeltaRaw) {
  if (currentDeltaRaw < PRESSURE_FOLD_MIN_RAW) return false;
  if (referenceDeltaRaw < PRESSURE_FOLD_MIN_RAW) return true;

  return !isPressureFallingFromReferenceRaw(currentDeltaRaw, referenceDeltaRaw);
}

bool hasPressureMmHgMap() {
  return PRESSURE_SCORE_ENABLED &&
    (PRESSURE_CAL_PRE_LOW_DELTA_RAW < PRESSURE_CAL_LOW_DELTA_RAW) &&
    (PRESSURE_CAL_LOW_DELTA_RAW < PRESSURE_CAL_HIGH_DELTA_RAW) &&
    (PRESSURE_CAL_HIGH_DELTA_RAW < PRESSURE_CAL_POST_HIGH_DELTA_RAW);
}

float interpolatePressureMmHg(
  int32_t deltaRaw,
  int32_t lowDeltaRaw,
  float lowMmHg,
  int32_t highDeltaRaw,
  float highMmHg
) {
  float rawSpan = (float)(highDeltaRaw - lowDeltaRaw);
  if (rawSpan == 0.0f) return lowMmHg;
  return lowMmHg + (((float)deltaRaw - (float)lowDeltaRaw) * (highMmHg - lowMmHg) / rawSpan);
}

bool pressureDeltaRawToMmHg(int32_t deltaRaw, float& outMmHg) {
  if (!hasPressureMmHgMap()) return false;

  if (deltaRaw <= PRESSURE_CAL_LOW_DELTA_RAW) {
    outMmHg = interpolatePressureMmHg(
      deltaRaw,
      PRESSURE_CAL_PRE_LOW_DELTA_RAW,
      PRESSURE_CAL_PRE_LOW_MMHG,
      PRESSURE_CAL_LOW_DELTA_RAW,
      PRESSURE_CAL_LOW_MMHG
    );
  } else if (deltaRaw <= PRESSURE_CAL_HIGH_DELTA_RAW) {
    outMmHg = interpolatePressureMmHg(
      deltaRaw,
      PRESSURE_CAL_LOW_DELTA_RAW,
      PRESSURE_CAL_LOW_MMHG,
      PRESSURE_CAL_HIGH_DELTA_RAW,
      PRESSURE_CAL_HIGH_MMHG
    );
  } else {
    outMmHg = interpolatePressureMmHg(
      deltaRaw,
      PRESSURE_CAL_HIGH_DELTA_RAW,
      PRESSURE_CAL_HIGH_MMHG,
      PRESSURE_CAL_POST_HIGH_DELTA_RAW,
      PRESSURE_CAL_POST_HIGH_MMHG
    );
  }

  if (outMmHg < 0.0f) outMmHg = 0.0f;
  return true;
}

int scorePressureMmHg(float pressureMmHg) {
  if (pressureMmHg >= 80.0f && pressureMmHg <= 120.0f) return 20;
  if ((pressureMmHg >= 70.0f && pressureMmHg < 80.0f) ||
      (pressureMmHg > 120.0f && pressureMmHg <= 130.0f)) {
    return 10;
  }
  return 0;
}

String pressureScoreLabel(float pressureMmHg) {
  if (pressureMmHg >= 80.0f && pressureMmHg <= 120.0f) return "Standard";
  if (pressureMmHg >= 70.0f && pressureMmHg < 80.0f) return "Slightly low";
  if (pressureMmHg > 120.0f && pressureMmHg <= 130.0f) return "Slightly high";
  if (pressureMmHg < 70.0f) return "Too low";
  return "Too high";
}

int scoreDepthCm(int maxDepthCm) {
  if (maxDepthCm <= 0) return 30;
  if (maxDepthCm <= 6) return 15;
  return 0;
}

int scoreDurationMs(unsigned long durationMs) {
  if (durationMs == 0) return 0;

  float durationSec = durationMs / 1000.0f;
  if (durationSec <= 10.0f) return 20;
  if (durationSec <= 15.0f) return 10;
  return 0;
}

int scoreContactEvents(int contactEvents) {
  if (contactEvents <= 0) return 30;
  if (contactEvents <= 2) return 15;
  return 0;
}

int normalizeScore(int rawScore, int availableScore) {
  if (availableScore <= 0) return 0;
  return (rawScore * 100 + (availableScore / 2)) / availableScore;
}

String scoreLevel(int normalizedScore) {
  if (normalizedScore >= 90) return "Excellent";
  if (normalizedScore >= 70) return "Acceptable";
  if (normalizedScore >= 50) return "Needs Improvement";
  return "Unsafe";
}

String scoreInterpretation(int normalizedScore) {
  if (normalizedScore >= 90) return "Ready for real patient practice.";
  if (normalizedScore >= 70) return "Repeat practice for selected weak points.";
  if (normalizedScore >= 50) return "Not ready for real patient practice.";
  return "Immediate correction required.";
}

// =========================
// Context
// =========================
class SetupContext {
public:
  DeviceConfig config;
  String statusMessage = "Choose a practice mode to begin.";
  AppState* current = nullptr;
  unsigned long connectStartMs = 0;

  uint16_t currentLightValues[5] = {0, 0, 0, 0, 0};
  bool lightDetected[5] = {false, false, false, false, false};
  uint8_t lightOnCounts[5] = {0, 0, 0, 0, 0};
  uint8_t lightOffCounts[5] = {0, 0, 0, 0, 0};
  unsigned long lastLightSampleMs = 0;

  bool insideDetected = false;
  int insideSensorIndex = 0;

  bool trackingStarted = false;
  unsigned long startTimeMs = 0;
  unsigned long totalTimeMs = 0;

  int currentDepthCm = 0;
  int maxDepthCm = 0;

  bool pressureReady = false;
  bool pressureFolded = false;
  bool readyForSuction = false;
  bool insertPressureError = false;

  int32_t currentPressureRaw = 0;
  int32_t currentPressureDeltaRaw = 0;
  bool currentPressureReadOk = false;
  int32_t preSuctionPressureRaw = 0;
  int32_t foldedPressureReferenceRaw = 0;
  int32_t foldedPressureForScoreRaw = 0;
  int32_t releasePressureDropRaw = 0;
  int releasePressureRatioPercent = 100;
  bool pressureScoreCaptured = false;
  int32_t foldedPressureSamples[PRESSURE_SCORE_BUFFER_SIZE] = {0};
  int foldedPressureSampleCount = 0;
  int foldedPressureNextIndex = 0;

  unsigned long releaseCandidateSinceMs = 0;

  bool suctionStarted = false;
  bool suctionCompleted = false;

  int expectedExitBandCount = 0;
  int exitBandCount = 0;
  bool exitBlackBandSeen = false;
  bool exitReadyToCountBand = false;
  bool exitBandActive = false;
  unsigned long tubeClearSinceMs = 0;

  bool contactBandActive = false;
  uint8_t contactBandOnCount = 0;
  uint8_t contactBandOffCount = 0;
  bool contactEntryMarkerIgnored = false;
  int contactBandCount = 0;
  bool contactDetected = false;
  bool contactSequenceError = false;
  int contactMissCount = 0;
  int contactUnexpectedBandCount = 0;
  int lastContactExpectedDepthCm = -1;
  int lastContactActualDepthCm = 0;
  int lastContactBandSignedDelta = 0;

  unsigned long lastSensorSnapshotMs = 0;
  unsigned long lastSensorSampleIntervalMs = 0;
  unsigned long lastSerialDebugLogMs = 0;
  uint32_t serialDebugSequence = 0;
  uint32_t lastSerialDebugDurationUs = 0;
  bool serialDebugHeaderPrinted = false;

  void markSensorSnapshot(unsigned long now) {
    if (lastSensorSnapshotMs > 0) {
      lastSensorSampleIntervalMs = now - lastSensorSnapshotMs;
    } else {
      lastSensorSampleIntervalMs = 0;
    }
    lastSensorSnapshotMs = now;
  }

  void printSerialDebugHeader() {
    Serial.print("DBG_HEADER baud=115200 intervalMs=");
    Serial.println(SERIAL_DEBUG_INTERVAL_MS);
    Serial.print("DBG_THRESH pressure fold>=");
    Serial.print(PRESSURE_FOLD_MIN_RAW);
    Serial.print(" ready>=");
    Serial.print(PRESSURE_READY_MIN_RAW);
    Serial.print(" direction=");
    Serial.print(PRESSURE_ACTIVE_RAW_DIRECTION);
    Serial.print(" deadbandMin=");
    Serial.print(PRESSURE_ZERO_DEADBAND_MIN_RAW);
    Serial.print(" deadbandMax=");
    Serial.print(PRESSURE_ZERO_DEADBAND_MAX_RAW);
    Serial.print(" releaseDrop>=");
    Serial.print(PRESSURE_RELEASE_DROP_RAW);
    Serial.print(" releaseRatio<=");
    Serial.print(PRESSURE_RELEASE_MAX_RATIO_PERCENT);
    Serial.print(" refUpdateRatio>=");
    Serial.print(PRESSURE_FOLDED_REFERENCE_UPDATE_MIN_RATIO_PERCENT);
    Serial.print(" mmHgDelta70/80/120/130=");
    Serial.print(PRESSURE_CAL_PRE_LOW_DELTA_RAW);
    Serial.print("/");
    Serial.print(PRESSURE_CAL_LOW_DELTA_RAW);
    Serial.print("/");
    Serial.print(PRESSURE_CAL_HIGH_DELTA_RAW);
    Serial.print("/");
    Serial.print(PRESSURE_CAL_POST_HIGH_DELTA_RAW);
    Serial.print(" light0 opaque>=");
    Serial.print(LIGHT_SENSOR0_OPAQUE_DELTA_MIN);
    Serial.print(" transparent<=");
    Serial.print(LIGHT_SENSOR0_TRANSPARENT_DELTA_MAX);
    Serial.print(" clearAbs<=");
    Serial.print(LIGHT_SENSOR0_CLEAR_ABS_DELTA);
    Serial.print(" lightOther on/off=");
    for (int i = 1; i < 5; i++) {
      if (i > 1) Serial.print(",");
      Serial.print("L");
      Serial.print(i);
      Serial.print(":");
      Serial.print(LIGHT_DETECT_ON_THRESHOLDS[i]);
      Serial.print("/");
      Serial.print(LIGHT_DETECT_OFF_THRESHOLDS[i]);
    }
    Serial.println();
    Serial.println("DBG_LIGHT_FORMAT Lx=raw,baseline,signedDelta,absDelta,detected,onCount,offCount");
    serialDebugHeaderPrinted = true;
  }

  void printLightDebugValue(int index) {
    Serial.print(" L");
    Serial.print(index);
    Serial.print("=");
    Serial.print(currentLightValues[index]);
    Serial.print(",");
    Serial.print(config.lightBaselines[index]);
    Serial.print(",");
    Serial.print(lightSignedDelta(currentLightValues[index], config.lightBaselines[index]));
    Serial.print(",");
    Serial.print(lightAbsDelta(currentLightValues[index], config.lightBaselines[index]));
    Serial.print(",");
    Serial.print(lightDetected[index] ? 1 : 0);
    Serial.print(",");
    Serial.print(lightOnCounts[index]);
    Serial.print(",");
    Serial.print(lightOffCounts[index]);
  }

  void printSensorDebugLine(unsigned long now, const char* source) {
    if (!serialDebugHeaderPrinted) {
      printSerialDebugHeader();
    }

    unsigned long logStartUs = micros();
    serialDebugSequence++;
    lastSerialDebugLogMs = now;

    Serial.print("DBG seq=");
    Serial.print(serialDebugSequence);
    Serial.print(" t=");
    Serial.print(now);
    Serial.print(" state=");
    Serial.print(current ? current->name() : "NoState");
    Serial.print(" src=");
    Serial.print(source);
    Serial.print(" sampleDt=");
    Serial.print(lastSensorSampleIntervalMs);
    Serial.print(" logUsPrev=");
    Serial.print(lastSerialDebugDurationUs);
    Serial.print(" pOk=");
    Serial.print(currentPressureReadOk ? 1 : 0);
    Serial.print(" pRaw=");
    Serial.print(currentPressureRaw);
    Serial.print(" pZero=");
    Serial.print(config.pressureZeroRaw);
    Serial.print(" pDeadband=");
    Serial.print(clampPressureDeadbandRaw(config.pressureZeroDeadbandRaw));
    Serial.print(" pDelta=");
    Serial.print(currentPressureDeltaRaw);
    Serial.print(" pFold=");
    Serial.print(pressureFolded ? 1 : 0);
    Serial.print(" pReady=");
    Serial.print(pressureReady ? 1 : 0);
    Serial.print(" pRef=");
    Serial.print(foldedPressureReferenceRaw);
    Serial.print(" pScore=");
    Serial.print(foldedPressureForScoreRaw);
    Serial.print(" relDrop=");
    Serial.print(releasePressureDropRaw);
    Serial.print(" relRatio=");
    Serial.print(releasePressureRatioPercent);
    Serial.print(" depth=");
    Serial.print(currentDepthCm);
    Serial.print(" maxDepth=");
    Serial.print(maxDepthCm);
    Serial.print(" inside=");
    Serial.print(insideDetected ? 1 : 0);
    Serial.print(" insideIdx=");
    Serial.print(insideSensorIndex);
    Serial.print(" tracking=");
    Serial.print(trackingStarted ? 1 : 0);
    Serial.print(" readySuction=");
    Serial.print(readyForSuction ? 1 : 0);
    Serial.print(" suctionStarted=");
    Serial.print(suctionStarted ? 1 : 0);
    Serial.print(" suctionDone=");
    Serial.print(suctionCompleted ? 1 : 0);
    Serial.print(" contact=");
    Serial.print(contactDetected ? 1 : 0);
    Serial.print(" contactErr=");
    Serial.print(contactSequenceError ? 1 : 0);
    Serial.print(" contactBands=");
    Serial.print(contactBandCount);
    Serial.print(" entryIgnored=");
    Serial.print(contactEntryMarkerIgnored ? 1 : 0);

    for (int i = 0; i < 5; i++) {
      printLightDebugValue(i);
    }

    Serial.println();
    Serial.flush();
    lastSerialDebugDurationUs = micros() - logStartUs;
  }

  void logSensorDebugIfDue(unsigned long now, const char* source) {
    if (!config.serialDebugEnabled) return;
    if (lastSerialDebugLogMs > 0 && (now - lastSerialDebugLogMs) < SERIAL_DEBUG_INTERVAL_MS) return;
    printSensorDebugLine(now, source);
  }

  void logSensorDebugNow(unsigned long now, const char* source) {
    if (!config.serialDebugEnabled) return;
    printSensorDebugLine(now, source);
  }

  void sampleLiveSerialDebugSensors() {
    readCurrentLightValues(currentLightValues);

    if (config.lightCalibrated) {
      updateLightDetection();
    }

    PressureReadStats stats;
    currentPressureReadOk = readPressureRawStatsWithTimeout(
      PRESSURE_DEBUG_READ_SAMPLES,
      PRESSURE_INSERT_READ_DELAY_MS,
      stats,
      PRESSURE_DEBUG_READY_TIMEOUT_MS
    );

    if (currentPressureReadOk) {
      currentPressureRaw = stats.averageRaw;

      if (config.pressureCalibrated) {
        currentPressureDeltaRaw = rawToDeltaRaw(
          currentPressureRaw,
          config.pressureZeroRaw,
          config.pressureZeroDeadbandRaw
        );
        pressureFolded = isPressureFoldedRaw(currentPressureDeltaRaw);
        pressureReady = isPressureReadyRaw(currentPressureDeltaRaw);
      } else {
        currentPressureDeltaRaw = 0;
        pressureFolded = false;
        pressureReady = false;
      }
    } else {
      currentPressureRaw = 0;
      currentPressureDeltaRaw = 0;
      pressureFolded = false;
      pressureReady = false;
    }
  }

  void logLiveSerialDebugNow(unsigned long now, const char* source) {
    if (!config.serialDebugEnabled) return;
    sampleLiveSerialDebugSensors();
    markSensorSnapshot(now);
    printSensorDebugLine(now, source);
  }

  void logLiveSerialDebugIfDue(unsigned long now, const char* source) {
    if (!config.serialDebugEnabled) return;
    if (current && current->ownsSerialSensorSampling()) return;
    if (lastSerialDebugLogMs > 0 && (now - lastSerialDebugLogMs) < SERIAL_DEBUG_INTERVAL_MS) return;
    logLiveSerialDebugNow(now, source);
  }

  void setSerialDebugEnabled(bool enabled, const char* source = "web") {
    bool changed = (config.serialDebugEnabled != enabled);

    config.serialDebugEnabled = enabled;
    if (changed) {
      serialDebugHeaderPrinted = false;
      lastSerialDebugLogMs = 0;
      lastSerialDebugDurationUs = 0;
    }
    saveConfig();

    Serial.print("DBG_CONTROL t=");
    Serial.print(millis());
    Serial.print(" src=");
    Serial.print(source);
    Serial.print(" enabled=");
    Serial.print(enabled ? 1 : 0);
    Serial.print(" changed=");
    Serial.print(changed ? 1 : 0);
    Serial.print(" state=");
    Serial.println(current ? current->name() : "NoState");
    Serial.flush();

    if (enabled) {
      logLiveSerialDebugNow(millis(), changed ? "debug-on" : "debug-apply");
    }
  }

  void resetFoldedPressureTracking() {
    preSuctionPressureRaw = 0;
    foldedPressureReferenceRaw = 0;
    foldedPressureForScoreRaw = 0;
    releasePressureDropRaw = 0;
    releasePressureRatioPercent = 100;
    pressureScoreCaptured = false;
    foldedPressureSampleCount = 0;
    foldedPressureNextIndex = 0;

    for (int i = 0; i < PRESSURE_SCORE_BUFFER_SIZE; i++) {
      foldedPressureSamples[i] = 0;
    }
  }

  int32_t foldedPressureAverageRaw() const {
    if (foldedPressureSampleCount <= 0) return 0;

    int64_t sum = 0;
    int32_t minValue = foldedPressureSamples[0];
    int32_t maxValue = foldedPressureSamples[0];

    for (int i = 0; i < foldedPressureSampleCount; i++) {
      int32_t value = foldedPressureSamples[i];
      sum += value;
      if (value < minValue) minValue = value;
      if (value > maxValue) maxValue = value;
    }

    if (foldedPressureSampleCount >= 5) {
      sum -= minValue;
      sum -= maxValue;
      return (int32_t)(sum / (foldedPressureSampleCount - 2));
    }

    return (int32_t)(sum / foldedPressureSampleCount);
  }

  void addFoldedPressureSample(int32_t deltaRaw) {
    foldedPressureSamples[foldedPressureNextIndex] = deltaRaw;
    foldedPressureNextIndex = (foldedPressureNextIndex + 1) % PRESSURE_SCORE_BUFFER_SIZE;

    if (foldedPressureSampleCount < PRESSURE_SCORE_BUFFER_SIZE) {
      foldedPressureSampleCount++;
    }

    foldedPressureReferenceRaw = foldedPressureAverageRaw();
    preSuctionPressureRaw = foldedPressureReferenceRaw;
  }

  void captureFoldedPressureForScore() {
    if (pressureScoreCaptured) return;

    foldedPressureForScoreRaw = foldedPressureReferenceRaw;
    preSuctionPressureRaw = foldedPressureForScoreRaw;
    pressureScoreCaptured = true;
  }

  void resetContactTracking() {
    contactBandActive = false;
    contactBandOnCount = 0;
    contactBandOffCount = 0;
    contactEntryMarkerIgnored = false;
    contactBandCount = 0;
    contactDetected = false;
    contactSequenceError = false;
    contactMissCount = 0;
    contactUnexpectedBandCount = 0;
    lastContactExpectedDepthCm = -1;
    lastContactActualDepthCm = 0;
    lastContactBandSignedDelta = 0;
  }

  void beginContactTrackingAtEntryMarker() {
    int signedDelta = lightSignedDelta(currentLightValues[0], config.lightBaselines[0]);

    contactEntryMarkerIgnored = true;
    contactBandActive = true;
    contactBandOnCount = 0;
    contactBandOffCount = 0;
    lastContactExpectedDepthCm = 0;
    lastContactActualDepthCm = currentDepthCm;
    lastContactBandSignedDelta = signedDelta;
  }

  int expectedContactDepthForBand(int bandNumber) const {
    if (bandNumber < 1 || bandNumber > CONTACT_MARKER_COUNT) return -1;
    return CONTACT_MARKER_DEPTH_CM[bandNumber - 1];
  }

  bool contactDepthMatches(int expectedDepthCm) const {
    if (expectedDepthCm < 0) return false;
    if (expectedDepthCm == 0) return currentDepthCm == 0;
    return currentDepthCm >= expectedDepthCm;
  }

  void handleContactBandEvent(int signedDelta) {
    lastContactActualDepthCm = currentDepthCm;
    lastContactBandSignedDelta = signedDelta;

    contactBandCount++;
    lastContactExpectedDepthCm = expectedContactDepthForBand(contactBandCount);

    if (lastContactExpectedDepthCm < 0) {
      contactSequenceError = true;
      contactUnexpectedBandCount++;
      return;
    }

    if (!contactDepthMatches(lastContactExpectedDepthCm)) {
      contactDetected = true;
      contactMissCount++;
    }
  }

  void updateContactBandDetection() {
    int signedDelta = lightSignedDelta(currentLightValues[0], config.lightBaselines[0]);

    if (!contactBandActive) {
      if (signedDelta >= CONTACT_BAND_ON_SIGNED_DELTA) {
        if (contactBandOnCount < CONTACT_BAND_DEBOUNCE_COUNT) contactBandOnCount++;
      } else {
        contactBandOnCount = 0;
      }

      if (contactBandOnCount >= CONTACT_BAND_DEBOUNCE_COUNT) {
        contactBandActive = true;
        contactBandOnCount = 0;
        contactBandOffCount = 0;
        handleContactBandEvent(signedDelta);
      }

      return;
    }

    if (signedDelta <= CONTACT_BAND_OFF_SIGNED_DELTA) {
      if (contactBandOffCount < CONTACT_BAND_DEBOUNCE_COUNT) contactBandOffCount++;
    } else {
      contactBandOffCount = 0;
    }

    if (contactBandOffCount >= CONTACT_BAND_DEBOUNCE_COUNT) {
      contactBandActive = false;
      contactBandOffCount = 0;
      contactBandOnCount = 0;
    }
  }

  bool isLightDetected(int index) const {
    if (index < 0 || index >= 5) return false;
    return lightDetected[index];
  }

  void updateLightDetection() {
    bool anyDetected = false;
    int deepestIndex = 0;
    int deepestDepth = 0;

    for (int i = 0; i < 5; i++) {
      bool detectCandidate = isLightDetectCandidate(i, currentLightValues[i], config.lightBaselines[i]);
      bool clearCandidate = isLightClearCandidate(i, currentLightValues[i], config.lightBaselines[i]);

      if (!lightDetected[i]) {
        if (detectCandidate) {
          if (lightOnCounts[i] < LIGHT_DEBOUNCE_COUNT) lightOnCounts[i]++;
        } else {
          lightOnCounts[i] = 0;
        }

        if (lightOnCounts[i] >= LIGHT_DEBOUNCE_COUNT) {
          lightDetected[i] = true;
          lightOffCounts[i] = 0;
        }
      } else {
        if (clearCandidate) {
          if (lightOffCounts[i] < LIGHT_DEBOUNCE_COUNT) lightOffCounts[i]++;
        } else {
          lightOffCounts[i] = 0;
        }

        if (lightOffCounts[i] >= LIGHT_DEBOUNCE_COUNT) {
          lightDetected[i] = false;
          lightOnCounts[i] = 0;
        }
      }

      if (lightDetected[i]) {
        anyDetected = true;

        if (SENSOR_DEPTH_CM[i] > deepestDepth) {
          deepestDepth = SENSOR_DEPTH_CM[i];
          deepestIndex = i;
        }
      }
    }

    insideDetected = anyDetected;
    insideSensorIndex = deepestIndex;
    currentDepthCm = deepestDepth;

    if (currentDepthCm > maxDepthCm) {
      maxDepthCm = currentDepthCm;
    }
  }

  void transitionTo(AppState* next) {
    current = next;
    appLogLine(String("Transition -> ") + current->name());
    current->enter(*this);
  }

  void update() {
    if (current) current->update(*this);
    logLiveSerialDebugIfDue(millis(), "live");
  }

  String renderPage() {
    if (!current) return pageStart("Error") + String("<h2>No state</h2>") + pageEnd();
    return current->renderPage(*this);
  }

  void loadConfig() {
    prefs.begin("device_cfg", true);
    config.configured = prefs.getBool("configured", false);
    config.mode = (AppMode)prefs.getUChar("mode", MODE_UNSET);
    config.ssid = prefs.getString("ssid", "");
    config.password = prefs.getString("pass", "");
    for (int i = 0; i < 5; i++) {
      config.lightBaselines[i] = 0;
    }
    prefs.getBytes("light_arr", config.lightBaselines, sizeof(config.lightBaselines));
    config.lightCalibrated = prefs.getBool("light_done", false);
    config.calibrateStep = (CalibrateStep)prefs.getUChar("cal_step", CAL_STEP_LIGHT);
    config.pressureCalibrated = prefs.getBool("press_done", false);
    config.pressureZeroRaw = prefs.getLong("press_zero", 0);
    config.pressureZeroDeadbandRaw = clampPressureDeadbandRaw(
      prefs.getLong("press_db", PRESSURE_ZERO_DEADBAND_MIN_RAW)
    );
    config.serialDebugEnabled = false;
    prefs.end();
  }

  void saveConfig() {
    prefs.begin("device_cfg", false);
    prefs.putBool("configured", config.configured);
    prefs.putUChar("mode", (uint8_t)config.mode);
    prefs.putString("ssid", config.ssid);
    prefs.putString("pass", config.password);
    prefs.putUChar("cal_step", (uint8_t)config.calibrateStep);
    prefs.putBool("light_done", config.lightCalibrated);
    prefs.putBytes("light_arr", config.lightBaselines, sizeof(config.lightBaselines));
    prefs.putBool("press_done", config.pressureCalibrated);
    prefs.putLong("press_zero", config.pressureZeroRaw);
    prefs.putLong("press_db", clampPressureDeadbandRaw(config.pressureZeroDeadbandRaw));
    prefs.putBool("serial_dbg", false);
    prefs.end();
  }

  void clearConfig() {
    prefs.begin("device_cfg", false);
    prefs.clear();
    prefs.end();

    config.configured = false;
    config.mode = MODE_UNSET;
    config.ssid = "";
    config.password = "";
    config.calibrateStep = CAL_STEP_LIGHT;
    config.lightCalibrated = false;
    for (int i = 0; i < 5; i++) {
      config.lightBaselines[i] = 0;
    }
    config.pressureCalibrated = false;
    config.pressureZeroRaw = 0;
    config.pressureZeroDeadbandRaw = PRESSURE_ZERO_DEADBAND_MIN_RAW;
    config.serialDebugEnabled = false;
    serialDebugHeaderPrinted = false;
    lastSerialDebugLogMs = 0;
  }

  void boot() {
    loadConfig();

    if (config.mode == MODE_OFFLINE) {
      if (!config.configured){
        statusMessage = "Continue offline calibration.";
        transitionTo(&calibrateState());
        return;       
      }
      statusMessage = "Offline mode is ready.";
      transitionTo(&readyState());
      return;
    }

    if (config.configured && config.mode == MODE_ONLINE && config.ssid.length() > 0) {
      statusMessage = "Connecting to the saved Wi-Fi network...";
      transitionTo(&wifiConnectingState());
      return;
    }

    statusMessage = "Choose a practice mode to begin.";
    transitionTo(&modeSelectState());
  }
};

SetupContext app;

// =========================
// Concrete States
// =========================

// -------------------------
// SetupFlowState
// -------------------------

class ModeSelectState : public SetupFlowState {
public:
  const char* name() const override {
    return "ModeSelectState";
  }

  void enter(SetupContext& ctx) override {
    ctx.statusMessage = "Choose a practice mode to begin.";
  }

  void onModeSelected(SetupContext& ctx, const String& mode) override {
    if (mode == "offline") {
      ctx.config.mode = MODE_OFFLINE;
      ctx.config.ssid = "";
      ctx.config.password = "";

      ctx.config.configured = false;
      ctx.config.calibrateStep = CAL_STEP_LIGHT;
      ctx.config.lightCalibrated = false;
      for (int i = 0; i < 5; i++) {
        ctx.config.lightBaselines[i] = 0;
      }
      ctx.config.pressureCalibrated = false;
      ctx.config.pressureZeroRaw = 0;
      ctx.config.pressureZeroDeadbandRaw = PRESSURE_ZERO_DEADBAND_MIN_RAW;
      ctx.saveConfig();

      WiFi.disconnect(false, true);
      ctx.statusMessage = "Offline mode selected. Continue to calibration.";
      ctx.transitionTo(&calibrateState());
      return;
    }

    if (mode == "online") {
      ctx.config.mode = MODE_ONLINE;
      ctx.config.configured = false;
      ctx.statusMessage = "Select a Wi-Fi network and enter the password.";
      ctx.transitionTo(&wifiConfigState());
      return;
    }

    ctx.statusMessage = "Please choose either offline practice or online mode.";
  }

  void onReset(SetupContext& ctx) override {
    ctx.clearConfig();
    WiFi.disconnect(false, true);
    ctx.statusMessage = "Setup has been reset.";
    ctx.transitionTo(&modeSelectState());
  }

  String renderPage(SetupContext& ctx) override {
    String p = pageStart("Select Mode");
    p += "<h2>Suctioning Trainer</h2>";
    p += "<p class='lead'>Choose how this training device should run. Use offline practice when you only need the local trainer, or online mode when Wi-Fi reporting is needed.</p>";

    p += statusHtml(ctx.statusMessage);

    p += "<form method='POST' action='/select-mode'>";
    p += "<div class='row mode-grid'>";
    p += "<label class='mode-card'><input type='radio' name='mode' value='offline'";
    if (ctx.config.mode == MODE_OFFLINE) p += " checked";
    p += ">Offline practice<span>Start calibration and practice on this device.</span></label>";
    p += "<label class='mode-card'><input type='radio' name='mode' value='online'";
    if (ctx.config.mode == MODE_ONLINE) p += " checked";
    p += ">Online mode<span>Connect the trainer to a Wi-Fi network first.</span></label>";
    p += "</div>";

    p += "<div class='row actions'>";
    p += "<button class='primary' type='submit'>Continue</button>";
    p += actionLinkHtml("/reset", "Reset setup");
    p += "</div>";
    p += "</form>";

    p += sensorRawControlHtml();

    p += "<details><summary>Connection details</summary>";
    p += "<div class='diagnostic-row'>Connect to AP: <b>";
    p += htmlEscape(AP_SSID);
    p += "</b> | Password: <b>";
    p += htmlEscape(AP_PASSWORD);
    p += "</b> | Open: <b>192.168.4.1</b></div>";
    p += "</details>";

    p += pageEnd();
    return p;
  }
};

class WifiConfigState : public SetupFlowState {
public:
  const char* name() const override {
    return "WifiConfigState";
  }

  void enter(SetupContext& ctx) override {
    ctx.statusMessage = "Select a Wi-Fi network and enter the password.";
  }

  void onConnectWifi(SetupContext& ctx, const String& ssid, const String& password) override {
    if (ssid.length() == 0) {
      ctx.statusMessage = "Please select a Wi-Fi network.";
      return;
    }

    ctx.config.mode = MODE_ONLINE;
    ctx.config.ssid = ssid;
    ctx.config.password = password;
    ctx.config.configured = false;

    ctx.transitionTo(&wifiConnectingState());
  }

  void onBack(SetupContext& ctx) override {
    ctx.statusMessage = "Returned to mode selection.";
    ctx.transitionTo(&modeSelectState());
  }

  void onReset(SetupContext& ctx) override {
    ctx.clearConfig();
    WiFi.disconnect(false, true);
    ctx.statusMessage = "Setup has been reset.";
    ctx.transitionTo(&modeSelectState());
  }

  String renderPage(SetupContext& ctx) override {
    String p = pageStart("Connect Wi-Fi");
    p += "<h2>Connect Wi-Fi</h2>";
    p += "<p class='lead'>Select the Wi-Fi network for online mode. Keep your phone or computer connected to the ESP32 setup network until this step finishes.</p>";

    String wifiTone = (ctx.statusMessage.indexOf("failed") >= 0) ? "err" : "";
    p += statusHtml(ctx.statusMessage, wifiTone);

    p += "<form method='POST' action='/connect-wifi'>";
    p += "<div class='row'>";
    p += "<label>Wi-Fi network</label>";
    p += "<select name='ssid'>";
    p += wifiOptionsHtml(ctx.config.ssid);
    p += "</select>";
    p += "</div>";

    p += "<div class='row'>";
    p += "<label>Wi-Fi password</label>";
    p += "<input type='password' name='password' value='";
    p += htmlEscape(ctx.config.password);
    p += "' placeholder='Enter Wi-Fi password'>";
    p += "</div>";

    p += "<div class='row actions'>";
    p += "<button class='primary' type='submit'>Connect</button>";
    p += actionLinkHtml("/", "Rescan");
    p += actionLinkHtml("/back", "Back");
    p += actionLinkHtml("/reset", "Reset setup");
    p += "</div>";
    p += "</form>";

    p += pageEnd();
    return p;
  }
};

class WifiConnectingState : public SetupFlowState {
public:
  const char* name() const override {
    return "WifiConnectingState";
  }

  void enter(SetupContext& ctx) override {
    if (ctx.config.ssid.length() == 0) {
      ctx.statusMessage = "Wi-Fi network is empty.";
      ctx.transitionTo(&wifiConfigState());
      return;
    }

    ctx.statusMessage = "Connecting to Wi-Fi: " + ctx.config.ssid;
    ctx.connectStartMs = millis();

    WiFi.disconnect(false, true);
    delay(200);
    WiFi.begin(ctx.config.ssid.c_str(), ctx.config.password.c_str());

    appLogLine(String("Connecting to: ") + ctx.config.ssid);
  }

  void update(SetupContext& ctx) override {
    wl_status_t s = WiFi.status();

    if (s == WL_CONNECTED) {
      ctx.config.configured = true;
      ctx.saveConfig();
      ctx.statusMessage = "Wi-Fi connected. The trainer is ready.";
      ctx.transitionTo(&readyState());
      return;
    }

    if (millis() - ctx.connectStartMs >= WIFI_CONNECT_TIMEOUT_MS) {
      WiFi.disconnect(false, true);
      ctx.statusMessage = "Wi-Fi connection failed. Check the network and password.";
      ctx.transitionTo(&wifiConfigState());
      return;
    }
  }

  void onBack(SetupContext& ctx) override {
    WiFi.disconnect(false, true);
    ctx.statusMessage = "Connection cancelled.";
    ctx.transitionTo(&wifiConfigState());
  }

  void onReset(SetupContext& ctx) override {
    WiFi.disconnect(false, true);
    ctx.clearConfig();
    ctx.statusMessage = "Setup has been reset.";
    ctx.transitionTo(&modeSelectState());
  }

  String renderPage(SetupContext& ctx) override {
    String p = pageStart("Connecting", true);
    p += "<h2>Connecting...</h2>";
    p += "<p class='lead'>The trainer is trying to join the selected Wi-Fi network. This page refreshes every 2 seconds.</p>";

    p += statusHtml(ctx.statusMessage, "warn");

    p += "<div class='metric-grid'>";
    p += metricHtml("Network", ctx.config.ssid);
    p += metricHtml("Timeout", String(WIFI_CONNECT_TIMEOUT_MS / 1000) + " s");
    p += "</div>";

    p += "<div class='row actions'>";
    p += actionLinkHtml("/back", "Cancel");
    p += actionLinkHtml("/reset", "Reset setup");
    p += "</div>";

    p += pageEnd();
    return p;
  }
};

class CalibrateState : public SetupFlowState {
public:
  const char* name() const override {
    return "CalibrateState";
  }

  void enter(SetupContext& ctx) override {
    if (!ctx.config.lightCalibrated) {
      ctx.config.calibrateStep = CAL_STEP_LIGHT;
      ctx.statusMessage = "Calibrating light sensors for 10 seconds.";
    } else if (!ctx.config.pressureCalibrated) {
      ctx.config.calibrateStep = CAL_STEP_PRESSURE;
      ctx.statusMessage = "Calibrating pressure baseline for 10 seconds.";
    } else {
      ctx.config.calibrateStep = CAL_STEP_DONE;
      ctx.config.configured = true;
      ctx.saveConfig();
      ctx.statusMessage = "Calibration complete. Ready to practice.";
      ctx.transitionTo(&readyState());
    }
  }

  void onBack(SetupContext& ctx) override {
    ctx.statusMessage = "Returned to mode selection.";
    ctx.transitionTo(&modeSelectState());
  }

  void onReset(SetupContext& ctx) override {
    ctx.clearConfig();
    WiFi.disconnect(false, true);
    ctx.statusMessage = "Setup has been reset.";
    ctx.transitionTo(&modeSelectState());
  }

  void handleCalibrateButton(SetupContext& ctx, const String& action) {
    if (action == "light" && ctx.config.calibrateStep == CAL_STEP_LIGHT) {
      appLogLine("Starting 10 s light calibration.");
      LightReadStats stats;
      if (!readLightStats(LIGHT_CALIBRATION_SAMPLES, LIGHT_CALIBRATION_DELAY_MS, stats)) {
        ctx.statusMessage = "Light sensor calibration failed. Check wiring and try again.";
        return;
      }

      for (int i = 0; i < 5; i++) {
        ctx.config.lightBaselines[i] = stats.average[i];
      }

      ctx.config.lightCalibrated = true;
      ctx.config.calibrateStep = CAL_STEP_PRESSURE;
      ctx.saveConfig();

      String ranges = "";
      for (int i = 0; i < 5; i++) {
        if (i > 0) ranges += ", ";
        ranges += "L";
        ranges += String(i);
        ranges += "=";
        ranges += String(stats.range[i]);
      }
      ctx.statusMessage = String("Light sensors calibrated over 10 s. Range raw: ")
        + ranges
        + ". Continue to pressure calibration.";
      appLogLine(ctx.statusMessage);
      return;
    }

    if (action == "pressure" && ctx.config.calibrateStep == CAL_STEP_PRESSURE) {
      appLogLine("Starting 10 s pressure calibration.");
      PressureReadStats stats;

      if (!readPressureRawStats(PRESSURE_CALIBRATION_SAMPLES, PRESSURE_CALIBRATION_DELAY_MS, stats)) {
        ctx.statusMessage = "Pressure sensor read failed. Check the sensor and try again.";
        return;
      }

      if (!isPressureStable(stats, PRESSURE_CAL_STABLE_MAX_TRIMMED_RANGE_RAW)) {
        ctx.statusMessage = String("Pressure unstable. Trimmed range = ")
          + String(stats.trimmedRangeRaw)
          + " raw, limit = "
          + String(PRESSURE_CAL_STABLE_MAX_TRIMMED_RANGE_RAW)
          + ". Check wiring/tube and retry.";
        return;
      }

      ctx.config.pressureZeroRaw = stats.averageRaw;
      ctx.config.pressureZeroDeadbandRaw = pressureDeadbandFromStats(stats);
      ctx.config.pressureCalibrated = true;
      ctx.config.calibrateStep = CAL_STEP_DONE;
      ctx.config.configured = true;
      ctx.saveConfig();

      ctx.statusMessage = String("Pressure calibration complete. Raw zero = ")
        + String(stats.averageRaw)
        + ", min/max = "
        + String(stats.minRaw)
        + "/"
        + String(stats.maxRaw)
        + ", trimmed range = "
        + String(stats.trimmedRangeRaw)
        + ", deadband = "
        + String(ctx.config.pressureZeroDeadbandRaw);
      appLogLine(ctx.statusMessage);
      ctx.transitionTo(&readyState());
      return;
    }

    ctx.statusMessage = "Invalid calibration action.";
  }

  String renderPage(SetupContext& ctx) override {
    String p = pageStart("Calibration");
    p += "<h2>Calibration</h2>";
    p += "<p class='lead'>Calibrate each sensor baseline for 10 seconds so the trainer can detect stable patterns.</p>";

    String calibrationTone = "warn";
    if (ctx.statusMessage.indexOf("failed") >= 0 ||
        ctx.statusMessage.indexOf("unstable") >= 0 ||
        ctx.statusMessage.indexOf("Invalid") >= 0) {
      calibrationTone = "err";
    } else if (ctx.config.calibrateStep == CAL_STEP_DONE ||
               ctx.statusMessage.indexOf("complete") >= 0 ||
               ctx.statusMessage.indexOf("calibrated") >= 0) {
      calibrationTone = "ok";
    }
    p += statusHtml(ctx.statusMessage, calibrationTone);

    p += "<div class='steps'>";
    p += stepHtml(1, "Light sensors", "Keep the tube out of the trainer, then calibrate the light baseline for 10 seconds.", ctx.config.lightCalibrated ? "done" : "active");
    p += stepHtml(2, "Pressure baseline", "Turn the suction machine off and leave the tube released, then calibrate pressure for 10 seconds.", ctx.config.pressureCalibrated ? "done" : ((ctx.config.calibrateStep == CAL_STEP_PRESSURE) ? "active" : ""));
    p += "</div>";

    if (ctx.config.calibrateStep == CAL_STEP_LIGHT) {
      p += "<form method='POST' action='/calibrate' data-calibrate='1'>";
      p += "<input type='hidden' name='action' value='light'>";
      p += "<button class='primary' type='submit'>Calibrate Light (10 s)</button>";
      p += "</form>";
    } else if (ctx.config.calibrateStep == CAL_STEP_PRESSURE) {
      p += "<form method='POST' action='/calibrate' data-calibrate='1'>";
      p += "<input type='hidden' name='action' value='pressure'>";
      p += "<button class='primary' type='submit'>Calibrate Pressure (10 s)</button>";
      p += "</form>";
    }

    p += "<div class='row actions spaced'>";
    p += actionLinkHtml("/back", "Back");
    p += actionLinkHtml("/reset", "Reset setup");
    p += "</div>";

    p += calibrationWaitAlertScriptHtml();
    p += pageEnd();
    return p;
  }
};

// -------------------------
// AppState
// -------------------------

class ReadyState : public AppState {
public:
  const char* name() const override {
    return "ReadyState";
  }

  void onStartInsert(SetupContext& ctx) override {
    LightReadStats lightStats;
    if (!readLightStats(LIGHT_READY_CHECK_SAMPLES, LIGHT_READY_CHECK_DELAY_MS, lightStats)) {
      ctx.statusMessage = "Light sensor read failed before practice. Check wiring and retry.";
      return;
    }

    for (int i = 0; i < 5; i++) {
      if (lightStats.range[i] > LIGHT_READY_STABLE_MAX_RANGE[i]) {
        ctx.statusMessage = String("Light sensor ")
          + String(i)
          + " is unstable before practice. Range = "
          + String(lightStats.range[i])
          + ", limit = "
          + String(LIGHT_READY_STABLE_MAX_RANGE[i])
          + ". Keep the trainer still and retry.";
        return;
      }

      int clearDelta = lightAbsDelta(lightStats.average[i], ctx.config.lightBaselines[i]);
      if (clearDelta > LIGHT_READY_CLEAR_ABS_DELTA[i]) {
        ctx.statusMessage = String("Light sensor ")
          + String(i)
          + " is not clear before practice. Delta = "
          + String(clearDelta)
          + ", limit = "
          + String(LIGHT_READY_CLEAR_ABS_DELTA[i])
          + ". Remove the tube or obstruction and retry.";
        return;
      }
    }

    for (int i = 0; i < 5; i++) {
      ctx.currentLightValues[i] = lightStats.average[i];
      ctx.lightDetected[i] = false;
      ctx.lightOnCounts[i] = 0;
      ctx.lightOffCounts[i] = 0;
    }
    ctx.insideDetected = false;
    ctx.insideSensorIndex = 0;
    ctx.currentDepthCm = 0;

    PressureReadStats stats;

    if (!readPressureRawStats(PRESSURE_READY_CHECK_SAMPLES, PRESSURE_READY_CHECK_DELAY_MS, stats)) {
      ctx.pressureReady = false;
      ctx.pressureFolded = false;
      ctx.currentPressureReadOk = false;
      ctx.statusMessage = "Pressure sensor read failed. Check wiring before practice.";
      unsigned long debugNow = millis();
      ctx.markSensorSnapshot(debugNow);
      ctx.logSensorDebugNow(debugNow, "ready-pressure-fail");
      return;
    }

    trackPressureZeroIfResting(ctx.config, stats.averageRaw);

    int32_t pressureDeadbandRaw = clampPressureDeadbandRaw(ctx.config.pressureZeroDeadbandRaw);
    int32_t restingDeltaRaw = rawToDeltaRaw(
      stats.averageRaw,
      ctx.config.pressureZeroRaw,
      pressureDeadbandRaw
    );
    int32_t restingSignedDeltaRaw = stats.averageRaw - ctx.config.pressureZeroRaw;
    int32_t restingAbsDeltaRaw = abs(restingSignedDeltaRaw);
    ctx.currentPressureRaw = stats.averageRaw;
    ctx.currentPressureDeltaRaw = restingDeltaRaw;
    ctx.currentPressureReadOk = true;
    ctx.pressureFolded = isPressureFoldedRaw(restingDeltaRaw);
    ctx.pressureReady = isPressureReadyRaw(restingDeltaRaw);

    unsigned long debugNow = millis();

    if (!isPressureStable(stats, PRESSURE_READY_STABLE_MAX_TRIMMED_RANGE_RAW)) {
      ctx.pressureReady = false;
      ctx.pressureFolded = false;
      ctx.statusMessage = String("Pressure unstable before insert. Trimmed range = ")
        + String(stats.trimmedRangeRaw)
        + " raw, limit = "
        + String(PRESSURE_READY_STABLE_MAX_TRIMMED_RANGE_RAW)
        + ". Check wiring/tube and retry.";
      ctx.markSensorSnapshot(debugNow);
      ctx.logSensorDebugNow(debugNow, "ready-pressure-unstable");
      return;
    }

    int32_t maxRestingDriftRaw = PRESSURE_READY_MAX_ZERO_DRIFT_RAW;
    if (pressureDeadbandRaw > maxRestingDriftRaw) {
      maxRestingDriftRaw = pressureDeadbandRaw;
    }

    bool openSuctionBeforeInsert =
      restingSignedDeltaRaw < 0 &&
      restingDeltaRaw > 0 &&
      restingDeltaRaw < PRESSURE_FOLD_MIN_RAW;

    if (openSuctionBeforeInsert) {
      int32_t openSuctionLimitRaw =
        PRESSURE_REFERENCE_REST_DELTA_RAW +
        pressureDeadbandRaw +
        PRESSURE_READY_OPEN_SUCTION_BUFFER_RAW;
      if (openSuctionLimitRaw > maxRestingDriftRaw) {
        maxRestingDriftRaw = openSuctionLimitRaw;
      }
    }

    if (restingAbsDeltaRaw > maxRestingDriftRaw) {
      ctx.pressureReady = false;
      ctx.pressureFolded = false;
      ctx.statusMessage = String("Pressure baseline drift before insert. Current-zero delta = ")
        + String(restingSignedDeltaRaw)
        + " raw, abs limit = "
        + String(maxRestingDriftRaw)
        + ". Recalibrate or check tube/sensor.";
      ctx.markSensorSnapshot(debugNow);
      ctx.logSensorDebugNow(debugNow, "ready-pressure-drift");
      return;
    }

    ctx.statusMessage = "Pressure baseline is stable. Start the insert step.";
    ctx.markSensorSnapshot(debugNow);
    ctx.logSensorDebugNow(debugNow, "ready-precheck-ok");
    ctx.transitionTo(&insertState());
  }

  void onReset(SetupContext& ctx) override {
    WiFi.disconnect(false, true);
    ctx.clearConfig();
    ctx.statusMessage = "Setup has been reset.";
    ctx.transitionTo(&modeSelectState());
  }

  String renderPage(SetupContext& ctx) override {
    String p = pageStart("Ready");
    p += "<h2>Ready to Practice</h2>";
    p += "<p class='lead'>The trainer is configured. Start a new practice session when the tube and sensors are in their resting position.</p>";

    String readyTone = "ok";
    if (ctx.statusMessage.indexOf("failed") >= 0 ||
        ctx.statusMessage.indexOf("unstable") >= 0 ||
        ctx.statusMessage.indexOf("drift") >= 0) {
      readyTone = "err";
    }
    p += statusHtml(ctx.statusMessage, readyTone);

    p += "<div class='metric-grid'>";
    p += metricHtml("Mode", modeLabel(ctx.config.mode));
    p += metricHtml("Sensor raw", "Web");

    if (ctx.config.mode == MODE_OFFLINE) {
      p += metricHtml("Network", "Not required");
    }

    if (ctx.config.mode == MODE_ONLINE) {
      if (WiFi.status() == WL_CONNECTED) {
        p += metricHtml("Local IP", WiFi.localIP().toString());
      } else {
        p += metricHtml("Wi-Fi", "Not connected");
      }
    }
    p += "</div>";

    p += "<div class='row actions'>";
    p += actionPostHtml("/start-insert", "Start Practice");
    p += actionLinkHtml("/reset", "Reconfigure");
    p += "</div>";

    p += sensorRawControlHtml();

    p += pageEnd();
    return p;
  }
};

// -------------------------
// WorkingFlowStates
// -------------------------

class InsertState : public WorkingFlowState {
public:
  const char* name() const override {
    return "InsertState";
  }

  bool ownsSerialSensorSampling() const override {
    return true;
  }

  void enter(SetupContext& ctx) override {
    ctx.statusMessage = "Fold the tube before inserting.";
    ctx.lastLightSampleMs = 0;
    ctx.lastSensorSnapshotMs = 0;
    ctx.lastSensorSampleIntervalMs = 0;
    ctx.insideDetected = false;

    ctx.insideSensorIndex = 0;

    ctx.trackingStarted = false;
    ctx.startTimeMs = 0;
    ctx.totalTimeMs = 0;

    ctx.currentDepthCm = 0;
    ctx.maxDepthCm = 0;

    ctx.pressureReady = false;
    ctx.pressureFolded = false;
    ctx.readyForSuction = false;
    ctx.insertPressureError = false;

    ctx.currentPressureRaw = 0;
    ctx.currentPressureDeltaRaw = 0;
    ctx.currentPressureReadOk = false;
    ctx.resetFoldedPressureTracking();
    ctx.releaseCandidateSinceMs = 0;

    ctx.suctionStarted = false;
    ctx.suctionCompleted = false;
    ctx.resetContactTracking();

    for (int i = 0; i < 5; i++) {
      ctx.currentLightValues[i] = 0;
      ctx.lightDetected[i] = false;
      ctx.lightOnCounts[i] = 0;
      ctx.lightOffCounts[i] = 0;
    }
  }

  void onBack(SetupContext& ctx) override {
    ctx.statusMessage = "Returned to ready screen.";
    ctx.transitionTo(&readyState());
  }

  void onStartInsert(SetupContext& ctx) override {
    ctx.statusMessage = "Restarting the insert step.";
    ctx.transitionTo(&insertState());
  }

  void onReset(SetupContext& ctx) override {
    WiFi.disconnect(false, true);
    ctx.clearConfig();
    ctx.statusMessage = "Setup has been reset.";
    ctx.transitionTo(&modeSelectState());
  }
  
  String renderPage(SetupContext& ctx) override {
    int idx = ctx.insideSensorIndex;
    int insideSignedDelta = lightSignedDelta(ctx.currentLightValues[idx], ctx.config.lightBaselines[idx]);
    int insideAbsDelta = lightAbsDelta(ctx.currentLightValues[idx], ctx.config.lightBaselines[idx]);
    String pressureLabel = ctx.pressureReady ? "Target" : (ctx.pressureFolded ? "Folded low" : "Not folded");
    String statusTone = ctx.insertPressureError ? "err" : ((ctx.pressureFolded || ctx.trackingStarted) ? "ok" : "warn");

    String p = pageStart("Insert");
    p += "<h2>Practice: Insert</h2>";
    p += "<p class='lead'>Follow the current prompt while the trainer reads the sensors.</p>";

    p += statusHtmlWithId(ctx.statusMessage, statusTone, "live-status");

    p += "<div class='steps'>";
    p += stepHtml(1, "Fold the tube", "Create folded pressure before inserting. Low pressure can continue but may lose score.", (ctx.pressureFolded || ctx.trackingStarted) ? "done" : "active");
    p += stepHtml(2, "Insert into the neck", "Insert after the tube is folded.", ctx.trackingStarted ? "done" : (ctx.pressureFolded ? "active" : ""));
    p += stepHtml(3, "Release at target depth", "Release the fold after the tube reaches the trainer.", ctx.readyForSuction ? "done" : (ctx.trackingStarted ? "active" : ""));
    p += "</div>";

    p += "<div class='metric-grid'>";
    p += metricHtmlWithId("Pressure", pressureLabel, "live-pressure");
    p += metricHtmlWithId("Tube", ctx.insideDetected ? "Detected" : "Not detected", "live-tube");
    p += metricHtmlWithId("Time", String(ctx.totalTimeMs / 1000.0f, 2) + " s", "live-time");
    p += metricHtmlWithId("Max depth", String(ctx.maxDepthCm) + " cm", "live-max-depth");
    p += "</div>";

    if (ctx.insertPressureError) {
      p += "<div class='row status err'>Action required: remove the tube, create suction pressure, then restart the insert step.</div>";
    }

    p += "<details><summary>Sensor diagnostics</summary>";
    p += "<div class='diagnostic-row'>Inside sensor index: <b id='live-inside-index'>" + String(ctx.insideSensorIndex) + "</b></div>";
    p += "<div class='diagnostic-row'>Inside sensor signed / abs delta: <b id='live-inside-delta'>";
    p += String(insideSignedDelta);
    p += " / ";
    p += String(insideAbsDelta);
    p += "</b></div>";

    if (idx == 0) {
      p += "<div class='diagnostic-row'>Inside threshold opaque / transparent: <b>+";
      p += String(LIGHT_SENSOR0_OPAQUE_DELTA_MIN);
      p += " / ";
      p += String(LIGHT_SENSOR0_TRANSPARENT_DELTA_MAX);
      p += " | clear abs <= ";
      p += String(LIGHT_SENSOR0_CLEAR_ABS_DELTA);
      p += "</b></div>";
    } else {
      p += "<div class='diagnostic-row'>Inside threshold ON/OFF: <b>";
      p += String(LIGHT_DETECT_ON_THRESHOLDS[idx]);
      p += " / ";
      p += String(LIGHT_DETECT_OFF_THRESHOLDS[idx]);
      p += "</b></div>";
    }

    p += "<div class='diagnostic-row'>Tracking started: <b id='live-tracking'>";
    p += ctx.trackingStarted ? "YES" : "NO";
    p += "</b> | Current depth: <b id='live-depth'>";
    p += String(ctx.currentDepthCm);
    p += " cm</b> | Ready for suction: <b id='live-ready-suction'>";
    p += ctx.readyForSuction ? "YES" : "NO";
    p += "</b></div>";
    p += "<div class='diagnostic-row'>Pressure raw / zero / delta: <b>";
    p += "<span id='live-pressure-raw'>";
    p += String(ctx.currentPressureRaw);
    p += "</span> / <span id='live-pressure-zero'>";
    p += String(ctx.config.pressureZeroRaw);
    p += "</span> / <span id='live-pressure-delta'>";
    p += String(ctx.currentPressureDeltaRaw);
    p += "</span></b> | Folded: <b id='live-pressure-folded'>";
    p += ctx.pressureFolded ? "YES" : "NO";
    p += "</b> | Target: <b id='live-pressure-ready'>";
    p += ctx.pressureReady ? "YES" : "NO";
    p += "</b></div>";
    p += "<div class='diagnostic-row'>Folded reference raw: <b id='live-folded-ref'>";
    p += String(ctx.foldedPressureReferenceRaw);
    p += "</b> | Score pressure raw: <b id='live-score-pressure'>";
    p += String(ctx.foldedPressureForScoreRaw);
    p += "</b> | Captured: <b id='live-pressure-captured'>";
    p += ctx.pressureScoreCaptured ? "YES" : "NO";
    p += "</b></div>";
    p += "<div class='diagnostic-row'>Release drop raw / ratio: <b id='live-release'>";
    p += String(ctx.releasePressureDropRaw);
    p += " / ";
    p += String(ctx.releasePressureRatioPercent);
    p += "%</b> | Buffer samples: <b id='live-buffer'>";
    p += String(ctx.foldedPressureSampleCount);
    p += "</b></div>";
    p += "<div class='diagnostic-row'>Contact bands: <b id='live-contact-bands'>";
    p += String(ctx.contactBandCount);
    p += "</b> | Entry marker ignored: <b id='live-contact-entry'>";
    p += ctx.contactEntryMarkerIgnored ? "YES" : "NO";
    p += "</b> | Active: <b id='live-contact-active'>";
    p += ctx.contactBandActive ? "YES" : "NO";
    p += "</b> | Miss count: <b id='live-contact-miss'>";
    p += String(ctx.contactMissCount);
    p += "</b> | Extra bands: <b id='live-contact-extra'>";
    p += String(ctx.contactUnexpectedBandCount);
    p += "</b></div>";
    p += "<div class='diagnostic-row'>Neck signed delta: <b id='live-neck-delta'>";
    p += String(lightSignedDelta(ctx.currentLightValues[0], ctx.config.lightBaselines[0]));
    p += "</b> | Contact detected: <b id='live-contact-detected'>";
    p += ctx.contactDetected ? "YES" : "NO";
    p += "</b> | Sequence error: <b id='live-contact-error'>";
    p += ctx.contactSequenceError ? "YES" : "NO";
    p += "</b></div>";

    for (int i = 0; i < 5; i++) {
      p += "<div class='diagnostic-row'>";
      p += "Sensor ";
      p += String(i);
      p += " | current: <b id='live-s";
      p += String(i);
      p += "-cur'>";
      p += String(ctx.currentLightValues[i]);
      p += "</b> | baseline: <b id='live-s";
      p += String(i);
      p += "-base'>";
      p += String(ctx.config.lightBaselines[i]);
      p += "</b> | signed delta: <b id='live-s";
      p += String(i);
      p += "-signed'>";
      p += String(lightSignedDelta(ctx.currentLightValues[i], ctx.config.lightBaselines[i]));
      p += "</b> | abs delta: <b id='live-s";
      p += String(i);
      p += "-abs'>";
      p += String(lightAbsDelta(ctx.currentLightValues[i], ctx.config.lightBaselines[i]));
      p += "</b> | threshold: <b>";
      if (i == 0) {
        p += "+";
        p += String(LIGHT_SENSOR0_OPAQUE_DELTA_MIN);
        p += "/";
        p += String(LIGHT_SENSOR0_TRANSPARENT_DELTA_MAX);
        p += " clear<=";
        p += String(LIGHT_SENSOR0_CLEAR_ABS_DELTA);
      } else {
        p += String(LIGHT_DETECT_ON_THRESHOLDS[i]);
        p += "/";
        p += String(LIGHT_DETECT_OFF_THRESHOLDS[i]);
      }
      p += "</b> | detected: <b id='live-s";
      p += String(i);
      p += "-detected'>";
      p += ctx.lightDetected[i] ? "YES" : "NO";
      p += "</b></div>";
    }
    p += "</details>";

    p += "<div class='row actions'>";
    if (ctx.insertPressureError) {
      p += actionPostHtml("/start-insert", "Restart Insert");
    }
    p += actionLinkHtml("/back", "Back to Ready");
    p += actionLinkHtml("/reset", "Reset setup");
    p += "</div>";

    p += liveUpdateScriptHtml("InsertState");
    p += pageEnd();
    return p;
  }

  void update(SetupContext& ctx) override {
    unsigned long now = millis();
    if (ctx.readyForSuction) {
      return;
    }

    if (ctx.insertPressureError) {
      return;
    }

    if (now - ctx.lastLightSampleMs < SAMPLE_INTERVAL_MS) {
      return;
    }

    ctx.lastLightSampleMs = now;

    // ===== Read pressure =====
    int32_t currentPressureRaw = 0;
    if (!readPressureRawAverage(PRESSURE_INSERT_READ_SAMPLES, PRESSURE_INSERT_READ_DELAY_MS, currentPressureRaw)) {
      ctx.pressureReady = false;
      ctx.pressureFolded = false;
      ctx.currentPressureReadOk = false;
      ctx.statusMessage = "Pressure sensor read failed. Check wiring and restart the insert step.";
      appLogLine(ctx.statusMessage);
      ctx.markSensorSnapshot(now);
      ctx.logSensorDebugNow(now, "insert-pressure-fail");
      return;
    }

    if (!ctx.trackingStarted) {
      trackPressureZeroIfResting(ctx.config, currentPressureRaw);
    }

    int32_t currentPressureDeltaRaw = rawToDeltaRaw(
      currentPressureRaw,
      ctx.config.pressureZeroRaw,
      ctx.config.pressureZeroDeadbandRaw
    );
    ctx.currentPressureRaw = currentPressureRaw;
    ctx.currentPressureDeltaRaw = currentPressureDeltaRaw;
    ctx.currentPressureReadOk = true;
    ctx.pressureFolded = isPressureFoldedRaw(currentPressureDeltaRaw);
    ctx.pressureReady = isPressureReadyRaw(currentPressureDeltaRaw);

    // ===== Read light sensors =====
    readCurrentLightValues(ctx.currentLightValues);
    ctx.updateLightDetection();
    bool neckDetected = ctx.isLightDetected(0);
    bool startedThisTick = false;

    // ===== Before insert starts =====
    if (!ctx.trackingStarted) {
      if (ctx.pressureReady) {
        ctx.statusMessage = "Target folded pressure reached. Insert the tube into the neck.";
      } else if (ctx.pressureFolded) {
        ctx.statusMessage = "Tube is folded with low pressure. You can continue, but pressure score may be reduced.";
      } else {
        ctx.statusMessage = "Fold the tube before inserting.";
      }
    }

    if (!ctx.trackingStarted && neckDetected && !ctx.pressureFolded) {
      ctx.insertPressureError = true;
      ctx.statusMessage = "The tube was inserted before the tube was folded. Remove it and restart.";
      appLogLine(ctx.statusMessage);
      ctx.markSensorSnapshot(now);
      ctx.logSensorDebugNow(now, "insert-order-error");
      return;
    }

    // ===== Start insert only when neck is detected AND the tube is folded =====
    if (!ctx.trackingStarted && neckDetected && ctx.pressureFolded) {
      ctx.trackingStarted = true;
      ctx.startTimeMs = now;
      ctx.totalTimeMs = 0;

      ctx.resetFoldedPressureTracking();
      ctx.addFoldedPressureSample(currentPressureDeltaRaw);
      ctx.beginContactTrackingAtEntryMarker();
      startedThisTick = true;

      ctx.statusMessage = "Tube detected. Timer started.";
    }

    // ===== During insert =====
    if (ctx.trackingStarted) {
      ctx.totalTimeMs = now - ctx.startTimeMs;
      ctx.updateContactBandDetection();

      bool hasTubeEntered = ctx.trackingStarted;
      int32_t pressureReferenceRaw = ctx.foldedPressureReferenceRaw;
      ctx.releasePressureDropRaw = (pressureReferenceRaw > currentPressureDeltaRaw)
        ? (pressureReferenceRaw - currentPressureDeltaRaw)
        : 0;
      ctx.releasePressureRatioPercent = pressureRatioPercent(
        currentPressureDeltaRaw,
        pressureReferenceRaw
      );

      bool releaseCandidate =
        hasTubeEntered &&
        ctx.foldedPressureSampleCount > 0 &&
        isReleaseCandidateRaw(
          currentPressureDeltaRaw,
          pressureReferenceRaw
        );
      bool pressureFallingFromReference =
        hasTubeEntered &&
        ctx.foldedPressureSampleCount > 0 &&
        isPressureFallingFromReferenceRaw(
          currentPressureDeltaRaw,
          pressureReferenceRaw
        );
      bool updateFoldedReference =
        shouldUpdateFoldedPressureReferenceRaw(
          currentPressureDeltaRaw,
          pressureReferenceRaw
        );

      if (releaseCandidate) {
        ctx.captureFoldedPressureForScore();

        if (ctx.releaseCandidateSinceMs == 0) {
          ctx.releaseCandidateSinceMs = now;
        }

        if ((now - ctx.releaseCandidateSinceMs) >= PRESSURE_RELEASE_HOLD_MS) {
          ctx.readyForSuction = true;
          ctx.statusMessage = "Suction release detected. Continue the suction step.";
          appLogLine(
            String("Tube released. Folded pressure score raw=")
              + String(ctx.foldedPressureForScoreRaw)
              + " | Current pressure raw="
              + String(currentPressureDeltaRaw)
              + " | Insert time="
              + String(ctx.totalTimeMs / 1000.0f, 2)
              + " s"
          );
          ctx.markSensorSnapshot(now);
          ctx.logSensorDebugNow(now, "insert-release");
          ctx.transitionTo(&suctionState());
          return;
        }
      } else {
        if (ctx.releaseCandidateSinceMs != 0 || ctx.pressureScoreCaptured) {
          ctx.releaseCandidateSinceMs = 0;
          ctx.pressureScoreCaptured = false;
          ctx.foldedPressureForScoreRaw = 0;
        }

        if (ctx.pressureFolded && !startedThisTick && updateFoldedReference) {
          ctx.addFoldedPressureSample(currentPressureDeltaRaw);
          ctx.statusMessage = ctx.pressureReady
            ? "Maintain folded pressure until the target depth, then release."
            : "Maintain the low folded pressure until the target depth, then release.";
        } else if (pressureFallingFromReference) {
          ctx.statusMessage = "Tube release is being detected. Keep the tube released steadily.";
        } else if (startedThisTick) {
          ctx.statusMessage = "Tube detected. Timer started.";
        } else if (hasTubeEntered) {
          ctx.statusMessage = "Pressure dropped, but release is not confirmed. Keep the tube folded or release more clearly.";
        } else {
          ctx.statusMessage = "Pressure is too low before the target depth. Fold the tube again before releasing.";
        }
      }
    }

    ctx.markSensorSnapshot(now);
    ctx.logSensorDebugIfDue(now, "insert");
  }
};

class SuctionState : public WorkingFlowState {
public:
  const char* name() const override {
    return "SuctionState";
  }

  bool ownsSerialSensorSampling() const override {
    return true;
  }

  void enter(SetupContext& ctx) override {
    ctx.lastLightSampleMs = 0;
    ctx.suctionStarted = true;
    ctx.suctionCompleted = false;

    readCurrentLightValues(ctx.currentLightValues);
    ctx.updateLightDetection();

    int neckDelta = lightSignedDelta(
      ctx.currentLightValues[0],
      ctx.config.lightBaselines[0]
    );

    bool neckOnBand = neckDelta >= CONTACT_BAND_ON_SIGNED_DELTA;

    // Markers that must pass the neck sensor during withdrawal:
    // all inserted depth markers plus the front entry marker.
    ctx.expectedExitBandCount = ctx.contactBandCount + 1;
    if (neckOnBand && ctx.expectedExitBandCount > 0) {
      // If suction starts while already on a band, ignore that band.
      ctx.expectedExitBandCount--;
    }

    ctx.exitBandCount = 0;
    ctx.exitBlackBandSeen = false;
    ctx.exitReadyToCountBand = !neckOnBand;
    ctx.exitBandActive = neckOnBand;
    ctx.tubeClearSinceMs = 0;

    unsigned long now = millis();

    if (ctx.startTimeMs > 0) {
      ctx.totalTimeMs = now - ctx.startTimeMs;
    }

    ctx.statusMessage = "Suction started. Withdraw the tube until all black bands exit.";
    ctx.markSensorSnapshot(now);
    ctx.logSensorDebugNow(now, "suction-enter");
  }

  void onBack(SetupContext& ctx) override {
    ctx.statusMessage = "Returned to ready screen.";
    ctx.transitionTo(&readyState());
  }

  void onReset(SetupContext& ctx) override {
    WiFi.disconnect(false, true);
    ctx.clearConfig();
    ctx.statusMessage = "Setup has been reset.";
    ctx.transitionTo(&modeSelectState());
  }

  void onStartInsert(SetupContext& ctx) override {
    ctx.statusMessage = "Starting a new practice session.";
    ctx.transitionTo(&insertState());
  }

  String renderPage(SetupContext& ctx) override {
    String p = pageStart("Suction");
    p += "<h2>Practice: Suction</h2>";
    p += "<p class='lead'>Continue the suction step and withdraw the tube. The trainer will move to the score screen after the tube exits.</p>";

    p += statusHtmlWithId(ctx.statusMessage, ctx.suctionCompleted ? "ok" : "warn", "live-status");

    p += "<div class='metric-grid'>";
    p += metricHtmlWithId("Tube", ctx.insideDetected ? "Detected" : "Exited", "live-tube");
    p += metricHtmlWithId("Time", String(ctx.totalTimeMs / 1000.0f, 2) + " s", "live-time");
    p += metricHtmlWithId("Current depth", String(ctx.currentDepthCm) + " cm", "live-current-depth");
    p += metricHtmlWithId("Contact", (ctx.contactDetected || ctx.contactSequenceError) ? "Suspected" : "Clear", "live-contact");
    p += metricHtmlWithId("Max depth", String(ctx.maxDepthCm) + " cm", "live-max-depth");
    p += "</div>";

    p += "<details><summary>Sensor diagnostics</summary>";
    p += "<div class='diagnostic-row'>Folded pressure score raw: <b id='live-score-pressure'>";
    p += String(ctx.foldedPressureForScoreRaw);
    p += "</b> | Reference raw: <b id='live-folded-ref'>";
    p += String(ctx.foldedPressureReferenceRaw);
    p += "</b> | Captured: <b id='live-pressure-captured'>";
    p += ctx.pressureScoreCaptured ? "YES" : "NO";
    p += "</b></div>";
    p += "<div class='diagnostic-row'>Release drop raw / ratio: <b id='live-release'>";
    p += String(ctx.releasePressureDropRaw);
    p += " / ";
    p += String(ctx.releasePressureRatioPercent);
    p += "%</b></div>";
    p += "<div class='diagnostic-row'>Contact bands: <b id='live-contact-bands'>";
    p += String(ctx.contactBandCount);
    p += "</b> | Entry marker ignored: <b id='live-contact-entry'>";
    p += ctx.contactEntryMarkerIgnored ? "YES" : "NO";
    p += "</b> | Active: <b id='live-contact-active'>";
    p += ctx.contactBandActive ? "YES" : "NO";
    p += "</b> | Miss count: <b id='live-contact-miss'>";
    p += String(ctx.contactMissCount);
    p += "</b> | Extra bands: <b id='live-contact-extra'>";
    p += String(ctx.contactUnexpectedBandCount);
    p += "</b></div>";
    p += "<div class='diagnostic-row'>Last marker expected / actual depth: <b>";
    if (ctx.lastContactExpectedDepthCm >= 0) {
      p += String(ctx.lastContactExpectedDepthCm);
      p += " cm";
    } else {
      p += "none";
    }
    p += " / ";
    p += String(ctx.lastContactActualDepthCm);
    p += " cm</b> | Neck signed delta: <b id='live-neck-delta'>";
    p += String(lightSignedDelta(ctx.currentLightValues[0], ctx.config.lightBaselines[0]));
    p += "</b></div>";
    p += "<div class='diagnostic-row'>Contact detected: <b id='live-contact-detected'>";
    p += ctx.contactDetected ? "YES" : "NO";
    p += "</b> | Sequence error: <b id='live-contact-error'>";
    p += ctx.contactSequenceError ? "YES" : "NO";
    p += "</b></div>";
    p += "<div class='diagnostic-row'>Suction started: <b id='live-suction-started'>";
    p += ctx.suctionStarted ? "YES" : "NO";
    p += "</b> | Suction completed: <b id='live-suction-completed'>";
    p += ctx.suctionCompleted ? "YES" : "NO";
    p += "</b> | Ready for suction: <b id='live-ready-suction'>";
    p += ctx.readyForSuction ? "YES" : "NO";
    p += "</b></div>";
    p += "</details>";

    p += "<div class='row actions'>";
    p += actionPostHtml("/start-insert", "Start New Practice");
    p += actionLinkHtml("/back", "Back to Ready");
    p += actionLinkHtml("/reset", "Reset setup");
    p += "</div>";

    p += liveUpdateScriptHtml("SuctionState");
    p += pageEnd();
    return p;
  }

  void update(SetupContext& ctx) override {
    if (ctx.suctionCompleted) {
      return;
    }

    unsigned long now = millis();
    if (now - ctx.lastLightSampleMs < SAMPLE_INTERVAL_MS) {
      return;
    }

    ctx.lastLightSampleMs = now;

    readCurrentLightValues(ctx.currentLightValues);
    ctx.updateLightDetection();

    if (!ctx.suctionStarted) {
      ctx.markSensorSnapshot(now);
      ctx.logSensorDebugIfDue(now, "suction-wait");
      return;
    }

    ctx.totalTimeMs = (ctx.startTimeMs > 0) ? (now - ctx.startTimeMs) : 0;

    int neckDelta = lightSignedDelta(
      ctx.currentLightValues[0],
      ctx.config.lightBaselines[0]
    );

    bool bandOnCandidate = neckDelta >= CONTACT_BAND_ON_SIGNED_DELTA;
    bool bandOffCandidate = neckDelta <= CONTACT_BAND_OFF_SIGNED_DELTA;

    // Ignore a band already under the neck sensor when suction begins.
    if (!ctx.exitReadyToCountBand) {
      if (bandOffCandidate) {
        ctx.exitReadyToCountBand = true;
        ctx.exitBandActive = false;
      }
    } else {
      if (bandOnCandidate && !ctx.exitBandActive) {
        ctx.exitBandActive = true;
        ctx.exitBlackBandSeen = true;
        ctx.exitBandCount++;
      } else if (bandOffCandidate && ctx.exitBandActive) {
        ctx.exitBandActive = false;
      }
    }

    // Finish only after a valid withdrawal band has been seen and cleared,
    // all required markers have passed, and the tube remains outside the
    // inside sensors long enough to be stable.
    bool passedRequiredBands = ctx.exitBandCount >= ctx.expectedExitBandCount;
    bool exitFullyClear =
      passedRequiredBands &&
      ctx.exitBlackBandSeen &&
      !ctx.exitBandActive &&
      !bandOnCandidate &&
      !ctx.insideDetected;

    if (exitFullyClear) {
      if (ctx.tubeClearSinceMs == 0) {
        ctx.tubeClearSinceMs = now;
      }

      if ((now - ctx.tubeClearSinceMs) >= 400) {
        ctx.suctionCompleted = true;
        ctx.statusMessage = "Tube exited after black band cleared. Calculating score.";
        appLogLine(String("Suction completed. Total time=") + String(ctx.totalTimeMs / 1000.0f, 2) + " s");
        ctx.markSensorSnapshot(now);
        ctx.logSensorDebugNow(now, "suction-complete");
        ctx.transitionTo(&scoreState());
        return;
      }
    } else {
      ctx.tubeClearSinceMs = 0;
    }

    if (ctx.contactDetected || ctx.contactSequenceError) {
      ctx.statusMessage = "Contact marker mismatch detected. Continue withdrawing the tube.";
    } else {
      ctx.statusMessage = "Suction in progress. Continue until the tube exits.";
    }

    ctx.markSensorSnapshot(now);
    ctx.logSensorDebugIfDue(now, "suction");
  }
};

class ScoreState : public AppState {
public:
  const char* name() const override {
    return "ScoreState";
  }

  void enter(SetupContext& ctx) override {
    ctx.statusMessage = "Score ready.";
  }

  void onBack(SetupContext& ctx) override {
    ctx.statusMessage = "Returned to ready screen.";
    ctx.transitionTo(&readyState());
  }

  void onReset(SetupContext& ctx) override {
    WiFi.disconnect(false, true);
    ctx.clearConfig();
    ctx.statusMessage = "Setup has been reset.";
    ctx.transitionTo(&modeSelectState());
  }

  void onStartInsert(SetupContext& ctx) override {
    ctx.statusMessage = "Starting a new practice session.";
    ctx.transitionTo(&insertState());
  }

  String renderPage(SetupContext& ctx) override {
    const int depthMaxScore = 30;
    const int durationMaxScore = 20;

    int depthScore = scoreDepthCm(ctx.maxDepthCm);
    int durationScore = scoreDurationMs(ctx.totalTimeMs);
    int contactEvents = ctx.contactMissCount + ctx.contactUnexpectedBandCount;
    int contactScore = scoreContactEvents(contactEvents);
    float pressureMmHg = 0.0f;
    bool pressureScoreAvailable =
      ctx.pressureScoreCaptured &&
      pressureDeltaRawToMmHg(ctx.foldedPressureForScoreRaw, pressureMmHg);
    int pressureScore = pressureScoreAvailable ? scorePressureMmHg(pressureMmHg) : 0;
    int availableScore = depthMaxScore + durationMaxScore + CONTACT_MAX_SCORE +
      (pressureScoreAvailable ? PRESSURE_MAX_SCORE : 0);
    int rawScore = depthScore + durationScore + contactScore +
      (pressureScoreAvailable ? pressureScore : 0);
    int normalizedScore = normalizeScore(rawScore, availableScore);
    String pressureMetric = "Not scored";
    String contactMetric = String(contactScore) + " / " + String(CONTACT_MAX_SCORE);

    if (ctx.insertPressureError) {
      pressureMetric = "Error";
    } else if (pressureScoreAvailable) {
      pressureMetric = String(pressureScore) + " / " + String(PRESSURE_MAX_SCORE);
    } else if (ctx.pressureScoreCaptured) {
      pressureMetric = String(ctx.foldedPressureForScoreRaw) + " raw";
    }

    String p = pageStart("Score");
    p += "<h2>Practice Score</h2>";
    p += "<p class='lead'>Review the session result, then start another practice run when ready.</p>";

    p += statusHtml(ctx.statusMessage, "ok");

    p += "<div class='score-hero'><div class='small'>Total score</div><div class='value'>";
    p += String(normalizedScore);
    p += "</div><div><b>";
    p += htmlEscape(scoreLevel(normalizedScore));
    p += "</b> - ";
    p += htmlEscape(scoreInterpretation(normalizedScore));
    p += "</div></div>";

    p += "<div class='metric-grid'>";
    p += metricHtml("Measured score", String(rawScore) + " / " + String(availableScore));
    p += metricHtml("Total time", String(ctx.totalTimeMs / 1000.0f, 2) + " s");
    p += metricHtml("Max depth", String(ctx.maxDepthCm) + " cm");
    p += metricHtml("Pressure", pressureMetric);
    p += metricHtml("Contact", contactMetric);
    p += "</div>";

    p += "<div class='section'>";
    p += "<h3>Score breakdown</h3>";

    p += "<div class='row small'>Depth: <b>";
    p += String(depthScore);
    p += " / ";
    p += String(depthMaxScore);
    p += "</b> | Max depth: <b>";
    p += String(ctx.maxDepthCm);
    p += " cm</b></div>";

    p += "<div class='row small'>Pass duration: <b>";
    p += String(durationScore);
    p += " / ";
    p += String(durationMaxScore);
    p += "</b> | Total time: <b>";
    p += String(ctx.totalTimeMs / 1000.0f, 2);
    p += " s</b></div>";

    p += "<div class='row small'>Folded pressure: <b>";
    if (pressureScoreAvailable) {
      p += String(pressureScore);
      p += " / ";
      p += String(PRESSURE_MAX_SCORE);
      p += "</b> | Measured: <b>";
      p += String(pressureMmHg, 1);
      p += " mmHg</b> | ";
      p += htmlEscape(pressureScoreLabel(pressureMmHg));
    } else if (ctx.pressureScoreCaptured) {
      p += "captured, awaiting raw-to-mmHg calibration";
      p += "</b> | Score raw: <b>";
      p += String(ctx.foldedPressureForScoreRaw);
      p += "</b>";
    } else {
      p += "not captured</b>";
    }
    p += "</div>";

    p += "<div class='row small'>Contact: <b>";
    p += String(contactScore);
    p += " / ";
    p += String(CONTACT_MAX_SCORE);
    p += "</b> | Events: <b>";
    p += String(contactEvents);
    p += "</b> | Bands: <b>";
    p += String(ctx.contactBandCount);
    p += "</b></div>";

    p += "<div class='row small'>Folded pressure is included only after calibration mapping is enabled.</div>";
    p += "</div>";

    p += "<details><summary>Session diagnostics</summary>";
    p += "<div class='diagnostic-row'>Measured score: <b>";
    p += String(rawScore);
    p += " / ";
    p += String(availableScore);
    p += "</b></div>";
    p += "<div class='diagnostic-row'>Folded pressure score raw: <b>";
    p += String(ctx.foldedPressureForScoreRaw);
    p += "</b> | Reference raw: <b>";
    p += String(ctx.foldedPressureReferenceRaw);
    p += "</b> | Captured: <b>";
    p += (ctx.pressureScoreCaptured ? "YES" : "NO");
    p += "</b></div>";
    p += "<div class='diagnostic-row'>Release drop raw / ratio: <b>";
    p += String(ctx.releasePressureDropRaw);
    p += " / ";
    p += String(ctx.releasePressureRatioPercent);
    p += "%</b></div>";
    p += "<div class='diagnostic-row'>Contact bands: <b>";
    p += String(ctx.contactBandCount);
    p += "</b> | Entry marker ignored: <b>";
    p += (ctx.contactEntryMarkerIgnored ? "YES" : "NO");
    p += "</b> | Miss count: <b>";
    p += String(ctx.contactMissCount);
    p += "</b> | Extra bands: <b>";
    p += String(ctx.contactUnexpectedBandCount);
    p += "</b></div>";
    p += "<div class='diagnostic-row'>Last marker expected / actual depth: <b>";
    if (ctx.lastContactExpectedDepthCm >= 0) {
      p += String(ctx.lastContactExpectedDepthCm);
      p += " cm";
    } else {
      p += "none";
    }
    p += " / ";
    p += String(ctx.lastContactActualDepthCm);
    p += " cm</b> | Contact detected: <b>";
    p += ctx.contactDetected ? "YES" : "NO";
    p += "</b> | Sequence error: <b>";
    p += ctx.contactSequenceError ? "YES" : "NO";
    p += "</b></div>";
    p += "<div class='diagnostic-row'>Insert pressure error: <b>";
    p += (ctx.insertPressureError ? "YES" : "NO");
    p += "</b> | Ready for suction: <b>";
    p += (ctx.readyForSuction ? "YES" : "NO");
    p += "</b> | Suction completed: <b>";
    p += (ctx.suctionCompleted ? "YES" : "NO");
    p += "</b></div>";
    p += "</details>";

    p += "<div class='row actions'>";
    p += actionPostHtml("/start-insert", "Start New Practice");
    p += actionLinkHtml("/back", "Back to Ready");
    p += actionLinkHtml("/reset", "Reset setup");
    p += "</div>";

    p += pageEnd();
    return p;
  }
};

// =========================
// State singletons
// =========================

ModeSelectState gModeSelectState;
WifiConfigState gWifiConfigState;
WifiConnectingState gWifiConnectingState;
ReadyState gReadyState;
CalibrateState gCalibrateState;
InsertState gInsertState;
SuctionState gSuctionState;
ScoreState gScoreState;

AppState& modeSelectState()     { return gModeSelectState; }
AppState& wifiConfigState()     { return gWifiConfigState; }
AppState& wifiConnectingState() { return gWifiConnectingState; }
AppState& readyState()          { return gReadyState; }
AppState& calibrateState()      { return gCalibrateState; }
AppState& insertState()         { return gInsertState; }
AppState& suctionState()        { return gSuctionState; }
AppState& scoreState()          { return gScoreState; }

// =========================
// HTTP handlers
// =========================

String yesNo(bool value) {
  return value ? "YES" : "NO";
}

String liveStatusTone(const SetupContext& ctx, const String& stateName) {
  if (stateName == "InsertState") {
    return ctx.insertPressureError ? "err" : ((ctx.pressureFolded || ctx.trackingStarted) ? "ok" : "warn");
  }

  if (stateName == "SuctionState") {
    return ctx.suctionCompleted ? "ok" : "warn";
  }

  if (stateName == "ScoreState" || stateName == "ReadyState") {
    return "ok";
  }

  return "";
}

String liveStateJson(const SetupContext& ctx) {
  String stateName = ctx.current ? ctx.current->name() : "NoState";
  String pressureLabel = ctx.pressureReady ? "Target" : (ctx.pressureFolded ? "Folded low" : "Not folded");
  String tubeLabel = ctx.insideDetected ? "Detected" : ((stateName == "SuctionState") ? "Exited" : "Not detected");
  String contactLabel = (ctx.contactDetected || ctx.contactSequenceError) ? "Suspected" : "Clear";
  int idx = ctx.insideSensorIndex;
  if (idx < 0 || idx >= 5) idx = 0;

  String json = "{";
  appendJsonString(json, "state", stateName);
  appendJsonString(json, "status", ctx.statusMessage);
  appendJsonString(json, "statusTone", liveStatusTone(ctx, stateName));
  appendJsonString(json, "pressure", pressureLabel);
  appendJsonString(json, "tube", tubeLabel);
  appendJsonString(json, "time", String(ctx.totalTimeMs / 1000.0f, 2) + " s");
  appendJsonString(json, "maxDepth", String(ctx.maxDepthCm) + " cm");
  appendJsonString(json, "currentDepth", String(ctx.currentDepthCm) + " cm");
  appendJsonString(json, "contact", contactLabel);
  appendJsonString(json, "insideIndex", String(ctx.insideSensorIndex));
  appendJsonString(
    json,
    "insideDelta",
    String(lightSignedDelta(ctx.currentLightValues[idx], ctx.config.lightBaselines[idx]))
      + " / "
      + String(lightAbsDelta(ctx.currentLightValues[idx], ctx.config.lightBaselines[idx]))
  );
  appendJsonString(json, "tracking", yesNo(ctx.trackingStarted));
  appendJsonString(json, "readySuction", yesNo(ctx.readyForSuction));
  appendJsonString(json, "pressureRaw", String(ctx.currentPressureRaw));
  appendJsonString(json, "pressureZero", String(ctx.config.pressureZeroRaw));
  appendJsonString(json, "pressureDelta", String(ctx.currentPressureDeltaRaw));
  appendJsonString(json, "pressureFolded", yesNo(ctx.pressureFolded));
  appendJsonString(json, "pressureReady", yesNo(ctx.pressureReady));
  appendJsonString(json, "foldedRef", String(ctx.foldedPressureReferenceRaw));
  appendJsonString(json, "scorePressure", String(ctx.foldedPressureForScoreRaw));
  appendJsonString(json, "pressureCaptured", yesNo(ctx.pressureScoreCaptured));
  appendJsonString(json, "release", String(ctx.releasePressureDropRaw) + " / " + String(ctx.releasePressureRatioPercent) + "%");
  appendJsonString(json, "buffer", String(ctx.foldedPressureSampleCount));
  appendJsonString(json, "contactEntry", yesNo(ctx.contactEntryMarkerIgnored));
  appendJsonString(json, "contactBands", String(ctx.contactBandCount));
  appendJsonString(json, "contactActive", yesNo(ctx.contactBandActive));
  appendJsonString(json, "contactMiss", String(ctx.contactMissCount));
  appendJsonString(json, "contactExtra", String(ctx.contactUnexpectedBandCount));
  appendJsonString(json, "neckDelta", String(lightSignedDelta(ctx.currentLightValues[0], ctx.config.lightBaselines[0])));
  appendJsonString(json, "contactDetected", yesNo(ctx.contactDetected));
  appendJsonString(json, "contactError", yesNo(ctx.contactSequenceError));
  appendJsonString(json, "suctionStarted", yesNo(ctx.suctionStarted));
  appendJsonString(json, "suctionCompleted", yesNo(ctx.suctionCompleted));

  for (int i = 0; i < 5; i++) {
    String prefix = String("s") + String(i);
    appendJsonString(json, (prefix + "Cur").c_str(), String(ctx.currentLightValues[i]));
    appendJsonString(json, (prefix + "Base").c_str(), String(ctx.config.lightBaselines[i]));
    appendJsonString(json, (prefix + "Signed").c_str(), String(lightSignedDelta(ctx.currentLightValues[i], ctx.config.lightBaselines[i])));
    appendJsonString(json, (prefix + "Abs").c_str(), String(lightAbsDelta(ctx.currentLightValues[i], ctx.config.lightBaselines[i])));
    appendJsonString(json, (prefix + "Detected").c_str(), yesNo(ctx.lightDetected[i]));
  }

  json += "}";
  return json;
}

String sensorRawJson() {
  uint16_t lightValues[5] = {0, 0, 0, 0, 0};
  readCurrentLightValues(lightValues);

  PressureReadStats pressureStats;
  bool pressureOk = readPressureRawStatsWithTimeout(
    PRESSURE_DEBUG_READ_SAMPLES,
    PRESSURE_INSERT_READ_DELAY_MS,
    pressureStats,
    PRESSURE_DEBUG_READY_TIMEOUT_MS
  );

  String json = "{";
  appendJsonString(json, "pressure", pressureOk ? String(pressureStats.averageRaw) : "ERR");
  appendJsonString(json, "l0", String(lightValues[0]));
  appendJsonString(json, "l1", String(lightValues[1]));
  appendJsonString(json, "l2", String(lightValues[2]));
  appendJsonString(json, "l3", String(lightValues[3]));
  appendJsonString(json, "l4", String(lightValues[4]));
  json += "}";
  return json;
}

void handleRoot() {
  server.send(200, "text/html", app.renderPage());
}

void handleLiveState() {
  server.sendHeader("Cache-Control", "no-cache, no-store, must-revalidate");
  server.send(200, "application/json", liveStateJson(app));
}

void handleSensorRawPage() {
  server.send(200, "text/html", sensorRawPageHtml());
}

void handleSensorRawJson() {
  server.sendHeader("Cache-Control", "no-cache, no-store, must-revalidate");
  server.send(200, "application/json", sensorRawJson());
}

void handleCaptiveRedirect() {
  server.sendHeader("Location", String("http://") + apIP.toString(), true);
  server.sendHeader("Cache-Control", "no-cache, no-store, must-revalidate");
  server.send(302, "text/plain", "");
}

void handleSelectMode() {
  String mode = server.arg("mode");
  if (app.current) {
    app.current->onModeSelected(app, mode);
  }
  server.sendHeader("Location", "/");
  server.send(303);
}

void handleConnectWifi() {
  String ssid = server.arg("ssid");
  String password = server.arg("password");
  if (app.current) {
    app.current->onConnectWifi(app, ssid, password);
  }
  server.sendHeader("Location", "/");
  server.send(303);
}

void handleSerialDebug() {
  app.config.serialDebugEnabled = false;
  app.saveConfig();
  server.sendHeader("Location", "/sensors");
  server.send(303);
}

void handleBack() {
  if (app.current) {
    app.current->onBack(app);
  }
  server.sendHeader("Location", "/");
  server.send(303);
}

void handleReset() {
  if (app.current) {
    app.current->onReset(app);
  }
  server.sendHeader("Location", "/");
  server.send(303);
}

void handleCalibrate() {
  String action = server.arg("action");

  if (app.current == &gCalibrateState) {
    gCalibrateState.handleCalibrateButton(app, action);
  }

  server.sendHeader("Location", "/");
  server.send(303);
}

void handleStartInsert() {
  if (app.current) {
    app.current->onStartInsert(app);
  }
  server.sendHeader("Location", "/");
  server.send(303);
}


// =========================
// Setup / Loop
// =========================
void startPortal() {
  WiFi.mode(WIFI_AP_STA);
  WiFi.softAPConfig(apIP, gateway, subnet, dhcpStartIP, apIP);
  WiFi.softAP(AP_SSID, AP_PASSWORD);

  dnsServer.start(53, "*",apIP );

  appLogLine("=== AP Portal Started ===");
  appLogLine(String("AP SSID: ") + AP_SSID);
  appLogLine(String("AP PASS: ") + AP_PASSWORD);
  appLogLine(String("AP IP: ") + WiFi.softAPIP().toString());
  appLogLine(String("AP DNS: ") + apIP.toString());
}

void setup() {
  Serial.begin(115200);
  delay(STARTUP_DELAY_MS);
  esp_log_level_set("wifi", ESP_LOG_NONE);
  esp_log_level_set("phy", ESP_LOG_NONE);
  appLogLine("OK");
  if (DEBUG_LIVE_LOG) {
    appLogLine(String("A0 test = ") + String(analogRead(LIGHT_SENSOR_PINS[0])));
  }

  for (int i = 0; i < 5; i++) {
    pinMode(LIGHT_SENSOR_PINS[i], INPUT);
  }

  pinMode(HX_DOUT_PIN, INPUT);
  pinMode(HX_SCK_PIN, OUTPUT);
  digitalWrite(HX_SCK_PIN, LOW);

  startPortal();
  server.on("/", HTTP_GET, handleRoot);
  server.on("/live.json", HTTP_GET, handleLiveState);
  server.on("/sensors", HTTP_GET, handleSensorRawPage);
  server.on("/sensor-raw.json", HTTP_GET, handleSensorRawJson);
  server.on("/select-mode", HTTP_POST, handleSelectMode);
  server.on("/connect-wifi", HTTP_POST, handleConnectWifi);
  server.on("/serial-debug", HTTP_POST, handleSerialDebug);
  server.on("/back", HTTP_GET, handleBack);
  server.on("/reset", HTTP_GET, handleReset);
  server.on("/calibrate", HTTP_POST, handleCalibrate);
  
  server.on("/generate_204", HTTP_GET, handleCaptiveRedirect);
  server.on("/gen_204", HTTP_GET, handleCaptiveRedirect);
  server.on("/hotspot-detect.html", HTTP_GET, handleCaptiveRedirect);
  server.on("/library/test/success.html", HTTP_GET, handleCaptiveRedirect);
  server.on("/fwlink", HTTP_GET, handleCaptiveRedirect);
  server.on("/connecttest.txt", HTTP_GET, handleCaptiveRedirect);
  server.on("/ncsi.txt", HTTP_GET, handleCaptiveRedirect);
  server.on("/redirect", HTTP_GET, handleCaptiveRedirect);
  server.on("/start-insert", HTTP_POST, handleStartInsert);

  server.onNotFound(handleCaptiveRedirect);
  server.begin();

  app.boot();
}

void loop() {
  dnsServer.processNextRequest();
  server.handleClient();
  app.update();
}
