/*
  feeder_001.ino
  SmartPetHome — Automatic Feeder prototype
  Serial number : FEEDER-001
  Device type   : automatic_feeder

  Base logic: original working sketch (servo + potentiometer + LEDs).
  Added layer : WiFi + MQTT to broker.emqx.io:1883.
  Serial Monitor is debug only — not the communication protocol.

  Topics
  ------
  Publish   : smartpethome/devices/FEEDER-001/telemetry  (every 1 s)
  Publish   : smartpethome/devices/FEEDER-001/status     (every 10 s)
  Publish   : smartpethome/devices/FEEDER-001/ack        (on command)
  Subscribe : smartpethome/devices/FEEDER-001/command
*/

#include <WiFi.h>
#include <PubSubClient.h>
#include <ESP32Servo.h>
#include <ArduinoJson.h>

// ── WiFi ──────────────────────────────────────────────────────
#define WIFI_SSID  "Familia Jiménez Wilhelm 2.4Ghz"
#define WIFI_PASS  "Wilhelm25"

// ── MQTT ──────────────────────────────────────────────────────
#define MQTT_HOST  "broker.emqx.io"
#define MQTT_PORT  1883
#define CLIENT_ID  "feeder-001-esp32"

// ── Topics ────────────────────────────────────────────────────
#define TOPIC_TELEMETRY  "smartpethome/devices/FEEDER-001/telemetry"
#define TOPIC_STATUS     "smartpethome/devices/FEEDER-001/status"
#define TOPIC_COMMAND    "smartpethome/devices/FEEDER-001/command"
#define TOPIC_ACK        "smartpethome/devices/FEEDER-001/ack"

// ── Original pinout (unchanged) ───────────────────────────────
#define PIN_SERVO  27
#define PIN_PESO   34
#define LED_ROJO   25
#define LED_VERDE  26

// ── Original threshold (unchanged) ───────────────────────────
int umbralPeso = 1800;

// ── Timing ────────────────────────────────────────────────────
#define SENSOR_INTERVAL_MS     500UL    // original delay(500)
#define TELEMETRY_INTERVAL_MS  1000UL
#define STATUS_INTERVAL_MS     10000UL
#define DISPENSE_MS            2000UL   // dispense_food command

// ─────────────────────────────────────────────────────────────

WiFiClient   wifiClient;
PubSubClient mqttClient(wifiClient);
Servo        compuerta;

unsigned long lastSensorMs    = 0;
unsigned long lastTelemetryMs = 0;
unsigned long lastStatusMs    = 0;

// Shared state written by sensor cycle, read by telemetry publisher
int  pesoSimulado = 0;
bool lowFood      = false;

// ─────────────────────────────────────────────────────────────
// ORIGINAL SENSOR LOGIC — runs every 500 ms, exactly as before
// ─────────────────────────────────────────────────────────────

void runSensorCycle() {
  pesoSimulado = analogRead(PIN_PESO);
  lowFood      = (pesoSimulado < umbralPeso);

  Serial.print("Peso simulado: ");
  Serial.println(pesoSimulado);

  if (pesoSimulado < umbralPeso) {
    digitalWrite(LED_ROJO,  HIGH);
    digitalWrite(LED_VERDE, LOW);
    compuerta.write(360);
    Serial.println("Estado: BAJO - Abriendo compuerta");
  } else {
    digitalWrite(LED_ROJO,  LOW);
    digitalWrite(LED_VERDE, HIGH);
    compuerta.write(0);
    Serial.println("Estado: OK - Compuerta cerrada");
  }
}

// ─────────────────────────────────────────────────────────────
// MQTT PUBLISH HELPERS
// ─────────────────────────────────────────────────────────────

void publishTelemetry() {
  StaticJsonDocument<384> doc;
  doc["serial_number"] = "FEEDER-001";
  doc["device_type"]   = "automatic_feeder";

  JsonObject data = doc.createNestedObject("data");
  data["bowl_weight_grams"]    = pesoSimulado;
  data["food_remaining_grams"] = pesoSimulado;
  data["dispensed_grams"]      = 0;
  data["consumed_grams"]       = 0;
  data["leftover_grams"]       = 0;
  data["status_color"]         = lowFood ? "red" : "green";
  data["low_food"]             = lowFood;
  data["pet_underfed"]         = lowFood;

  char buf[384];
  serializeJson(doc, buf);
  mqttClient.publish(TOPIC_TELEMETRY, buf, false);
  Serial.printf("[MQTT] telemetry peso=%d low_food=%s\n",
                pesoSimulado, lowFood ? "true" : "false");
}

void publishStatus(const char* statusStr) {
  StaticJsonDocument<128> doc;
  doc["serial_number"] = "FEEDER-001";
  doc["status"]        = statusStr;

  char buf[128];
  serializeJson(doc, buf);
  mqttClient.publish(TOPIC_STATUS, buf, false);
  Serial.printf("[MQTT] status → %s\n", statusStr);
}

void publishAck(const char* commandId, const char* status, const char* message) {
  StaticJsonDocument<256> doc;
  doc["command_id"] = commandId;
  doc["status"]     = status;
  doc["message"]    = message;

  char buf[256];
  serializeJson(doc, buf);
  mqttClient.publish(TOPIC_ACK, buf, false);
  Serial.printf("[MQTT] ack id=%s status=%s msg=%s\n", commandId, status, message);
}

// ─────────────────────────────────────────────────────────────
// COMMAND HANDLER
// ─────────────────────────────────────────────────────────────

void handleCommand(const char* payload, unsigned int length) {
  StaticJsonDocument<256> doc;
  DeserializationError err = deserializeJson(doc, payload, length);
  if (err) {
    Serial.printf("[CMD] JSON error: %s\n", err.c_str());
    return;
  }

  const char* command   = doc["command"]    | "unknown";
  const char* commandId = doc["command_id"] | "no-id";
  Serial.printf("[CMD] %s\n", command);

  if (strcmp(command, "dispense_food") == 0) {
    compuerta.write(170);
    delay(DISPENSE_MS);
    compuerta.write(0);
    runSensorCycle();          // restore LEDs/servo to sensor state
    publishTelemetry();
    publishAck(commandId, "ok", "Food dispensed");

  } else if (strcmp(command, "get_status") == 0) {
    runSensorCycle();
    publishStatus("online");
    publishTelemetry();
    publishAck(commandId, "ok", "Status sent");

  } else if (strcmp(command, "tare_scale") == 0) {
    publishAck(commandId, "ok", "Tare acknowledged");

  } else if (strcmp(command, "calibrate_scale") == 0) {
    publishAck(commandId, "ok", "Calibrate acknowledged");

  } else if (strcmp(command, "set_feeding_mode") == 0) {
    publishAck(commandId, "ok", "Feeding mode acknowledged");

  } else if (strcmp(command, "sync_schedules") == 0) {
    publishAck(commandId, "ok", "Schedules acknowledged");

  } else {
    char msg[64];
    snprintf(msg, sizeof(msg), "Unknown command: %s", command);
    publishAck(commandId, "error", msg);
  }
}

void mqttCallback(char* topic, byte* payload, unsigned int length) {
  if (strcmp(topic, TOPIC_COMMAND) == 0) {
    handleCommand((const char*)payload, length);
  }
}

// ─────────────────────────────────────────────────────────────
// WIFI + MQTT CONNECTION
// ─────────────────────────────────────────────────────────────

void connectWifi() {
  Serial.printf("[WiFi] Conectando a %s", WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.printf("\n[WiFi] Conectado. IP: %s\n", WiFi.localIP().toString().c_str());
}

void connectMqtt() {
  mqttClient.setBufferSize(512);   // default 256 is too small for nested telemetry payload (~286 bytes)
  mqttClient.setServer(MQTT_HOST, MQTT_PORT);
  mqttClient.setCallback(mqttCallback);

  while (!mqttClient.connected()) {
    Serial.printf("[MQTT] Conectando a %s...", MQTT_HOST);
    if (mqttClient.connect(CLIENT_ID)) {
      Serial.println(" conectado.");
      mqttClient.subscribe(TOPIC_COMMAND, 1);
      Serial.println("[MQTT] Suscrito a " TOPIC_COMMAND);
      publishStatus("online");
    } else {
      Serial.printf(" fallo rc=%d, reintentando en 3s...\n", mqttClient.state());
      delay(3000);
    }
  }
}

// ─────────────────────────────────────────────────────────────
// SETUP
// ─────────────────────────────────────────────────────────────

void setup() {
  Serial.begin(115200);

  pinMode(LED_ROJO,  OUTPUT);
  pinMode(LED_VERDE, OUTPUT);

  compuerta.attach(PIN_SERVO);
  compuerta.write(0);   // cerrado al inicio

  connectWifi();
  connectMqtt();

  runSensorCycle();     // initial read before first publish
  Serial.println("[BOOT] FEEDER-001 listo.");
}

// ─────────────────────────────────────────────────────────────
// LOOP
// delay(500) replaced with millis() so mqttClient.loop() is
// never starved. Sensor cadence is identical: every 500 ms.
// ─────────────────────────────────────────────────────────────

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[WiFi] Reconectando...");
    connectWifi();
  }
  if (!mqttClient.connected()) {
    connectMqtt();
  }
  mqttClient.loop();

  unsigned long now = millis();

  if (now - lastSensorMs >= SENSOR_INTERVAL_MS) {
    lastSensorMs = now;
    runSensorCycle();
  }

  if (now - lastTelemetryMs >= TELEMETRY_INTERVAL_MS) {
    lastTelemetryMs = now;
    publishTelemetry();
  }

  if (now - lastStatusMs >= STATUS_INTERVAL_MS) {
    lastStatusMs = now;
    publishStatus("online");
  }
}