/*
  compuerta_proyecto.ino
  SmartPetHome — Automatic Access Door prototype
  Serial number : DOOR-001
  Device type   : automatic_access_door

  Base logic: original working sketch (servo + LEDs).
  Added layer : WiFi + MQTT to broker.emqx.io:1883.
  Serial Monitor is debug only — not the communication protocol.

  Topics
  ------
  Publish   : smartpethome/devices/DOOR-001/telemetry  (every 2 s)
  Publish   : smartpethome/devices/DOOR-001/status     (every 10 s)
  Publish   : smartpethome/devices/DOOR-001/ack        (on command)
  Subscribe : smartpethome/devices/DOOR-001/command
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
#define CLIENT_ID  "door-001-esp32"

// ── Topics ────────────────────────────────────────────────────
#define TOPIC_TELEMETRY  "smartpethome/devices/DOOR-001/telemetry"
#define TOPIC_STATUS     "smartpethome/devices/DOOR-001/status"
#define TOPIC_COMMAND    "smartpethome/devices/DOOR-001/command"
#define TOPIC_ACK        "smartpethome/devices/DOOR-001/ack"

// ── Original pinout (unchanged) ───────────────────────────────
#define PIN_SERVO  27
#define LED_ROJO   25
#define LED_AZUL   26

// ── Timing ────────────────────────────────────────────────────
#define TELEMETRY_INTERVAL_MS  2000UL
#define STATUS_INTERVAL_MS     10000UL

// ─────────────────────────────────────────────────────────────

WiFiClient   wifiClient;
PubSubClient mqttClient(wifiClient);
Servo        compuerta;

unsigned long lastTelemetryMs = 0;
unsigned long lastStatusMs    = 0;

bool abierta = false;

// ─────────────────────────────────────────────────────────────
// ORIGINAL DOOR LOGIC — unchanged
// ─────────────────────────────────────────────────────────────

void abrirCompuerta() {
  compuerta.write(180);
  digitalWrite(LED_ROJO, HIGH);
  digitalWrite(LED_AZUL, LOW);
  abierta = true;
  Serial.println("Compuerta abierta - LED rojo encendido");
}

void cerrarCompuerta() {
  compuerta.write(0);
  digitalWrite(LED_ROJO, LOW);
  digitalWrite(LED_AZUL, HIGH);
  abierta = false;
  Serial.println("Compuerta cerrada - LED azul encendido");
}

// ─────────────────────────────────────────────────────────────
// MQTT PUBLISH HELPERS
// ─────────────────────────────────────────────────────────────

// source must be one the backend accepts: "manual", "scheduled", "sensor"
// "serial" and "app" commands both count as "manual"; periodic heartbeat uses "sensor"
void publishTelemetry(const char* action, const char* source) {
  StaticJsonDocument<384> doc;
  doc["serial_number"] = "DOOR-001";
  doc["device_type"]   = "automatic_access_door";

  // Map ESP-side source labels to DB-valid values
  const char* dbSource = "manual";
  if (strcmp(source, "heartbeat") == 0) dbSource = "sensor";
  // "serial" and "app" both map to "manual" (default above)

  JsonObject data = doc.createNestedObject("data");
  data["action"]        = action;
  data["source"]        = dbSource;
  data["success"]       = true;
  data["door_state"]    = abierta ? "open" : "closed";
  data["error_message"] = (char*)nullptr;

  char buf[384];
  serializeJson(doc, buf);
  mqttClient.publish(TOPIC_TELEMETRY, buf, false);
  Serial.printf("[MQTT] telemetry action=%s source=%s door=%s\n",
                action, dbSource, abierta ? "open" : "closed");
}

void publishStatus() {
  StaticJsonDocument<192> doc;
  doc["serial_number"] = "DOOR-001";
  doc["device_type"]   = "automatic_access_door";
  doc["status"]        = "online";
  doc["door_state"]    = abierta ? "open" : "closed";

  char buf[192];
  serializeJson(doc, buf);
  mqttClient.publish(TOPIC_STATUS, buf, false);
  Serial.printf("[MQTT] status online door=%s\n", abierta ? "open" : "closed");
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
  Serial.printf("[CMD] received: %s\n", command);

  if (strcmp(command, "open_door") == 0) {
    abrirCompuerta();
    publishTelemetry("open", "app");
    publishStatus();
    publishAck(commandId, "ok", "Door opened");

  } else if (strcmp(command, "close_door") == 0) {
    cerrarCompuerta();
    publishTelemetry("close", "app");
    publishStatus();
    publishAck(commandId, "ok", "Door closed");

  } else if (strcmp(command, "get_status") == 0) {
    publishStatus();
    publishTelemetry(abierta ? "open" : "close", "app");
    publishAck(commandId, "ok", "Status sent");

  } else if (strcmp(command, "enable_manual_control") == 0) {
    publishAck(commandId, "ok", "Manual control enabled");

  } else if (strcmp(command, "disable_manual_control") == 0) {
    publishAck(commandId, "ok", "Manual control disabled");

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
  mqttClient.setBufferSize(512);
  mqttClient.setServer(MQTT_HOST, MQTT_PORT);
  mqttClient.setCallback(mqttCallback);

  while (!mqttClient.connected()) {
    Serial.printf("[MQTT] Conectando a %s...", MQTT_HOST);
    if (mqttClient.connect(CLIENT_ID)) {
      Serial.println(" conectado.");
      mqttClient.subscribe(TOPIC_COMMAND, 1);
      Serial.println("[MQTT] Suscrito a " TOPIC_COMMAND);
      publishStatus();
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

  pinMode(LED_ROJO, OUTPUT);
  pinMode(LED_AZUL, OUTPUT);

  compuerta.attach(PIN_SERVO, 500, 2400);

  cerrarCompuerta();   // closed on boot

  Serial.println("Sistema listo.");
  Serial.println("Escriba:");
  Serial.println("a = abrir compuerta");
  Serial.println("c = cerrar compuerta");
  Serial.println("t = alternar");

  connectWifi();
  connectMqtt();

  publishTelemetry("close", "heartbeat");
  Serial.println("[BOOT] DOOR-001 listo.");
}

// ─────────────────────────────────────────────────────────────
// LOOP
// ─────────────────────────────────────────────────────────────

void loop() {
  // WiFi reconnect
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[WiFi] Reconectando...");
    connectWifi();
  }

  // MQTT reconnect
  if (!mqttClient.connected()) {
    connectMqtt();
  }
  mqttClient.loop();

  // Serial commands (unchanged)
  if (Serial.available() > 0) {
    char comando = Serial.read();

    if (comando == 'a') {
      abrirCompuerta();
      publishTelemetry("open", "serial");
      publishStatus();
    }

    if (comando == 'c') {
      cerrarCompuerta();
      publishTelemetry("close", "serial");
      publishStatus();
    }

    if (comando == 't') {
      if (abierta) {
        cerrarCompuerta();
        publishTelemetry("close", "serial");
      } else {
        abrirCompuerta();
        publishTelemetry("open", "serial");
      }
      publishStatus();
    }
  }

  unsigned long now = millis();

  if (now - lastTelemetryMs >= TELEMETRY_INTERVAL_MS) {
    lastTelemetryMs = now;
    publishTelemetry(abierta ? "open" : "close", "heartbeat");
  }

  if (now - lastStatusMs >= STATUS_INTERVAL_MS) {
    lastStatusMs = now;
    publishStatus();
  }
}
