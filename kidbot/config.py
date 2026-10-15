"""Ayarların yüklenmesi: config.yaml + ortam değişkenleri."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class ChildProfile:
    name: str = "Deniz"
    age: int = 6
    language: str = "tr"
    interests: list[str] = field(default_factory=list)


@dataclass
class AssistantConfig:
    name: str = "Bilge"
    model: str = "claude-opus-5-5"
    # Sesli sohbette hız önemli: düşük efor = hızlı cevap.
    effort: str = "low"
    max_tokens: int = 1024


@dataclass
class SpeechConfig:
    provider: str = "openai"  # "openai" veya "google"
    stt_model: str = "whisper-1"
    tts_model: str = "gpt-4o-mini-tts"
    tts_voice: str = "nova"
    tts_speed: float = 0.95
    google_voice: str = "tr-TR-Wavenet-E"


@dataclass
class AudioConfig:
    sample_rate: int = 16000
    # Çocuk bu kadar saniye susunca konuşmasını bitirdi sayılır.
    silence_seconds: float = 1.2
    # Hiç konuşmazsa bu kadar bekleyip vazgeçer.
    start_timeout_seconds: float = 8.0
    max_utterance_seconds: float = 20.0
    # Gürültü tabanının kaç katı "konuşma" sayılır.
    vad_multiplier: float = 3.0
    input_device: str | int | None = None
    output_device: str | int | None = None


@dataclass
class HardwareConfig:
    # "gpio" (Raspberry Pi butonu) veya "keyboard" (Enter tuşu, test için)
    button: str = "keyboard"
    gpio_pin: int = 17
    led_pin: int | None = None


@dataclass
class SessionConfig:
    # Bu kadar tur boyunca hiç ses gelmezse asistan kendiliğinden uyur.
    idle_turns_before_sleep: int = 2
    # Ebeveynin okuyabilmesi için konuşma kaydı (boş = kapalı)
    log_dir: str | None = "logs"
    # Günlük toplam kullanım sınırı (dakika). 0 = sınırsız.
    daily_limit_minutes: int = 0


@dataclass
class Config:
    child: ChildProfile = field(default_factory=ChildProfile)
    assistant: AssistantConfig = field(default_factory=AssistantConfig)
    speech: SpeechConfig = field(default_factory=SpeechConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    hardware: HardwareConfig = field(default_factory=HardwareConfig)
    session: SessionConfig = field(default_factory=SessionConfig)


def _merge(dc, data: dict | None):
    for key, value in (data or {}).items():
        if not hasattr(dc, key):
            raise ValueError(f"Bilinmeyen ayar: {type(dc).__name__}.{key}")
        setattr(dc, key, value)
    return dc


def load_config(path: str | os.PathLike | None = None) -> Config:
    path = Path(path or os.environ.get("KIDBOT_CONFIG", "config.yaml"))
    raw = {}
    if path.exists():
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cfg = Config()
    for section in ("child", "assistant", "speech", "audio", "hardware", "session"):
        _merge(getattr(cfg, section), raw.get(section))
    return cfg
