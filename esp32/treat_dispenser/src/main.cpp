#include <Arduino.h>
#include <ESP32Servo.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>


//Configuración WiFi y MQTT
#define WIFI_SSID  "J ARIAS -2.4G"
#define WIFI_PASS  "Barra3126"

#define MQTT_HOST  "broker.emqx.io"
#define MQTT_PORT  1883

#define SERIAL_NUMBER "REW-001"
#define CLIENT_ID "reward-REW-001-esp32"

#define DEVICE_TYPE "reward_dispenser"

#define TOPIC_TELEMETRY  "smartpethome/devices/" SERIAL_NUMBER "/telemetry"
#define TOPIC_STATUS     "smartpethome/devices/" SERIAL_NUMBER "/status"
#define TOPIC_COMMAND    "smartpethome/devices/" SERIAL_NUMBER "/command"
#define TOPIC_ACK        "smartpethome/devices/" SERIAL_NUMBER "/ack"

Servo servoMotor;
WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);


// Botones
const int botones[4] = {14, 27, 17, 25};

// Buzzer y Servo
const int buzzerPin = 12;
const int servoPin = 26;

// Canal PWM para buzzer
const int buzzerChannel = 0;

int botonGanador;
int premiosEntregados = 0;
int maxPremios = 20;


//limite de premios a entregar
unsigned long ultimoIntento = 0;
unsigned long tiempoEsperaMs = 5000;

unsigned long lastTelemetryMs = 0;
unsigned long lastStatusMs = 0;

#define TELEMETRY_INTERVAL_MS 5000UL
#define STATUS_INTERVAL_MS 10000UL

void publishStatus(const char* statusStr) {

    StaticJsonDocument<128> doc;

    doc["serial_number"] = SERIAL_NUMBER;
    doc["status"] = statusStr;

    char buffer[128];

    serializeJson(doc, buffer);

    mqttClient.publish(TOPIC_STATUS, buffer);
}

void publishAck(
    const char* commandId,
    const char* status,
    const char* message) {

    StaticJsonDocument<256> doc;

    doc["command_id"] = commandId;
    doc["status"] = status;
    doc["message"] = message;

    char buffer[256];

    serializeJson(doc, buffer);

    mqttClient.publish(TOPIC_ACK, buffer);
}

void publishTelemetry() {

    StaticJsonDocument<256> doc;

    doc["serial_number"] = SERIAL_NUMBER;
    doc["device_type"] = DEVICE_TYPE;

    JsonObject data = doc.createNestedObject("data");

    data["rewards_given"] = premiosEntregados;
    data["max_rewards"] = maxPremios;
    data["cooldown_ms"] = tiempoEsperaMs;

    char buffer[256];

    serializeJson(doc, buffer);

    mqttClient.publish(TOPIC_TELEMETRY, buffer);

    Serial.println("[MQTT] Telemetry enviada");
}

void publishEvent(const char* eventName) {

    StaticJsonDocument<128> doc;

    doc["serial_number"] = SERIAL_NUMBER;
    doc["event"] = eventName;

    char buffer[128];

    serializeJson(doc, buffer);

    mqttClient.publish(TOPIC_TELEMETRY, buffer);
}

void connectWifi() {

    Serial.printf("[WiFi] Conectando a %s", WIFI_SSID);

    WiFi.begin(WIFI_SSID, WIFI_PASS);

    while (WiFi.status() != WL_CONNECTED) {

        delay(500);
        Serial.print(".");
    }

    Serial.println();
    Serial.println("[WiFi] Conectado");
}

void connectMqtt() {

    mqttClient.setServer(MQTT_HOST, MQTT_PORT);

    while (!mqttClient.connected()) {

        Serial.print("[MQTT] Conectando...");

        if (mqttClient.connect(CLIENT_ID)) {

            Serial.println(" OK");

            mqttClient.subscribe(TOPIC_COMMAND);

            publishStatus("online");

        } else {

            Serial.println(" fallo");

            delay(3000);
        }
    }
}

void handleCommand(const char* payload, unsigned int length) {

    StaticJsonDocument<256> doc;

    if (deserializeJson(doc, payload, length)) {
        return;
    }

    const char* command =
        doc["command"] | "";

    const char* commandId =
        doc["command_id"] | "unknown";

    if (strcmp(command, "set_reward_limit") == 0) {

        maxPremios =
            doc["params"]["max_rewards"] | maxPremios;

        publishAck(
            commandId,
            "ok",
            "Reward limit updated");
    }  else if (strcmp(command, "set_cooldown") == 0) {

        tiempoEsperaMs =
            doc["params"]["cooldown_ms"] | tiempoEsperaMs;

        publishAck(
            commandId,
            "ok",
            "Cooldown updated");
    } else if (strcmp(command, "reset_daily_limit") == 0) {

        premiosEntregados = 0;

        publishAck(
            commandId,
            "ok",
            "Counter reset");
    } else if (strcmp(command, "get_status") == 0) {

        publishStatus("online");
        publishTelemetry();

        publishAck(
            commandId,
            "ok",
            "Status sent");
    }
}  

void mqttCallback(char* topic, byte* payload, unsigned int length) {

    if (strcmp(topic, TOPIC_COMMAND) == 0) {

        handleCommand(
            (const char*)payload,
            length);
    }
}

void sonidoPremio() {

    ledcWriteTone(buzzerChannel, 1000);
    delay(150);

    ledcWriteTone(buzzerChannel, 1500);
    delay(150);

    ledcWriteTone(buzzerChannel, 0);
}

void sonidoInicio() {

    ledcWriteTone(buzzerChannel, 1000);
    delay(100);

    ledcWriteTone(buzzerChannel, 1500);
    delay(100);

    ledcWriteTone(buzzerChannel, 2000);
    delay(100);

    ledcWriteTone(buzzerChannel, 0);
}

void sonidoError() {

    ledcWriteTone(buzzerChannel, 300);
    delay(500);

    ledcWriteTone(buzzerChannel, 0);
}

void setup() {

    Serial.begin(115200);

    for (int i = 0; i < 4; i++) {
        pinMode(botones[i], INPUT_PULLUP);
    }

    // Configuración buzzer
    ledcSetup(buzzerChannel, 2000, 8);
    ledcAttachPin(buzzerPin, buzzerChannel);

    // Servo
    servoMotor.attach(servoPin);
    servoMotor.write(90);
    delay(1000);

    ledcWriteTone(buzzerChannel, 0);

    randomSeed(micros());

    botonGanador = random(0, 4);


    connectWifi();
    mqttClient.setCallback(mqttCallback);
    connectMqtt();

    Serial.println("Sistema iniciado");
    Serial.print("Boton ganador: ");
    Serial.println(botonGanador + 1);

    sonidoInicio();
}

void dispensarPremio() {

    sonidoPremio();

    servoMotor.attach(servoPin);
    servoMotor.write(0);
    delay(1000);

    premiosEntregados++;
    publishEvent("reward_dispensed");

    Serial.print("Premio entregado. Total: ");
    Serial.println(premiosEntregados);

    botonGanador = random(0, 4);

    Serial.print("Nuevo boton ganador: ");
    Serial.println(botonGanador + 1);

    servoMotor.write(90);
    delay(500);
    servoMotor.detach();

    ledcWriteTone(buzzerChannel, 0);
}

void loop() {

    if (WiFi.status() != WL_CONNECTED) {
        connectWifi();
    }

    if (!mqttClient.connected()) {
        connectMqtt();
    }

    mqttClient.loop();

    for (int i = 0; i < 4; i++) {

        if (digitalRead(botones[i]) == LOW) {

            delay(50); // debounce

            if (digitalRead(botones[i]) == LOW) {
                
                if (millis() - ultimoIntento < tiempoEsperaMs) {

                    Serial.println("Cooldown activo");

                    continue;
                }

                ultimoIntento = millis();

                Serial.print("Boton ");
                Serial.print(i + 1);
                Serial.println(" presionado");
                publishEvent("attempt");

                if (premiosEntregados >= maxPremios) {

                    Serial.println("Limite alcanzado");
                    publishEvent("limit_reached");
                    sonidoError();

                } else {

                    if (i == botonGanador) {

                        publishEvent("winner_button");
                        Serial.println("BOTON GANADOR");
                        dispensarPremio();

                    } else {

                        publishEvent("incorrect_button");
                        Serial.println("Boton incorrecto");
                        sonidoError();
                    }
                }

                while (digitalRead(botones[i]) == LOW) {
                    delay(10);
                }
            }
        }
    }

    unsigned long now = millis();

    if (now - lastTelemetryMs >= TELEMETRY_INTERVAL_MS) {

        lastTelemetryMs = now;

        publishTelemetry();
    }

    if (now - lastStatusMs >= STATUS_INTERVAL_MS) {

        lastStatusMs = now;

        publishStatus("online");
    }
}