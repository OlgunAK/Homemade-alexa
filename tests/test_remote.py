"""RemoteDevice'ı sahte bir ESP32 istemcisiyle uçtan uca dener."""

import json
import socket
import threading
import time

import numpy as np
import pytest
from websockets.exceptions import InvalidStatus
from websockets.sync.client import connect

from kidbot.config import Config
from kidbot.remote import SPEAKER_RATE, RemoteDevice


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def device():
    cfg = Config()
    cfg.hardware.listen_host = "127.0.0.1"
    cfg.hardware.listen_port = _free_port()
    cfg.hardware.device_token = "gizli"
    cfg.audio.silence_seconds = 0.3
    dev = RemoteDevice(cfg)
    yield dev
    dev._server.shutdown()


def _url(dev, token="gizli"):
    return f"ws://127.0.0.1:{dev.cfg.hardware.listen_port}/?token={token}"


def _pcm(level, seconds):
    rng = np.random.default_rng(1)
    return (rng.standard_normal(int(16000 * seconds)) * level).astype(np.int16).tobytes()


class FakeSpeaker:
    """ESP32 yazılımının davranışını taklit eder."""

    def __init__(self, url):
        self.ws = connect(url, compression=None)
        self.texts, self.audio = [], bytearray()
        self.listening = threading.Event()
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        try:
            for msg in self.ws:
                if isinstance(msg, bytes):
                    self.audio += msg
                    continue
                data = json.loads(msg)
                self.texts.append(data)
                if data["type"] == "listen":
                    self.listening.set()
                elif data["type"] == "stop_listen":
                    self.listening.clear()
        except Exception:
            pass

    def send_mic(self, pcm):
        for i in range(0, len(pcm), 960):
            self.ws.send(pcm[i:i + 960])


def _wait(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_wrong_token_is_rejected(device):
    with pytest.raises(InvalidStatus):
        connect(_url(device, token="yanlis"))


def test_button_led_listen_and_play(device):
    pressed = threading.Event()
    device.on_press = pressed.set
    spk = FakeSpeaker(_url(device))
    # Bağlanınca 1 sn gürültü ölçümü yapılır
    assert spk.listening.wait(2)
    spk.send_mic(_pcm(50, 1.1))
    assert _wait(lambda: not spk.listening.is_set())
    assert 30 < device.noise_floor < 80

    spk.ws.send(json.dumps({"type": "button"}))
    assert pressed.wait(2)

    device.set_led(True, blink=True)
    assert _wait(lambda: {"type": "led", "state": "blink"} in spk.texts)

    result = {}
    t = threading.Thread(target=lambda: result.setdefault("a", device.listen(threading.Event())))
    t.start()
    assert spk.listening.wait(2)
    spk.send_mic(_pcm(50, 0.2) + _pcm(4000, 0.6) + _pcm(50, 0.6))
    t.join(3)
    assert result["a"] is not None and len(result["a"]) > 16000 * 0.6
    assert _wait(lambda: not spk.listening.is_set())

    # 16 kHz ses 24 kHz'e çevrilip gerçek zaman hızında gönderilir
    tone = _pcm(1000, 1.0)
    t0 = time.monotonic()
    device.play_pcm(tone, 16000, threading.Event())
    assert time.monotonic() - t0 >= 0.9
    assert abs(len(spk.audio) - SPEAKER_RATE * 2) <= 4


def test_play_stops_and_flushes_on_button(device):
    spk = FakeSpeaker(_url(device))
    assert _wait(lambda: device._conn is not None)
    stop = threading.Event()
    threading.Timer(0.3, stop.set).start()
    t0 = time.monotonic()
    device.play_pcm(_pcm(1000, 3.0), 16000, stop)
    assert time.monotonic() - t0 < 1.0
    assert _wait(lambda: {"type": "flush"} in spk.texts)


def test_listen_without_device_returns_none(device):
    assert device.listen(threading.Event()) is None
