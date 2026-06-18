#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

// ── WiFi credentials ─────────────────────────────────────────
#define WIFI_SSID "Jiménez Wilhelm 4G"
#define WIFI_PASS "Wilhelm25"

// ── MQTT broker ───────────────────────────────────────────────
#define MQTT_HOST      "broker.emqx.io"
#define MQTT_PORT      1883
#define MQTT_CLIENT_ID "smartpethome-motion-001"

// ── Device identity ───────────────────────────────────────────
#define SERIAL_NUMBER "MOTION-001"
#define DEVICE_TYPE   "motion_monitoring_network"

// ── MQTT topics ───────────────────────────────────────────────
#define TOPIC_STATUS    "smartpethome/devices/MOTION-001/status"
#define TOPIC_TELEMETRY "smartpethome/devices/MOTION-001/telemetry"
#define TOPIC_COMMAND   "smartpethome/devices/MOTION-001/command"
#define TOPIC_ACK       "smartpethome/devices/MOTION-001/ack"

// ── Hardware pins (do not change) ────────────────────────────
#define PIR_PIN    27
#define LED_VERDE  25
#define LED_ROJO   26

// ── Timing constants ──────────────────────────────────────────
#define PIR_CALIBRATION_MS  30000UL   // 30 s warm-up
#define STATUS_INTERVAL_MS  10000UL   // heartbeat every 10 s

// No-motion threshold starts at 60 s but can be changed at runtime via
// the set_inactivity_limit command (value stored in milliseconds).
unsigned long noMotionThresholdMs = 60000UL;

// ── Runtime state ─────────────────────────────────────────────
WiFiClient   wifiClient;
PubSubClient mqttClient(wifiClient);

bool monitoringEnabled  = true;   // can be toggled by commands
bool noMotionAlertSent  = false;  // latch — true after first 60-s alert
bool lastPirState       = false;  // last stable PIR reading

unsigned long noMotionStartMs  = 0;   // millis() when PIR went LOW (0 = not counting)
unsigned long lastStatusMs     = 0;
unsigned long lastMqttRetryMs  = 0;

// ── Forward declarations ───────────────────────────────────────
bool connectWiFi();
void connectMQTT();
void onCommand(byte* payload, unsigned int length);
void publishStatus(bool motionDetected);
void publishTelemetry(const char* event, bool motionDetected, int pirState,
                      unsigned long noMotionSeconds);
void publishAck(const char* commandId, const char* message);

// ── WiFi ──────────────────────────────────────────────────────
// Returns true if connected, false if timed out after 15 s.
// Never blocks forever — PIR+LED logic must keep working without network.
bool connectWiFi() {
    Serial.printf("[WiFi] Connecting to %s", WIFI_SSID);
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    unsigned long start = millis();
    while (WiFi.status() != WL_CONNECTED) {
        if (millis() - start > 15000UL) {
            Serial.println("\n[WiFi] Timeout — continuing without network");
            return false;
        }
        delay(500);
        Serial.print(".");
    }
    Serial.printf("\n[WiFi] Connected IP=%s\n", WiFi.localIP().toString().c_str());
    return true;
}

// ── MQTT callback ─────────────────────────────────────────────
void mqttCallback(char* topic, byte* payload, unsigned int length) {
    if (String(topic) == TOPIC_COMMAND) {
        onCommand(payload, length);
    }
}

// ── MQTT connection ───────────────────────────────────────────
// Non-blocking: makes one attempt and returns. Loop() retries next cycle.
void connectMQTT() {
    if (mqttClient.connected()) return;
    if (WiFi.status() != WL_CONNECTED) return;
    Serial.print("[MQTT] Connecting...");
    if (mqttClient.connect(MQTT_CLIENT_ID)) {
        Serial.println(" connected");
        mqttClient.subscribe(TOPIC_COMMAND);
    } else {
        Serial.printf(" failed rc=%d\n", mqttClient.state());
    }
}

// ── Command handler ───────────────────────────────────────────
void onCommand(byte* payload, unsigned int length) {
    JsonDocument doc;
    if (deserializeJson(doc, payload, length) != DeserializationError::Ok) return;

    const char* cmd        = doc["command"] | "";
    const char* commandId  = doc["command_id"] | "unknown";

    if (strcmp(cmd, "set_inactivity_limit") == 0) {
        int minutes = doc["params"]["minutes"] | 0;
        if (minutes > 0) {
            noMotionThresholdMs = (unsigned long)minutes * 60000UL;
            noMotionAlertSent   = false;
            noMotionStartMs     = 0;
            Serial.printf("[CMD] Inactivity limit set to %d min\n", minutes);
            publishAck(commandId, ("Inactivity limit set to " + String(minutes) + " min").c_str());
        } else {
            publishAck(commandId, "Invalid minutes value");
        }

    } else if (strcmp(cmd, "enable_monitoring") == 0) {
        monitoringEnabled = true;
        noMotionStartMs   = 0;
        publishAck(commandId, "Monitoring enabled");

    } else if (strcmp(cmd, "disable_monitoring") == 0) {
        monitoringEnabled = false;
        noMotionStartMs   = 0;
        publishAck(commandId, "Monitoring disabled");

    } else if (strcmp(cmd, "reset_motion_alert") == 0) {
        // Calibrate: reset latch and timer so the sensor starts fresh
        noMotionAlertSent = false;
        noMotionStartMs   = 0;
        Serial.println("[CMD] Sensor calibrated — motion monitoring reset");
        publishAck(commandId, "Sensor calibrated");

    } else if (strcmp(cmd, "get_status") == 0) {
        publishStatus(lastPirState);
        publishAck(commandId, "Status published");
    }
}

// ── Publish helpers ───────────────────────────────────────────
void publishStatus(bool motionDetected) {
    JsonDocument doc;
    doc["serial_number"]   = SERIAL_NUMBER;
    doc["device_type"]     = DEVICE_TYPE;
    doc["status"]          = "online";
    doc["motion_detected"] = motionDetected;

    char buf[256];
    serializeJson(doc, buf);
    mqttClient.publish(TOPIC_STATUS, buf, true);   // retained
}

void publishTelemetry(const char* event, bool motionDetected, int pirState,
                      unsigned long noMotionSeconds) {
    JsonDocument doc;
    doc["serial_number"] = SERIAL_NUMBER;
    doc["device_type"]   = DEVICE_TYPE;

    JsonObject data = doc["data"].to<JsonObject>();
    data["event"]                    = event;
    data["motion_detected"]          = motionDetected;
    data["pir_state"]                = pirState;
    data["no_motion_duration_seconds"] = (int)noMotionSeconds;
    data["status_color"]             = motionDetected ? "green" : "red";
    data["source"]                   = "sensor";
    data["success"]                  = true;
    data["error_message"]            = (char*)nullptr;  // null in JSON

    char buf[512];
    serializeJson(doc, buf);
    mqttClient.publish(TOPIC_TELEMETRY, buf);
    Serial.println("[MQTT] Telemetry published");
}

void publishAck(const char* commandId, const char* message) {
    JsonDocument doc;
    doc["command_id"] = commandId;
    doc["status"]     = "ok";
    doc["message"]    = message;

    char buf[128];
    serializeJson(doc, buf);
    mqttClient.publish(TOPIC_ACK, buf);
    Serial.println("[MQTT] ACK published");
}

// ── Setup ─────────────────────────────────────────────────────
void setup() {
    Serial.begin(115200);
    Serial.println("[BOOT] Starting MOTION-001");

    pinMode(PIR_PIN,   INPUT);
    pinMode(LED_VERDE, OUTPUT);
    pinMode(LED_ROJO,  OUTPUT);

    // Red LED on during calibration so the user sees the device is alive
    digitalWrite(LED_VERDE, LOW);
    digitalWrite(LED_ROJO,  HIGH);

    // 60-second PIR warm-up — blink red LED and print countdown every second
    Serial.println("[PIR] Waiting calibration...");
    for (int i = 30; i > 0; i--) {
        digitalWrite(LED_ROJO, (i % 2 == 0) ? HIGH : LOW);
        Serial.printf("[PIR] Calibrating... %d s remaining\n", i);
        delay(1000);
    }
    digitalWrite(LED_ROJO, LOW);
    Serial.println("[PIR] Ready");

    bool wifiOk = connectWiFi();

    mqttClient.setServer(MQTT_HOST, MQTT_PORT);
    mqttClient.setCallback(mqttCallback);
    mqttClient.setBufferSize(512);
    if (wifiOk) connectMQTT();

    // Initial status
    lastPirState = digitalRead(PIR_PIN) == HIGH;
    if (mqttClient.connected()) {
        publishStatus(lastPirState);
    }
    lastStatusMs = millis();
}

// ── Loop ──────────────────────────────────────────────────────
void loop() {
    // Retry MQTT every 5 s — non-blocking so LEDs keep working
    if (!mqttClient.connected() && millis() - lastMqttRetryMs >= 5000UL) {
        connectMQTT();
        lastMqttRetryMs = millis();
    }
    if (mqttClient.connected()) mqttClient.loop();

    bool pirHigh = (digitalRead(PIR_PIN) == HIGH);

    // ── LED control ─────────────────────────────────────────
    if (pirHigh) {
        digitalWrite(LED_VERDE, HIGH);
        digitalWrite(LED_ROJO,  LOW);
    } else {
        digitalWrite(LED_VERDE, LOW);
        digitalWrite(LED_ROJO,  HIGH);
    }

    Serial.printf("[PIR] state=%s\n", pirHigh ? "HIGH (motion)" : "LOW (no motion)");

    // ── Motion logic ─────────────────────────────────────────
    if (monitoringEnabled) {

        if (pirHigh) {
            // Motion present —————————————————————————————————

            if (noMotionAlertSent) {
                // Recovery: motion returned after a confirmed 60-s no-motion period
                Serial.println("[PIR] Motion resumed, publishing recovery telemetry");
                if (mqttClient.connected()) publishTelemetry("motion_resumed", true, 1, 0);
                noMotionAlertSent = false;
            }

            // Reset no-motion timer whenever motion is present
            noMotionStartMs = 0;

        } else {
            // No motion ——————————————————————————————————————

            if (!noMotionAlertSent) {
                if (noMotionStartMs == 0) {
                    // PIR just went LOW — start the timer
                    noMotionStartMs = millis();
                    Serial.println("[PIR] No motion timer started");
                } else {
                    unsigned long elapsed = millis() - noMotionStartMs;
                    if (elapsed >= noMotionThresholdMs) {
                        // 60 continuous seconds of no motion
                        Serial.printf("[PIR] No motion for %lu s, publishing alert telemetry\n", noMotionThresholdMs / 1000);
                        if (mqttClient.connected()) publishTelemetry("no_motion_1_minute", false, 0, 60);
                        noMotionAlertSent = true;
                        // Keep noMotionStartMs as-is (timer already expired; no repeat)
                    }
                }
            }
            // If noMotionAlertSent == true, do nothing — wait for motion to resume
        }

        lastPirState = pirHigh;
    }

    // ── Heartbeat status every 10 s ──────────────────────────
    if (mqttClient.connected() && millis() - lastStatusMs >= STATUS_INTERVAL_MS) {
        publishStatus(lastPirState);
        lastStatusMs = millis();
    }

    delay(200);   // ~5 Hz polling — smooth LED response without spamming Serial
}
