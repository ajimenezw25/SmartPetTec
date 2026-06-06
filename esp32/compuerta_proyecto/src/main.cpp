#include <Arduino.h>
#include <ESP32Servo.h>

#define PIN_SERVO  14
#define LED_VERDE  13
#define LED_AZUL   27

Servo compuerta;
bool abierta = false;

void abrirCompuerta() {
  compuerta.write(180);
  digitalWrite(LED_VERDE, LOW);
  digitalWrite(LED_AZUL, HIGH);
  abierta = true;
  Serial.println(">> Compuerta ABIERTA");
}

void cerrarCompuerta() {
  compuerta.write(0);
  digitalWrite(LED_VERDE, HIGH);
  digitalWrite(LED_AZUL, LOW);
  abierta = false;
  Serial.println(">> Compuerta CERRADA");
}

void setup() {
  Serial.begin(115200);
  pinMode(LED_VERDE, OUTPUT);
  pinMode(LED_AZUL, OUTPUT);

  compuerta.setPeriodHertz(50);
  compuerta.attach(PIN_SERVO, 500, 2400);
  delay(100);

  cerrarCompuerta();

  Serial.println("=== Dispensador de Comida ===");
  Serial.println("Comandos: A = Abrir | C = Cerrar | ESTADO");
}

void loop() {
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    cmd.toUpperCase();

    if      (cmd == "A")      { abrirCompuerta(); }
    else if (cmd == "C")      { cerrarCompuerta(); }
    else if (cmd == "ESTADO") { Serial.printf("Estado: %s\n", abierta ? "ABIERTA" : "CERRADA"); }
    else                      { Serial.println("Comando no reconocido"); }
  }
}