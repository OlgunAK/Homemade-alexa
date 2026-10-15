// Bu dosyayı aynı klasöre "config.h" adıyla kopyalayıp düzenleyin.
#pragma once

// --- Wi-Fi ---
#define WIFI_SSID      "EvWifiAdi"
#define WIFI_PASSWORD  "WifiSifresi"

// --- Laptop (python -m kidbot çalışan bilgisayar) ---
// IP adresi ("192.168.1.20") ya da bilgisayar adı + ".local" ("benim-laptop.local")
#define SERVER_HOST    "192.168.1.20"
#define SERVER_PORT    8765
// config.yaml -> hardware.device_token ile aynı olmalı
#define DEVICE_TOKEN   "degistir-beni"

// --- Pinler (ESP32-S3 DevKit için; başka kartta değiştirin) ---
// INMP441 mikrofon
#define MIC_SCK   4
#define MIC_WS    5
#define MIC_SD    6
// MAX98357A amfi
#define SPK_BCLK  15
#define SPK_LRC   16
#define SPK_DIN   7
// Buton (diğer ucu GND) ve LED (220 ohm direnç ile)
#define BUTTON_PIN 2
#define LED_PIN    21

// Ses seviyesi (0-100)
#define VOLUME     70
// Mikrofon kazancı: 32-bit örnekten 16-bit'e kaydırma. Küçük sayı = daha yüksek ses.
#define MIC_SHIFT  14
