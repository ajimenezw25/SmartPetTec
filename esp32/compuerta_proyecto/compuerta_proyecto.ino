void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("ESP32 prueba minima OK");
}

void loop() {
  Serial.println("sigue vivo");
  delay(1000);
}