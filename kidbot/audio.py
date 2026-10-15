"""Mikrofondan konuşma kaydı (basit ses etkinliği algılama) ve hoparlörden çalma."""

from __future__ import annotations

import logging
import threading
import time

import numpy as np

from .config import AudioConfig

log = logging.getLogger(__name__)

FRAME_MS = 30


def rms(frame: np.ndarray) -> float:
    return float(np.sqrt(np.mean(frame.astype(np.float32) ** 2)))


def apply_gain(frame: np.ndarray, gain: float) -> np.ndarray:
    if gain == 1.0:
        return frame.copy()
    return np.clip(frame.astype(np.float32) * gain, -32768, 32767).astype(np.int16)


BEEP_RATE = 24000


def beep_pcm(rate: int, freq: float = 880.0, ms: int = 120) -> bytes:
    t = np.arange(int(rate * ms / 1000)) / rate
    env = np.minimum(1.0, np.minimum(t, t[::-1]) * 200)
    return (0.25 * 32767 * env * np.sin(2 * np.pi * freq * t)).astype(np.int16).tobytes()


def resample(pcm: bytes, src_rate: int, dst_rate: int) -> bytes:
    """16-bit mono PCM'i doğrusal aradeğerleme ile yeniden örnekler (konuşma için yeterli)."""
    if src_rate == dst_rate or not pcm:
        return pcm
    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    n = int(round(len(x) * dst_rate / src_rate))
    y = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x)
    return y.astype(np.int16).tobytes()


class Endpointer:
    """Konuşmanın başladığı ve bittiği yeri ses enerjisine bakarak bulur.

    Saf mantıktır (donanım yok), böylece test edilebilir.
    """

    def __init__(self, cfg: AudioConfig, noise_floor: float):
        self.cfg = cfg
        self.threshold = max(noise_floor * cfg.vad_multiplier, 300.0)
        frames_per_sec = 1000 / FRAME_MS
        self.silence_frames_needed = int(cfg.silence_seconds * frames_per_sec)
        self.start_timeout_frames = int(cfg.start_timeout_seconds * frames_per_sec)
        self.max_frames = int(cfg.max_utterance_seconds * frames_per_sec)
        self.preroll = 10  # konuşma başlamadan önceki ~300 ms'yi de tut
        self.started = False
        self.frames: list[np.ndarray] = []
        self._silent_run = 0
        self._voiced = 0
        self._seen = 0

    def feed(self, frame: np.ndarray) -> str:
        """Bir ses çerçevesi verir. Dönüş: 'continue', 'done' veya 'timeout'."""
        self._seen += 1
        loud = rms(frame) > self.threshold
        self.frames.append(frame)
        if not self.started:
            if loud:
                self._voiced += 1
                # Tek bir tıkırtı yerine en az ~90 ms ses arıyoruz.
                if self._voiced >= 3:
                    self.started = True
                    self.frames = self.frames[-(self.preroll + self._voiced):]
            else:
                self._voiced = 0
                self.frames = self.frames[-self.preroll:]
            if not self.started and self._seen >= self.start_timeout_frames:
                return "timeout"
            return "continue"

        self._silent_run = 0 if loud else self._silent_run + 1
        if self._silent_run >= self.silence_frames_needed or len(self.frames) >= self.max_frames:
            return "done"
        return "continue"

    def audio(self) -> np.ndarray:
        return np.concatenate(self.frames) if self.frames else np.zeros(0, dtype=np.int16)


class AudioIO:
    def __init__(self, cfg: AudioConfig):
        import sounddevice as sd  # donanım kütüphanesi sadece burada gerekir

        self.sd = sd
        self.cfg = cfg
        self.noise_floor = 200.0
        self._play_lock = threading.Lock()

    def calibrate(self, seconds: float = 1.0) -> None:
        """Ortam gürültüsünü ölçer (odada kimse konuşmuyorken)."""
        n = int(self.cfg.sample_rate * seconds)
        data = self.sd.rec(n, samplerate=self.cfg.sample_rate, channels=1,
                           dtype="int16", device=self.cfg.input_device)
        self.sd.wait()
        self.noise_floor = rms(apply_gain(data[:, 0], self.cfg.input_gain))
        log.info("Gürültü tabanı: %.0f", self.noise_floor)

    def listen(self, stop: threading.Event) -> np.ndarray | None:
        """Çocuk konuşup susana kadar kaydeder. Konuşma yoksa None."""
        ep = Endpointer(self.cfg, self.noise_floor)
        block = int(self.cfg.sample_rate * FRAME_MS / 1000)
        with self.sd.InputStream(samplerate=self.cfg.sample_rate, channels=1, dtype="int16",
                                 blocksize=block, device=self.cfg.input_device) as stream:
            while not stop.is_set():
                frame, _ = stream.read(block)
                state = ep.feed(apply_gain(frame[:, 0], self.cfg.input_gain))
                if state == "timeout":
                    return None
                if state == "done":
                    return ep.audio()
        return None

    def play_pcm(self, pcm: bytes, sample_rate: int, stop: threading.Event) -> None:
        """16-bit mono PCM çalar; stop olayı gelirse hemen keser."""
        if not pcm:
            return
        audio = np.frombuffer(pcm, dtype=np.int16)
        with self._play_lock:
            self.sd.play(audio, samplerate=sample_rate, device=self.cfg.output_device)
            duration = len(audio) / sample_rate
            t0 = time.monotonic()
            while time.monotonic() - t0 < duration + 0.1:
                if stop.wait(0.05):
                    self.sd.stop()
                    return
            self.sd.wait()

    def beep(self) -> None:
        """Dinlemeye başladığını belli eden kısa 'bip'."""
        self.play_pcm(beep_pcm(BEEP_RATE), BEEP_RATE, threading.Event())
