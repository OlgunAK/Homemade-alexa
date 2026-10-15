"""Bulut konuşma servisleri: ses → yazı (STT) ve yazı → ses (TTS).

Claude metin ile çalışır; sesi yazıya ve yazıyı sese çevirmek için ayrı bir
servis gerekir. İki seçenek var: OpenAI veya Google Cloud.
"""

from __future__ import annotations

import io
import wave
from typing import Protocol

import numpy as np

from .config import SpeechConfig


def pcm_to_wav(audio: np.ndarray, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(audio.astype(np.int16).tobytes())
    return buf.getvalue()


def wav_to_pcm(data: bytes) -> tuple[bytes, int]:
    with wave.open(io.BytesIO(data), "rb") as w:
        return w.readframes(w.getnframes()), w.getframerate()


class Speech(Protocol):
    def transcribe(self, audio: np.ndarray, sample_rate: int) -> str: ...
    def synthesize(self, text: str) -> tuple[bytes, int]: ...


class OpenAISpeech:
    PCM_RATE = 24000  # OpenAI "pcm" çıktısı: 24 kHz, 16-bit, mono

    def __init__(self, cfg: SpeechConfig, child_age: int):
        from openai import OpenAI

        self.client = OpenAI()  # OPENAI_API_KEY ortam değişkeninden
        self.cfg = cfg
        self.prompt = f"{child_age} yaşında bir çocuk Türkçe konuşuyor."

    def transcribe(self, audio: np.ndarray, sample_rate: int) -> str:
        wav = pcm_to_wav(audio, sample_rate)
        result = self.client.audio.transcriptions.create(
            model=self.cfg.stt_model,
            file=("soru.wav", wav, "audio/wav"),
            language="tr",
            prompt=self.prompt,
        )
        return result.text.strip()

    def synthesize(self, text: str) -> tuple[bytes, int]:
        kwargs = {}
        if self.cfg.tts_model.startswith("gpt-"):
            kwargs["instructions"] = (
                "Küçük bir çocukla konuşan sıcak, neşeli ve sabırlı bir öğretmen gibi, "
                "net ve biraz yavaş konuş."
            )
        resp = self.client.audio.speech.create(
            model=self.cfg.tts_model,
            voice=self.cfg.tts_voice,
            input=text,
            response_format="pcm",
            speed=self.cfg.tts_speed,
            **kwargs,
        )
        return resp.content, self.PCM_RATE


class GoogleSpeech:
    def __init__(self, cfg: SpeechConfig):
        from google.cloud import speech, texttospeech

        self.speech = speech
        self.tts = texttospeech
        self.stt_client = speech.SpeechClient()  # GOOGLE_APPLICATION_CREDENTIALS
        self.tts_client = texttospeech.TextToSpeechClient()
        self.cfg = cfg

    def transcribe(self, audio: np.ndarray, sample_rate: int) -> str:
        s = self.speech
        resp = self.stt_client.recognize(
            config=s.RecognitionConfig(
                encoding=s.RecognitionConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=sample_rate,
                language_code="tr-TR",
                enable_automatic_punctuation=True,
            ),
            audio=s.RecognitionAudio(content=audio.astype(np.int16).tobytes()),
        )
        return " ".join(r.alternatives[0].transcript for r in resp.results if r.alternatives).strip()

    def synthesize(self, text: str) -> tuple[bytes, int]:
        t = self.tts
        resp = self.tts_client.synthesize_speech(
            input=t.SynthesisInput(text=text),
            voice=t.VoiceSelectionParams(language_code="tr-TR", name=self.cfg.google_voice),
            audio_config=t.AudioConfig(
                audio_encoding=t.AudioEncoding.LINEAR16,
                sample_rate_hertz=24000,
                speaking_rate=self.cfg.tts_speed,
            ),
        )
        return wav_to_pcm(resp.audio_content)


def make_speech(cfg: SpeechConfig, child_age: int) -> Speech:
    if cfg.provider == "openai":
        return OpenAISpeech(cfg, child_age)
    if cfg.provider == "google":
        return GoogleSpeech(cfg)
    raise ValueError(f"Bilinmeyen konuşma sağlayıcısı: {cfg.provider}")
