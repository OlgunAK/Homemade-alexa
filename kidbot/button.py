"""Aç/kapa butonu: Raspberry Pi GPIO butonu ya da test için klavyede Enter."""

from __future__ import annotations

import sys
import threading
from typing import Callable

from .config import HardwareConfig


class Button:
    def __init__(self, cfg: HardwareConfig, on_press: Callable[[], None]):
        self.on_press = on_press
        self._led = None
        if cfg.button == "gpio":
            from gpiozero import LED, Button as GpioButton

            self._btn = GpioButton(cfg.gpio_pin, pull_up=True, bounce_time=0.15)
            self._btn.when_pressed = lambda: self.on_press()
            if cfg.led_pin is not None:
                self._led = LED(cfg.led_pin)
        elif cfg.button == "keyboard":
            threading.Thread(target=self._keyboard_loop, daemon=True).start()
        else:
            raise ValueError(f"Bilinmeyen buton türü: {cfg.button}")

    def _keyboard_loop(self) -> None:
        print("Asistanı açmak/kapatmak için Enter'a basın.")
        for _ in sys.stdin:
            self.on_press()

    def set_led(self, on: bool, blink: bool = False) -> None:
        if not self._led:
            return
        if blink:
            self._led.blink(on_time=0.3, off_time=0.3)
        elif on:
            self._led.on()
        else:
            self._led.off()
