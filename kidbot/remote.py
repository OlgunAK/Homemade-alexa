"""Wi-Fi hoparlör: ESP32 cihazı laptoptaki bu WebSocket sunucusuna bağlanır.

Cihaz sadece "kulak, ağız ve buton"dur; tüm düşünme laptopta yapılır.

Protokol (tek WebSocket bağlantısı, ws://LAPTOP:8765/?token=...):
  cihaz → laptop  metin  {"type": "button"}           butona basıldı
                  ikili  16 kHz, 16-bit, mono PCM      mikrofon (sadece dinlerken)
  laptop → cihaz  metin  {"type": "listen"}            mikrofonu göndermeye başla
                  metin  {"type": "stop_listen"}       mikrofonu durdur
                  metin  {"type": "flush"}             çalmakta olan sesi hemen kes
                  metin  {"type": "led", "state": "on" | "off" | "blink"}
                  ikili  24 kHz, 16-bit, mono PCM      hoparlör
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from http import HTTPStatus
from typing import Callable
from urllib.parse import parse_qs, urlparse

import numpy as np
from websockets.exceptions import ConnectionClosed
from websockets.sync.server import ServerConnection, serve

from .audio import BEEP_RATE, FRAME_MS, Endpointer, apply_gain, beep_pcm, resample, rms
from .config import Config

log = logging.getLogger(__name__)

MIC_RATE = 16000
SPEAKER_RATE = 24000
CHUNK_SECONDS = 0.1
# Cihaz tamponunu taşırmamak için en fazla bu kadar önden gönderilir.
MAX_LEAD_SECONDS = 0.5


class RemoteDevice:
    """AudioIO ve Button ile aynı arayüzü sunar; Assistant farkı bilmez."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.on_press: Callable[[], None] = lambda: None
        self.noise_floor = 200.0
        self._conn: ServerConnection | None = None
        self._send_lock = threading.Lock()
        self._mic: queue.Queue[bytes] = queue.Queue()
        self._listening = False
        self._mic_lock = threading.Lock()  # mikrofonu aynı anda tek kullanıcı
        hw = cfg.hardware
        self._server = serve(self._handle, hw.listen_host, hw.listen_port,
                             compression=None, process_request=self._check_token)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        log.info("Wi-Fi hoparlör bekleniyor: ws://<laptop-ip>:%d", hw.listen_port)

    # --- bağlantı ---
    def _check_token(self, conn: ServerConnection, request):
        expected = self.cfg.hardware.device_token
        if not expected:
            return None
        got = parse_qs(urlparse(request.path).query).get("token", [""])[0]
        if got != expected:
            log.warning("Yanlış token ile bağlanma denemesi: %s", conn.remote_address)
            return conn.respond(HTTPStatus.FORBIDDEN, "token\n")
        return None

    def _handle(self, conn: ServerConnection) -> None:
        log.info("Hoparlör bağlandı: %s", conn.remote_address)
        old, self._conn = self._conn, conn
        if old is not None:
            old.close()
        threading.Thread(target=self._calibrate_on_connect, daemon=True).start()
        try:
            for msg in conn:
                if isinstance(msg, bytes):
                    if self._listening:
                        self._mic.put(msg)
                    continue
                try:
                    data = json.loads(msg)
                except ValueError:
                    continue
                if data.get("type") == "button":
                    self.on_press()
        except ConnectionClosed:
            pass
        finally:
            if self._conn is conn:
                self._conn = None
            log.info("Hoparlör bağlantısı koptu")

    def _send(self, payload: str | bytes) -> bool:
        conn = self._conn
        if conn is None:
            return False
        try:
            with self._send_lock:
                conn.send(payload)
            return True
        except ConnectionClosed:
            return False

    def _cmd(self, type_: str, **kw) -> bool:
        return self._send(json.dumps({"type": type_, **kw}))

    # --- Button arayüzü ---
    def set_led(self, on: bool, blink: bool = False) -> None:
        self._cmd("led", state="blink" if blink else ("on" if on else "off"))

    # --- AudioIO arayüzü ---
    def calibrate(self, seconds: float = 1.0) -> None:
        """Cihaz bağlanınca otomatik ölçülür; burada yapacak bir şey yok."""

    def _calibrate_on_connect(self) -> None:
        if not self._mic_lock.acquire(blocking=False):
            return  # sohbet sürüyor, ölçüm sonraya kalsın
        try:
            audio = self._record_raw(1.0, threading.Event())
        finally:
            self._mic_lock.release()
        if audio is not None and len(audio):
            self.noise_floor = rms(audio)
            log.info("Hoparlör gürültü tabanı: %.0f", self.noise_floor)

    def _mic_frames(self, stop: threading.Event):
        """Cihazdan gelen sesi 30 ms'lik çerçeveler halinde verir."""
        frame_bytes = int(MIC_RATE * FRAME_MS / 1000) * 2
        buf = b""
        while not stop.is_set() and self._conn is not None:
            try:
                buf += self._mic.get(timeout=0.1)
            except queue.Empty:
                continue
            while len(buf) >= frame_bytes:
                chunk, buf = buf[:frame_bytes], buf[frame_bytes:]
                yield apply_gain(np.frombuffer(chunk, dtype=np.int16), self.cfg.audio.input_gain)

    def _start_mic(self) -> bool:
        while not self._mic.empty():
            self._mic.get_nowait()
        self._listening = True
        return self._cmd("listen")

    def _stop_mic(self) -> None:
        self._listening = False
        self._cmd("stop_listen")

    def _record_raw(self, seconds: float, stop: threading.Event) -> np.ndarray | None:
        if not self._start_mic():
            return None
        frames, need = [], int(seconds * 1000 / FRAME_MS)
        try:
            for f in self._mic_frames(stop):
                frames.append(f)
                if len(frames) >= need:
                    break
        finally:
            self._stop_mic()
        return np.concatenate(frames) if frames else None

    def listen(self, stop: threading.Event) -> np.ndarray | None:
        with self._mic_lock:
            return self._listen(stop)

    def _listen(self, stop: threading.Event) -> np.ndarray | None:
        if not self._start_mic():
            log.warning("Hoparlör bağlı değil, dinlenemiyor")
            stop.wait(1.0)
            return None
        ep = Endpointer(self.cfg.audio, self.noise_floor)
        try:
            for frame in self._mic_frames(stop):
                state = ep.feed(frame)
                if state == "timeout":
                    return None
                if state == "done":
                    return ep.audio()
        finally:
            self._stop_mic()
        return None

    def play_pcm(self, pcm: bytes, sample_rate: int, stop: threading.Event) -> None:
        """Sesi gerçek zamanlı hızda gönderir ve cihaz çalmayı bitirene kadar bekler."""
        pcm = resample(pcm, sample_rate, SPEAKER_RATE)
        chunk = int(SPEAKER_RATE * CHUNK_SECONDS) * 2
        bytes_per_sec = SPEAKER_RATE * 2
        t0 = time.monotonic()
        sent = 0
        for i in range(0, len(pcm), chunk):
            if stop.is_set():
                self._cmd("flush")
                return
            # Gönderilen ses, geçen süreden en fazla MAX_LEAD_SECONDS önde olsun.
            ahead = sent / bytes_per_sec - (time.monotonic() - t0)
            if ahead > MAX_LEAD_SECONDS:
                if stop.wait(ahead - MAX_LEAD_SECONDS):
                    self._cmd("flush")
                    return
            if not self._send(pcm[i:i + chunk]):
                return
            sent += len(pcm[i:i + chunk])
        # Cihazın tamponundaki son kısım da çalınsın (mikrofon kendi sesini duymasın).
        remaining = sent / bytes_per_sec - (time.monotonic() - t0) + 0.15
        if remaining > 0 and stop.wait(remaining):
            self._cmd("flush")

    def beep(self) -> None:
        self.play_pcm(beep_pcm(BEEP_RATE), BEEP_RATE, threading.Event())
