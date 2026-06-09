// Sistema de control climatico con DHT22 + ventilador
// Ahora con integración MQTT según guía SmartPetHome

#include <Arduino.h>
#include <DHT.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

#define DHTPIN 4
#define DHTTYPE DHT22

#define FAN_PIN 25

// Red y broker
#define WIFI_SSID  "Familia Jiménez Wilhelm 2.4Ghz"
#define WIFI_PASS  "Wilhelm25"
#define MQTT_HOST  "broker.emqx.io"
#define MQTT_PORT  1883

// Identidad del dispositivo (ajustar serial si hace falta)
#define SERIAL_NUMBER "ENV-001"
#define CLIENT_ID      "env-ENV-001-esp32"
#define DEVICE_TYPE    "environmental_monitor"

// Topics
#define TOPIC_TELEMETRY  "smartpethome/devices/" SERIAL_NUMBER "/telemetry"
#define TOPIC_STATUS     "smartpethome/devices/" SERIAL_NUMBER "/status"
#define TOPIC_COMMAND    "smartpethome/devices/" SERIAL_NUMBER "/command"
#define TOPIC_ACK        "smartpethome/devices/" SERIAL_NUMBER "/ack"

// Intervalos
#define SENSOR_INTERVAL_MS     2000UL
#define TELEMETRY_INTERVAL_MS  2000UL
#define STATUS_INTERVAL_MS     10000UL

DHT dht(DHTPIN, DHTTYPE);

WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);

unsigned long lastSensorMs = 0;
unsigned long lastTelemetryMs = 0;
unsigned long lastStatusMs = 0;

// Estado y umbrales
float temperaturaActual = 0.0;
float humedadActual = 0.0;
float minTemp = 18.0;
float maxTemp = 28.0;
bool autoControl = true;
bool actuatorAutoTriggered = false;
bool manualControl = false;

void publishTelemetry() {
    StaticJsonDocument<384> doc;
    doc["serial_number"] = SERIAL_NUMBER;
    doc["device_type"] = DEVICE_TYPE;

    JsonObject data = doc.createNestedObject("data");
    data["temperature"] = temperaturaActual;
    data["humidity"] = humedadActual;
    data["actuator_triggered"] = actuatorAutoTriggered;
    if (temperaturaActual < minTemp) data["status"] = "too_low";
    else if (temperaturaActual > maxTemp) data["status"] = "too_high";
    else data["status"] = "normal";
    data["actuator_state"] = actuatorAutoTriggered ? "on" : "off";
    data["min_temperature"] = minTemp;
    data["max_temperature"] = maxTemp;

    char buf[384];
    serializeJson(doc, buf);
    mqttClient.publish(TOPIC_TELEMETRY, buf, false);
    Serial.printf("[MQTT] telemetry temp=%.2f hum=%.2f status=%s\n",
                    temperaturaActual, humedadActual, 
                    (temperaturaActual < minTemp) ? "too_low" : (temperaturaActual > maxTemp) ? "too_high" : "normal");
}

void publishStatus(const char* statusStr) {

    StaticJsonDocument<128> doc;
    doc["serial_number"] = SERIAL_NUMBER;
    doc["status"] = statusStr;

    char buf[128];
    serializeJson(doc, buf);
    mqttClient.publish(TOPIC_STATUS, buf, false);
    Serial.printf("[MQTT] status → %s\n", statusStr);
}

void publishAck(const char* commandId, const char* status, const char* message) {
    StaticJsonDocument<256> doc;
    doc["command_id"] = commandId;
    doc["status"] = status;
    doc["message"] = message;

    char buf[256];
    serializeJson(doc, buf);
    mqttClient.publish(TOPIC_ACK, buf, false);
    Serial.printf("[MQTT] ack id=%s status=%s msg=%s\n", commandId, status, message);
}

void runSensorCycle() {
    temperaturaActual = dht.readTemperature();
    humedadActual = dht.readHumidity();

    if (isnan(temperaturaActual) || isnan(humedadActual)) {
        Serial.println("Error leyendo DHT22");
        return;
    }

    Serial.printf("Temperatura: %.2f °C | Humedad: %.2f %%\n", temperaturaActual, humedadActual);

    // Si hay control manual activado, no cambiar el estado aquí
    if (manualControl) {
        Serial.println("Control manual activo: no cambiar ventilador desde sensor");
        return;
    }

    // Control automático: activar ventilador si supera max o está por debajo de min
    if (autoControl && (temperaturaActual > maxTemp || temperaturaActual < minTemp)) {
        digitalWrite(FAN_PIN, HIGH);
        actuatorAutoTriggered = true;
        Serial.println("Ventilador ENCENDIDO por control automático");
    } else {
        digitalWrite(FAN_PIN, LOW);
        actuatorAutoTriggered = false;
        Serial.println("Ventilador APAGADO");
    }
}

void handleCommand(const char* payload, unsigned int length) {
    StaticJsonDocument<256> doc;
    DeserializationError err = deserializeJson(doc, payload, length);
    if (err) {
        Serial.printf("[CMD] JSON error: %s\n", err.c_str());
        return;
    }

    const char* command = doc["command"] | "unknown";
    const char* commandId = doc["command_id"] | "no-id";
    Serial.printf("[CMD] %s (id=%s)\n", command, commandId);

    // set_temperature_range: params {min_temperature, max_temperature}
    if (strcmp(command, "set_temperature_range") == 0) {
        if (doc.containsKey("params") && doc["params"].containsKey("min_temperature") && 
            doc["params"].containsKey("max_temperature")) {
            float newMin = doc["params"]["min_temperature"].as<float>();
            float newMax = doc["params"]["max_temperature"].as<float>();
            if (newMin < newMax) {
                minTemp = newMin;
                maxTemp = newMax;
                publishAck(commandId, "ok", "Temperature range updated");
            } else {
                publishAck(commandId, "error", "min_temperature must be less than max_temperature");
            }
        } else {
            publishAck(commandId, "error", "missing params.min_temperature or params.max_temperature");
        }

    // turn_actuator_on: sin parámetros
    } else if (strcmp(command, "turn_actuator_on") == 0) {
        digitalWrite(FAN_PIN, HIGH);
        manualControl = true;
        actuatorAutoTriggered = true;
        publishAck(commandId, "ok", "Actuator turned on");

    // turn_actuator_off: sin parámetros
    } else if (strcmp(command, "turn_actuator_off") == 0) {
        digitalWrite(FAN_PIN, LOW);
        manualControl = true;
        actuatorAutoTriggered = false;
        publishAck(commandId, "ok", "Actuator turned off");

    // set_auto_control: params {enabled: true|false}
    } else if (strcmp(command, "set_auto_control") == 0) {
        if (doc.containsKey("params") && doc["params"].containsKey("enabled")) {
            bool enabled = false;
            // Aceptar tanto booleano como string "true" / "false"
            if (doc["params"]["enabled"].is<bool>()) {
                enabled = doc["params"]["enabled"].as<bool>();
            } else if (doc["params"]["enabled"].is<const char*>()) {
                const char* val = doc["params"]["enabled"].as<const char*>();
                enabled = (strcmp(val, "true") == 0);
            }
            autoControl = enabled;
            if (autoControl) manualControl = false; // permitir control automático si se activa
            char msg[64];
            snprintf(msg, sizeof(msg), "Auto control set to %s", autoControl ? "true" : "false");
            publishAck(commandId, "ok", msg);
        } else {
            publishAck(commandId, "error", "missing params.enabled");
        }

    // get_status: sin parámetros
    } else if (strcmp(command, "get_status") == 0) {
        runSensorCycle();
        publishStatus("online");
        publishTelemetry();
        publishAck(commandId, "ok", "Status sent");

    // Comando desconocido
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
            publishStatus("online");
        } else {
            Serial.printf(" fallo rc=%d, reintentando en 3s...\n", mqttClient.state());
            delay(3000);
        }
    }
}

void setup() {
    Serial.begin(115200);

    dht.begin();

    pinMode(FAN_PIN, OUTPUT);
    digitalWrite(FAN_PIN, LOW);

    delay(2000);

    connectWifi();
    connectMqtt();

    runSensorCycle();
    Serial.println("[BOOT] ENV-001 listo.");
}

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