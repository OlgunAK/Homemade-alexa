# Ucuz ve ev yapımı donanım rehberi

Hedef: lehim gerektirmeyen ya da çok az lehim gerektiren, kolay bulunan parçalarla yapılmış, istenince değiştirilebilen bir "akıllı hoparlör".

> Fiyatlar yaklaşık dolar karşılığıdır ve satıcıya göre çok değişir. Almadan önce yerel elektronik mağazalarında ya da pazaryerlerinde güncel fiyata bakın.

## Seçenek 1: Önerilen (Raspberry Pi Zero 2 W + I2S ses), yaklaşık 40-55 $

Bu repodaki kod olduğu gibi çalışır.

| Parça | Görev | Yaklaşık fiyat |
|---|---|---|
| Raspberry Pi Zero 2 W (pin başlıklı "WH" modeli tercih edin) | Beyin, Wi-Fi | 15-20 $ |
| INMP441 I2S mikrofon modülü | Mikrofon | 2-4 $ |
| MAX98357A I2S amfi modülü | Hoparlör sürücüsü | 3-5 $ |
| 3 W 4 Ω küçük hoparlör (40-50 mm) | Ses | 2-4 $ |
| 30 mm arcade buton (büyük, renkli) | Aç/kapa | 1-2 $ |
| 5 mm LED + 220 Ω direnç (isteğe bağlı) | "Dinliyorum" ışığı | <1 $ |
| 16 GB microSD kart | İşletim sistemi | 4-6 $ |
| 5 V 2.5 A micro-USB adaptör | Güç | 5-8 $ |
| Dişi-dişi jumper kablolar | Bağlantı (lehimsiz) | 1-2 $ |
| Kutu | Ayakkabı kutusu, saklama kabı, ahşap kutu ya da 3D baskı | 0-5 $ |

**Neden USB mikrofon ve hoparlör değil?** Pi Zero'da tek USB portu var. Bu yüzden hub gerekir ve toplam maliyet artar. I2S modülleri hem daha ucuzdur hem de doğrudan pinlere takılır.

### Kablo bağlantısı

Mikrofon ve amfi aynı saat hatlarını paylaşır.

```
Raspberry Pi pin            INMP441 (mikrofon)      MAX98357A (amfi)
-------------------------   ---------------------   ------------------
3.3V   (pin 1)          ──► VDD
5V     (pin 2)          ─────────────────────────►  VIN
GND    (pin 6)          ──► GND, L/R            ──► GND
GPIO18 (pin 12) BCLK    ──► SCK                 ──► BCLK
GPIO19 (pin 35) LRCLK   ──► WS                  ──► LRC
GPIO20 (pin 38) DIN     ◄── SD
GPIO21 (pin 40) DOUT    ─────────────────────────►  DIN
                                                    + / - ──► hoparlör

Buton:  GPIO17 (pin 11) ── buton ── GND (pin 9)
LED:    GPIO27 (pin 13) ── 220Ω ── LED(+)  LED(-) ── GND (pin 14)
```

- INMP441'in **L/R** pini GND'ye bağlanmalıdır. Böylece mikrofon sol kanaldan konuşur.
- MAX98357A'nın **SD** ve **GAIN** pinlerini boş bırakın. Ses yetmezse GAIN pinini GND'ye bağlayın; bu sesi 12 dB yükseltir.

### Yazılım ayarı

1. Raspberry Pi Imager ile **Raspberry Pi OS Lite (64-bit)** kurun. Kurarken Wi-Fi ve SSH'yi açın.
2. `/boot/firmware/config.txt` dosyasına şunu ekleyin. Bu sürücü INMP441 + MAX98357A ikilisiyle çalışır:
   ```
   dtparam=audio=off
   dtoverlay=googlevoicehat-soundcard
   ```
3. Repodaki ses ayarını kopyalayın ve cihazı yeniden başlatın:
   ```bash
   sudo cp deploy/asound.conf /etc/asound.conf
   sudo reboot
   ```
4. Ses kartının adını `aplay -l` ile kontrol edin. `sndrpigooglevoi` yazmıyorsa `asound.conf` içindeki adı düzeltin.
5. Deneme:
   ```bash
   arecord -f S16_LE -r 16000 -c 1 -d 4 deneme.wav && aplay deneme.wav
   ```
6. Kayıt çok kısıksa `config.yaml` içinde `audio.input_gain` değerini artırın (ör. `4.0`).
7. `config.yaml` içinde `hardware.button: gpio` ve `hardware.led_pin: 27` ayarlarını yapın.

## Seçenek 2: En ucuz (eldeki eski bilgisayar), 0-5 $

Kullanılmayan eski bir dizüstü bilgisayar, mini PC ya da Pi 3/4 zaten varsa, dahili mikrofon ve hoparlörle hiçbir şey almadan çalışır. Buton yerine Enter tuşu kullanılır (`hardware.button: keyboard`). Çocuk için büyük bir buton isterseniz ucuz bir USB tuş (tek tuşlu "makro pedalı") alıp Enter'a atayabilirsiniz.

## Seçenek 3: Daha da ucuz ve küçük (ESP32-S3), yaklaşık 15-20 $

Bir ESP32-S3 kartı + INMP441 + MAX98357A ile yapılır. Pi'den yaklaşık 15 $ ucuzdur ve pille çalışacak kadar az enerji harcar. Ancak ESP32 Python kodunu çalıştıramaz. Bu yüzden ayrı bir firmware ve sohbeti yürüten küçük bir sunucu (evdeki bir bilgisayar ya da ucuz bir bulut fonksiyonu) gerekir. Bu repo şu an bunu desteklemiyor; isterseniz ikinci aşama olarak eklenebilir.

## Kutu ve çocuk güvenliği

- **Küçük parçalar:** Bütün elektroniği kapağı vidalı ya da yapıştırılmış bir kutunun içine alın. Küçük çocuklar için yutma tehlikesi var; kablo ya da modül dışarıda kalmamalı.
- **Pil:** Lityum pil (LiPo) yerine priz adaptörü kullanın. Çocuk elindeki LiPo pil ezilirse yanabilir.
- **Buton:** Kutunun üstüne büyük arcade butonu takın. Hoparlörün önüne birkaç delik açın ya da kumaş gerin. Mikrofonun önünde küçük bir delik bırakın.
- **Özelleştirme:** Kutuyu çocukla birlikte boyamak ya da üstüne bir yüz veya karakter yapmak, asistanı onun için daha sahiplenilebilir yapar. Asistanın adını `config.yaml` içinden değiştirebilirsiniz.

## Aylık işletme maliyeti

Donanım tek seferlik bir harcamadır; asıl sürekli masraf API ücretidir. Günde 50 soru-cevap için kabaca hesap:

| Kalem | Aylık yaklaşık |
|---|---|
| Ses → yazı (OpenAI whisper, ~25 dk/gün) | ~4-5 $ |
| Yazı → ses (OpenAI TTS) | ~3-6 $ |
| Claude Opus 5.5 (varsayılan) | ~15-25 $ |
| Claude Sonnet 5.5 | ~7-12 $ |
| Claude Haiku 5.5 | ~1 $ |

Model `config.yaml` içinde `assistant.model` satırıyla tek satırda değiştirilebilir. Cevap kalitesini kendiniz deneyip karşılaştırın; `python -m kidbot --text` modu bunun için uygundur. Günlük süre sınırı (`session.daily_limit_minutes`) maliyeti de sınırlar.
