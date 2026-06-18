#define PIR_PIN 27
#define LED_VERDE 25
#define LED_ROJO 26

void setup() {
  Serial.begin(115200);

  pinMode(PIR_PIN, INPUT);
  pinMode(LED_VERDE, OUTPUT);
  pinMode(LED_ROJO, OUTPUT);

  Serial.println("Esperando calibracion del PIR...");
  delay(60000);
  Serial.println("Listo");
}

void loop() {
  int estado = digitalRead(PIR_PIN);

  Serial.print("PIR = ");
  Serial.println(estado);

  if (estado == HIGH) {
    digitalWrite(LED_VERDE, HIGH);
    digitalWrite(LED_ROJO, LOW);
  } else {
    digitalWrite(LED_VERDE, LOW);
    digitalWrite(LED_ROJO, HIGH);
  }

  delay(500);
}