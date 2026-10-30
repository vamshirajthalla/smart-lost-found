/*
 * Campus Lost & Found Smart Box — ESP32 firmware
 * ------------------------------------------------
 * Hardware:
 *   - ESP32 dev board
 *   - MFRC522 RFID reader (SPI)
 *   - SSD1306 128x64 OLED (I2C)
 *
 * Behavior:
 *   1. On boot, connect to Wi-Fi, then to AWS IoT Core over MQTT/TLS.
 *   2. When a tag is scanned, publish {tagId, boxId, ts} to
 *      lostfound/<boxId>/scan
 *   3. The cloud side (Lambda) decides whether this is a check-in or
 *      check-out (it's the single source of truth for item state) and
 *      publishes the result back to lostfound/<boxId>/status, which this
 *      device is subscribed to. The OLED updates when that arrives.
 *
 * Wiring (typical ESP32 devkit):
 *   MFRC522   ESP32
 *   SDA(SS)   GPIO5
 *   SCK       GPIO18
 *   MOSI      GPIO23
 *   MISO      GPIO19
 *   RST       GPIO4
 *   3.3V/GND  3.3V/GND
 *
 *   SSD1306 (I2C)  ESP32
 *   SDA            GPIO21
 *   SCL            GPIO22
 *   3.3V/GND       3.3V/GND
 *
 * Required libraries (install via Arduino Library Manager):
 *   - MFRC522 (miguelbalboa/rfid)
 *   - Adafruit SSD1306 + Adafruit GFX
 *   - PubSubClient (knolleary)
 *   - ArduinoJson (bblanchon)
 */

#include <SPI.h>
#include <MFRC522.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

#include "secrets.h"   // Wi-Fi + AWS IoT credentials, see secrets_template.h

// ---------- Pin config ----------
#define RFID_SS_PIN   5
#define RFID_RST_PIN  4
#define OLED_WIDTH    128
#define OLED_HEIGHT   64
#define OLED_RESET    -1

// ---------- Device identity ----------
// Each physical box gets a unique boxId. Used in MQTT topics so many
// boxes can share one AWS account / one set of Lambda functions.
const char* BOX_ID = "box-01";

MFRC522 rfid(RFID_SS_PIN, RFID_RST_PIN);
Adafruit_SSD1306 display(OLED_WIDTH, OLED_HEIGHT, &Wire, OLED_RESET);

WiFiClientSecure net;
PubSubClient mqtt(net);

char scanTopic[64];
char statusTopic[64];

unsigned long lastReconnectAttempt = 0;

// ---------- OLED helpers ----------
void oledMessage(const String& line1, const String& line2 = "", const String& line3 = "") {
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, 0);
  display.println(line1);
  if (line2.length()) display.println(line2);
  if (line3.length()) display.println(line3);
  display.display();
}

// ---------- Wi-Fi ----------
void connectWiFi() {
  oledMessage("Wi-Fi", "connecting...");
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    delay(400);
  }
  oledMessage("Wi-Fi", "connected", WiFi.localIP().toString());
  delay(800);
}

// ---------- MQTT message handler (status updates from Lambda) ----------
void onMqttMessage(char* topic, byte* payload, unsigned int length) {
  StaticJsonDocument<256> doc;
  DeserializationError err = deserializeJson(doc, payload, length);
  if (err) {
    oledMessage("Parse error", err.c_str());
    return;
  }

  const char* action = doc["action"] | "unknown";     // "checked_in" / "checked_out"
  const char* itemName = doc["itemName"] | "Unnamed item";
  const char* tagId = doc["itemId"] | "";

  String header = (String(action) == "checked_in") ? "CHECKED IN" : "CHECKED OUT";
  oledMessage(header, String("Item: ") + itemName, String("Tag: ") + tagId);
}

// ---------- MQTT connect ----------
bool connectMqtt() {
  net.setCACert(AWS_ROOT_CA1);
  net.setCertificate(AWS_CERT_CRT);
  net.setPrivateKey(AWS_CERT_PRIVATE);

  mqtt.setServer(AWS_IOT_ENDPOINT, 8883);
  mqtt.setCallback(onMqttMessage);

  oledMessage("AWS IoT Core", "connecting...");
  String clientId = String("smartbox-") + BOX_ID;
  if (mqtt.connect(clientId.c_str())) {
    mqtt.subscribe(statusTopic);
    oledMessage("AWS IoT Core", "connected");
    delay(500);
    return true;
  }
  oledMessage("AWS IoT Core", "connect failed", String("rc=") + mqtt.state());
  return false;
}

// ---------- Publish a scan event ----------
void publishScan(const String& tagId) {
  StaticJsonDocument<256> doc;
  doc["itemId"] = tagId;
  doc["boxId"] = BOX_ID;
  doc["ts"] = (uint32_t)(millis() / 1000); // device-relative; Lambda stamps wall-clock time too

  char buf[256];
  size_t n = serializeJson(doc, buf);
  mqtt.publish(scanTopic, buf, n);
  oledMessage("Tag scanned", tagId, "Sending...");
}

String uidToString(MFRC522::Uid uid) {
  String s;
  for (byte i = 0; i < uid.size; i++) {
    if (uid.uidByte[i] < 0x10) s += "0";
    s += String(uid.uidByte[i], HEX);
  }
  s.toUpperCase();
  return s;
}

void setup() {
  Serial.begin(115200);
  Wire.begin();
  SPI.begin();

  snprintf(scanTopic, sizeof(scanTopic), "lostfound/%s/scan", BOX_ID);
  snprintf(statusTopic, sizeof(statusTopic), "lostfound/%s/status", BOX_ID);

  if (!display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    Serial.println("OLED init failed");
  }
  oledMessage("Campus Lost&Found", "Booting...");

  rfid.PCD_Init();

  connectWiFi();
  connectMqtt();

  oledMessage("Ready", "Scan an item tag");
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    connectWiFi();
  }

  if (!mqtt.connected()) {
    unsigned long now = millis();
    if (now - lastReconnectAttempt > 5000) {
      lastReconnectAttempt = now;
      if (connectMqtt()) {
        lastReconnectAttempt = 0;
        oledMessage("Ready", "Scan an item tag");
      }
    }
  } else {
    mqtt.loop();
  }

  // Poll for a new RFID tag
  if (rfid.PICC_IsNewCardPresent() && rfid.PICC_ReadCardSerial()) {
    String tagId = uidToString(rfid.uid);
    publishScan(tagId);
    rfid.PICC_HaltA();
    rfid.PCD_StopCrypto1();
    delay(1500); // debounce so one tap doesn't fire multiple scans
  }
}
