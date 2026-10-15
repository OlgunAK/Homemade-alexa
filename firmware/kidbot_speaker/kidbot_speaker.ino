// Bilge Wi-Fi hoparlör: ESP32-S3 + INMP441 mikrofon + MAX98357A amfi + buton.
//
// Cihaz sadece "kulak, ağız ve buton"dur. Laptopta çalışan `python -m kidbot`
// sunucusuna WebSocket ile bağlanır; protokol kidbot/remote.py dosyasında.
//
// Gerekenler (Arduino IDE):
//   - Kart: "esp32" by Espressif, sürüm 3.x  ->  "ESP32S3 Dev Module"
//   - Kütüphane: "WebSockets" by Markus Sattler (links2004)

#include <Arduino.h>
#include <WiFi.h>
#include <ESPmDNS.h>
#include <ESP_I2S.h>
#include <WebSocketsClient.h>
#include <freertos/stream_buffer.h>

#include "config.h"

static const uint32_t MIC_RATE = 16000;
static const uint32_t SPK_RATE = 24000;
static const size_t MIC_FRAME = 480;           // 30 ms @ 16 kHz
static const size_t PLAY_BUFFER = 64 * 1024;   // ~1.3 sn @ 24 kHz

I2SClass mic;
I2SClass spk;
WebSocketsClient ws;
StreamBufferHandle_t playBuf;

volatile bool listening = false;
volatile bool flushRequested = false;
int discardFrames = 0;

enum LedMode { LED_OFF, LED_ON, LED_BLINK };
LedMode ledMode = LED_OFF;

// ---------------------------------------------------------------- hoparlör
void playbackTask(void *) {
  static int16_t buf[512];
  for (;;) {
    if (flushRequested) {
      if (xStreamBufferReset(playBuf) == pdPASS) flushRequested = false;
    }
    size_t n = xStreamBufferReceive(playBuf, buf, sizeof(buf), pdMS_TO_TICKS(20));
    if (n == 0) {
      memset(buf, 0, sizeof(buf));  // boşta sessizlik çal (cızırtı olmasın)
      n = sizeof(buf);
    } else {
      for (size_t i = 0; i < n / 2; i++) buf[i] = (int32_t)buf[i] * VOLUME / 100;
    }
    spk.write((uint8_t *)buf, n);
  }
}

// ---------------------------------------------------------------- WebSocket
void handleText(const char *msg) {
  // Mesajlar küçük ve sabit; JSON kütüphanesine gerek yok.
  if (strstr(msg, "\"stop_listen\"")) {
    listening = false;
  } else if (strstr(msg, "\"listen\"")) {
    discardFrames = 3;  // mikrofon tamponundaki eski sesi at
    listening = true;
  } else if (strstr(msg, "\"flush\"")) {
    flushRequested = true;
  } else if (strstr(msg, "\"led\"")) {
    if (strstr(msg, "\"blink\"")) ledMode = LED_BLINK;
    else if (strstr(msg, "\"on\"")) ledMode = LED_ON;
    else ledMode = LED_OFF;
  }
}

void onWsEvent(WStype_t type, uint8_t *payload, size_t length) {
  switch (type) {
    case WStype_CONNECTED:
      Serial.println("Laptopa bağlandı");
      break;
    case WStype_DISCONNECTED:
      Serial.println("Bağlantı yok, tekrar denenecek...");
      listening = false;
      ledMode = LED_OFF;
      flushRequested = true;
      break;
    case WStype_TEXT: {
      char msg[128];
      size_t n = length < sizeof(msg) - 1 ? length : sizeof(msg) - 1;
      memcpy(msg, payload, n);
      msg[n] = 0;
      handleText(msg);
      break;
    }
    case WStype_BIN:
      if (!flushRequested) {
        xStreamBufferSend(playBuf, payload, length, pdMS_TO_TICKS(100));
      }
      break;
    default:
      break;
  }
}

// ---------------------------------------------------------------- mikrofon
void sendMicFrame() {
  static int32_t raw[MIC_FRAME];
  static int16_t pcm[MIC_FRAME];
  size_t got = mic.readBytes((char *)raw, sizeof(raw));
  size_t samples = got / sizeof(int32_t);
  if (samples == 0) return;
  if (discardFrames > 0) {
    discardFrames--;
    return;
  }
  for (size_t i = 0; i < samples; i++) {
    int32_t s = raw[i] >> MIC_SHIFT;  // INMP441: 24 bit veri, 32 bit çerçeve
    if (s > 32767) s = 32767;
    if (s < -32768) s = -32768;
    pcm[i] = (int16_t)s;
  }
  ws.sendBIN((uint8_t *)pcm, samples * sizeof(int16_t));
}

// ---------------------------------------------------------------- buton ve LED
void checkButton() {
  static bool lastPressed = false;
  static uint32_t lastChange = 0;
  bool pressed = digitalRead(BUTTON_PIN) == LOW;
  if (pressed != lastPressed && millis() - lastChange > 50) {
    lastChange = millis();
    lastPressed = pressed;
    if (pressed) {
      Serial.println("Buton");
      flushRequested = true;  // konuşuyorsa hemen sus
      ws.sendTXT("{\"type\":\"button\"}");
    }
  }
}

void updateLed() {
  bool on = ledMode == LED_ON || (ledMode == LED_BLINK && (millis() / 300) % 2 == 0);
  digitalWrite(LED_PIN, on ? HIGH : LOW);
}

// ---------------------------------------------------------------- kurulum
void connectWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);  // ses akışında gecikme olmasın
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Wi-Fi bağlanıyor");
  while (WiFi.status() != WL_CONNECTED) {
    digitalWrite(LED_PIN, !digitalRead(LED_PIN));
    delay(250);
    Serial.print(".");
  }
  digitalWrite(LED_PIN, LOW);
  Serial.printf("\nWi-Fi tamam, IP: %s\n", WiFi.localIP().toString().c_str());
}

void connectServer() {
  String host = SERVER_HOST;
  String url = String("/?token=") + DEVICE_TOKEN;
  if (host.endsWith(".local")) {
    MDNS.begin("bilge-hoparlor");
    IPAddress ip;
    while ((ip = MDNS.queryHost(host.substring(0, host.length() - 6))) == IPAddress()) {
      Serial.println("Laptop bulunamadı (mDNS), tekrar deneniyor...");
      delay(2000);
    }
    Serial.printf("Laptop: %s\n", ip.toString().c_str());
    ws.begin(ip, SERVER_PORT, url.c_str());
  } else {
    ws.begin(host, SERVER_PORT, url);
  }
  ws.onEvent(onWsEvent);
  ws.setReconnectInterval(2000);
}

void setup() {
  Serial.begin(115200);
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  pinMode(LED_PIN, OUTPUT);

  mic.setPins(MIC_SCK, MIC_WS, -1, MIC_SD);
  if (!mic.begin(I2S_MODE_STD, MIC_RATE, I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_MONO, I2S_STD_SLOT_LEFT)) {
    Serial.println("Mikrofon başlatılamadı! Kabloları kontrol edin.");
  }
  spk.setPins(SPK_BCLK, SPK_LRC, SPK_DIN);
  if (!spk.begin(I2S_MODE_STD, SPK_RATE, I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO)) {
    Serial.println("Hoparlör başlatılamadı! Kabloları kontrol edin.");
  }

  playBuf = xStreamBufferCreate(PLAY_BUFFER, 1);
  xTaskCreatePinnedToCore(playbackTask, "play", 4096, nullptr, 5, nullptr, 1);

  connectWifi();
  connectServer();
}

void loop() {
  ws.loop();
  checkButton();
  updateLed();
  if (listening) {
    sendMicFrame();  // ~30 ms bekler; ws.loop() arada çalışmaya devam eder
  } else {
    // Dinlemiyorken de mikrofonu oku ki tamponda eski ses birikmesin
    static int32_t sink[MIC_FRAME];
    mic.readBytes((char *)sink, sizeof(sink));
  }
}
