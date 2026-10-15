"""Ana döngü: butonla uyanır, dinler, düşünür, konuşur; butonla uyur."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import queue
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv

from .audio import AudioIO
from .brain import Brain
from .button import Button
from .config import Config, load_config
from .prompts import GREETING_HINT, NO_SPEECH_HINT
from .speech import Speech, make_speech

log = logging.getLogger("kidbot")

GOODBYE_WORDS = ("hoşça kal", "görüşürüz", "güle güle", "bay bay")
SAID_GOODBYE = "Görüşürüz! Ne zaman istersen butona bas, ben buradayım."
DIDNT_HEAR = "Seni tam duyamadım. Bir daha söyler misin?"
LIMIT_REACHED = "Bugünlük sohbet süremiz doldu. Yarın yine konuşalım, olur mu?"


class ParentLog:
    """Ebeveynin okuyabileceği günlük konuşma dökümü ve kullanım süresi."""

    def __init__(self, log_dir: str | None):
        self.dir = Path(log_dir) if log_dir else None
        if self.dir:
            self.dir.mkdir(parents=True, exist_ok=True)

    def write(self, who: str, text: str) -> None:
        if not self.dir:
            return
        now = dt.datetime.now()
        with open(self.dir / f"{now:%Y-%m-%d}.txt", "a", encoding="utf-8") as f:
            f.write(f"[{now:%H:%M:%S}] {who}: {text}\n")

    def _usage_file(self) -> Path | None:
        return self.dir / "usage.json" if self.dir else None

    def used_minutes_today(self) -> float:
        p = self._usage_file()
        if not p or not p.exists():
            return 0.0
        return json.loads(p.read_text()).get(dt.date.today().isoformat(), 0.0)

    def add_usage(self, seconds: float) -> None:
        p = self._usage_file()
        if not p:
            return
        data = json.loads(p.read_text()) if p.exists() else {}
        key = dt.date.today().isoformat()
        data[key] = data.get(key, 0.0) + seconds / 60
        p.write_text(json.dumps(data))


class Assistant:
    def __init__(self, cfg: Config, speech: Speech, audio: AudioIO):
        self.cfg = cfg
        self.speech = speech
        self.audio = audio
        self.brain = Brain(cfg)
        self.parent_log = ParentLog(cfg.session.log_dir)
        self.awake = threading.Event()
        self.stop = threading.Event()  # aktif dinleme/konuşmayı keser
        self.wake_request = threading.Event()
        self.tts_pool = ThreadPoolExecutor(max_workers=2)
        self.button = Button(cfg.hardware, self.on_button)

    # --- buton ---
    def on_button(self) -> None:
        if self.awake.is_set():
            log.info("Buton: uyku")
            self.stop.set()
        else:
            log.info("Buton: uyan")
            self.wake_request.set()

    # --- konuşma ---
    def say(self, text: str) -> None:
        self.parent_log.write(self.cfg.assistant.name, text)
        pcm, rate = self.speech.synthesize(text)
        self.audio.play_pcm(pcm, rate, self.stop)

    def say_reply(self, user_text: str) -> None:
        """Claude'un cevabını cümle cümle seslendirir.

        Bir cümle çalınırken sonraki cümleler hem Claude'dan gelmeye hem de
        sese çevrilmeye devam eder; böylece bekleme süresi kısalır.
        """
        pending: queue.Queue[Future | None] = queue.Queue()
        spoken: list[str] = []

        def produce() -> None:
            try:
                for sentence in self.brain.reply(user_text):
                    if self.stop.is_set():
                        break
                    spoken.append(sentence)
                    pending.put(self.tts_pool.submit(self.speech.synthesize, sentence))
            except Exception:
                log.exception("Cevap üretilemedi")
            finally:
                pending.put(None)

        threading.Thread(target=produce, daemon=True).start()
        while (fut := pending.get()) is not None:
            if self.stop.is_set():
                continue  # kalan cümleleri boşalt ama çalma
            try:
                pcm, rate = fut.result()
            except Exception:
                log.exception("Ses üretilemedi")
                continue
            self.audio.play_pcm(pcm, rate, self.stop)
        if spoken:
            self.parent_log.write(self.cfg.assistant.name, " ".join(spoken))

    # --- oturum ---
    def session(self) -> None:
        started = time.monotonic()
        self.brain.reset()
        self.stop.clear()
        self.awake.set()
        self.button.set_led(True)
        idle_turns = 0
        try:
            limit = self.cfg.session.daily_limit_minutes
            if limit and self.parent_log.used_minutes_today() >= limit:
                self.say(LIMIT_REACHED)
                return
            self.parent_log.write("---", "oturum başladı")
            self.say_reply(GREETING_HINT)
            while not self.stop.is_set():
                self.audio.beep()
                self.button.set_led(True, blink=True)
                recording = self.audio.listen(self.stop)
                self.button.set_led(True)
                if self.stop.is_set():
                    break
                if recording is None:
                    idle_turns += 1
                    if idle_turns >= self.cfg.session.idle_turns_before_sleep:
                        self.say(SAID_GOODBYE)
                        break
                    self.say_reply(NO_SPEECH_HINT)
                    continue
                idle_turns = 0
                text = self.speech.transcribe(recording, self.cfg.audio.sample_rate)
                log.info("Çocuk: %s", text)
                if not text:
                    self.say(DIDNT_HEAR)
                    continue
                self.parent_log.write(self.cfg.child.name, text)
                self.say_reply(text)
                if any(w in text.lower() for w in GOODBYE_WORDS):
                    break
        except Exception:
            log.exception("Oturumda hata")
        finally:
            if self.stop.is_set():
                self.stop.clear()
                try:
                    self.say("Görüşürüz!")
                except Exception:
                    log.exception("Veda edilemedi")
            self.awake.clear()
            self.button.set_led(False)
            self.parent_log.add_usage(time.monotonic() - started)
            self.parent_log.write("---", "oturum bitti")

    def run(self) -> None:
        log.info("Ortam gürültüsü ölçülüyor, lütfen sessiz olun...")
        self.audio.calibrate()
        log.info("Hazır. Butona basınca uyanırım.")
        while True:
            self.wake_request.wait()
            self.wake_request.clear()
            self.session()
            self.wake_request.clear()  # oturum sırasında gelen basışları yut


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Çocuklar için sesli öğretmen asistan")
    parser.add_argument("--config", default=None, help="config.yaml yolu")
    parser.add_argument("--text", action="store_true",
                        help="Mikrofon/hoparlör olmadan, klavyeden yazışarak dene")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config(args.config)

    if args.text:
        text_mode(cfg)
        return
    speech = make_speech(cfg.speech, cfg.child.age)
    Assistant(cfg, speech, AudioIO(cfg.audio)).run()


def text_mode(cfg: Config) -> None:
    """Donanımsız deneme: sistem talimatını ve sohbet akışını test etmek için."""
    brain = Brain(cfg)
    print(f"{cfg.assistant.name}: ", end="")
    print(" ".join(brain.reply(GREETING_HINT)))
    while True:
        try:
            text = input(f"{cfg.child.name}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not text:
            continue
        print(f"{cfg.assistant.name}: " + " ".join(brain.reply(text)))


if __name__ == "__main__":
    main()
