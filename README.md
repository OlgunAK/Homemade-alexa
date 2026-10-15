# Bilge: çocuklar için sesli öğretmen asistan

Butona basınca uyanan, çocukla Türkçe konuşan, sabırla öğreten, Alexa benzeri ev yapımı bir hoparlör.
Beyin olarak **Claude API** kullanılıyor. Sesi yazıya ve yazıyı sese çevirmek için **OpenAI** veya **Google Cloud** konuşma servisi kullanılıyor.

```
 [buton] ──► uyan ──► "bip" ──► dinle ──► yazıya çevir (STT) ──► Claude ──► cümle cümle sese çevir (TTS) ──► hoparlör
                        ▲                                                                                  │
                        └──────────────────────────── çocuk tekrar konuşur ◄───────────────────────────────┘
 [buton tekrar] ──► "Görüşürüz!" ──► uyku
```

## Neden çocuğa özel?

Sistem talimatı ([kidbot/prompts.py](kidbot/prompts.py)) asistanı bir öğretmen-arkadaş olarak tanımlar:

- **Kısa ve basit konuşur.** Çocuğun yaşına uygun kelimeler kullanır, bir seferde tek fikir anlatır.
- **Anlamadığında her seferinde farklı anlatır.** Çocuk "anlamadım" dediğinde ya da kontrol sorusunu yanlış cevapladığında aynı açıklamayı tekrarlamaz. Konuyu daha küçük adımlara böler, yeni bir örnek verir, hikâyeleştirir ya da parmakla saymak gibi bir etkinlik önerir. Çocuk aynı soruyu kaç kez sorarsa sorsun sabırsızlanmaz.
- **Anlayıp anlamadığını sorar.** Açıklamadan sonra küçük bir kontrol sorusu sorar ve ipucuyla çocuğu kendi bulmaya teşvik eder.
- **Güvenlik kuralları vardır.** Yaşa uygun olmayan konularda çocuğu kısaca bir yetişkine yönlendirir. Kişisel bilgi istemez. Tehlikeli deney önermez. Bilmediği şeyi uydurmaz. Çocuk üzgün ya da tehlikede görünürse bir büyüğüne söylemesini ister.
- **Ebeveyn kontrolü vardır.** Tüm konuşmalar `logs/YYYY-AA-GG.txt` dosyasına yazılır, isterseniz günlük süre sınırı da koyabilirsiniz.

Çocuğun adı, yaşı ve ilgi alanları `config.yaml` dosyasından ayarlanır. Asistan örneklerini bu ilgi alanlarından seçer (ör. dinozor sever, toplamayı dinozorlarla anlatır).

## Donanım (önerilen)

Ucuz, lehimsiz, ev yapımı kurulum için parça listesi, kablo şeması ve maliyet hesabı: **[docs/DONANIM.md](docs/DONANIM.md)**

| Parça | Not |
|---|---|
| Raspberry Pi 4 / 5 (veya Pi Zero 2 W) | Herhangi bir Linux bilgisayar ya da Mac de olur |
| USB mikrofon veya ReSpeaker 2-Mic HAT | Çocuk sesini uzaktan almak için HAT daha iyi |
| Hoparlör | USB, 3.5 mm ya da HAT çıkışı |
| Büyük, renkli bir buton | GPIO17 (pin 11) ile GND (pin 9) arasına |
| (İsteğe bağlı) LED + 220 Ω direnç | Ör. GPIO27. Açıkken yanar, dinlerken yanıp söner |

Bilgisayarda deneme yaparken buton yerine **Enter** tuşu kullanılabilir (`hardware.button: keyboard`).

## Kurulum

```bash
git clone <bu repo> Homemade-alexa && cd Homemade-alexa
sudo apt install -y python3-venv libportaudio2      # Raspberry Pi OS / Debian
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env               # API anahtarlarını yazın
cp config.example.yaml config.yaml # çocuğun adı, yaşı, ilgi alanları, buton türü
```

Gerekli anahtarlar:

- `ANTHROPIC_API_KEY`: [console.anthropic.com](https://console.anthropic.com) adresinden alınır.
- `OPENAI_API_KEY`: `speech.provider: openai` seçiliyse gerekir.
- `GOOGLE_APPLICATION_CREDENTIALS`: `speech.provider: google` seçiliyse gerekir. Bu durumda `requirements.txt` içindeki Google satırlarının başındaki `#` işaretini kaldırın.

## Çalıştırma

```bash
# 1) Önce donanımsız deneyin: sohbeti klavyeden yazarak test edin
python -m kidbot --text

# 2) Ses cihazlarını listeleyin, gerekirse config.yaml'da input/output_device ayarlayın
python -m sounddevice

# 3) Sesli asistanı başlatın (açılışta 1 sn sessiz kalın, gürültü ölçülüyor)
python -m kidbot
```

Kullanım:

- **Butona bas:** asistan uyanır ve selam verir. "Bip" sesinden sonra çocuk konuşur.
- Çocuk susunca (~1.2 sn) asistan cevap verir ve tekrar dinlemeye başlar. Sohbet böyle devam eder.
- **Butona tekrar bas:** asistan konuşuyor olsa bile hemen susar, "Görüşürüz!" der ve uyur.
- Çocuk "hoşça kal" derse ya da iki kez üst üste hiçbir şey söylemezse asistan kendiliğinden uyur.

### Açılışta otomatik başlatma (Raspberry Pi)

```bash
sudo cp deploy/kidbot.service /etc/systemd/system/
sudo systemctl enable --now kidbot
journalctl -u kidbot -f   # kayıtları izlemek için
```

## Ayar ipuçları

- **Asistan çocuğun sözünü kesiyorsa** `audio.silence_seconds` değerini 1.5-2.0 yapın. Küçük çocuklar düşünürken uzun duraklar.
- **Gürültülü odada kendi kendine dinlemeye başlıyorsa** `audio.vad_multiplier` değerini artırın.
- **Cevaplar daha derin olsun istiyorsanız** `assistant.effort: medium` yapın. Cevaplar biraz daha yavaş gelir.
- **Model:** Varsayılan `claude-opus-5-5`. Maliyeti düşürmek isterseniz `claude-sonnet-5-5` ya da `claude-haiku-5-5` da kullanılabilir.
- **Ses:** OpenAI'de `tts_voice` (ör. `nova`, `shimmer`, `alloy`), Google'da `google_voice` (ör. `tr-TR-Wavenet-E`, `tr-TR-Standard-A`).

## Kod yapısı

| Dosya | Görev |
|---|---|
| `kidbot/main.py` | Butonla uyanma/uyuma döngüsü, oturum, ebeveyn kaydı, `--text` modu |
| `kidbot/prompts.py` | Çocuğa özel öğretmen talimatı |
| `kidbot/brain.py` | Claude ile akışlı sohbet: cevabı cümle cümle verir, böylece ilk cümle hemen seslendirilir |
| `kidbot/audio.py` | Mikrofon kaydı, konuşma başı/sonu algılama, çalma, "bip" |
| `kidbot/speech.py` | STT/TTS: OpenAI veya Google Cloud |
| `kidbot/button.py` | GPIO butonu / LED ya da klavye |

Testler: `pip install pytest && python -m pytest`

## Gizlilik notu

Çocuğun sesi yazıya çevrilmek için seçtiğiniz konuşma servisine, yazıya çevrilmiş hali de Claude API'ye gönderilir. Mikrofon yalnızca butona basıldıktan sonra açılır; asistan uyurken hiçbir şey dinlemez ve göndermez. Konuşma dökümleri yalnızca sizin cihazınızdaki `logs/` klasöründe tutulur.
