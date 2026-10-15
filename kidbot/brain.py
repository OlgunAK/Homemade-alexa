"""Claude ile sohbet: cevabı akış (stream) halinde alıp cümle cümle verir."""

from __future__ import annotations

import logging
import re
from typing import Iterator

import anthropic

from .config import Config
from .prompts import build_system_prompt

log = logging.getLogger(__name__)

# Cümle sonu: . ! ? … ardından boşluk. "Dr. " gibi kısaltmalar nadir, sorun değil.
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")
# Sese dönüşmemesi gereken işaretler (model yine de kullanırsa).
_MARKDOWN = re.compile(r"[*_#`>\[\]]|^\s*[-•]\s+", re.MULTILINE)

FALLBACK_REPLY = "Hımm, bunu şimdi cevaplayamıyorum. Başka bir şey sormak ister misin?"
ERROR_REPLY = "Ay, internetle ilgili küçük bir sorun oldu. Birazdan tekrar dener misin?"


def clean_for_speech(text: str) -> str:
    return re.sub(r"\s+", " ", _MARKDOWN.sub("", text)).strip()


def split_sentences(buffer: str) -> tuple[list[str], str]:
    """Tamamlanmış cümleleri ayırır, yarım kalan kısmı geri döndürür."""
    parts = _SENTENCE_END.split(buffer)
    return [p for p in parts[:-1] if p.strip()], parts[-1]


class Brain:
    """Bir sohbet oturumu (butona basıştan uyumaya kadar)."""

    def __init__(self, cfg: Config, client: anthropic.Anthropic | None = None):
        self.cfg = cfg
        self.client = client or anthropic.Anthropic()
        self.system = build_system_prompt(cfg)
        self.messages: list = []

    def reset(self) -> None:
        self.messages = []

    def reply(self, user_text: str) -> Iterator[str]:
        """Çocuğun sözüne cevabı, konuşulabilir cümleler halinde üretir."""
        self.messages.append({"role": "user", "content": user_text})
        a = self.cfg.assistant
        buffer = ""
        spoke = False
        try:
            with self.client.beta.messages.stream(
                model=a.model,
                max_tokens=a.max_tokens,
                system=self.system,
                messages=self.messages,
                output_config={"effort": a.effort},
                cache_control={"type": "ephemeral"},
                # Güvenlik sınıflandırıcısı bir isteği reddederse,
                # sunucu tarafında önerilen yedek modelle yeniden dener.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            ) as stream:
                for chunk in stream.text_stream:
                    buffer += chunk
                    sentences, buffer = split_sentences(buffer)
                    for s in sentences:
                        s = clean_for_speech(s)
                        if s:
                            spoke = True
                            yield s
                final = stream.get_final_message()
        except anthropic.APIConnectionError:
            log.exception("Claude'a bağlanılamadı")
            self._rollback()
            yield ERROR_REPLY
            return
        except anthropic.RateLimitError:
            log.warning("Hız sınırına takıldı")
            self._rollback()
            yield ERROR_REPLY
            return
        except anthropic.APIStatusError as e:
            log.error("Claude API hatası %s: %s", e.status_code, e.message)
            self._rollback()
            yield ERROR_REPLY
            return

        if final.stop_reason == "refusal":
            # Reddedilen tur geçmişe eklenmez; sohbet temiz devam eder.
            log.warning("Cevap reddedildi: %s", final.stop_details)
            self._rollback()
            yield FALLBACK_REPLY
            return

        tail = clean_for_speech(buffer)
        if tail:
            spoke = True
            yield tail
        # Tüm içeriği (düşünme blokları dahil) geçmişe olduğu gibi ekle.
        self.messages.append({"role": "assistant", "content": final.content})
        if not spoke:
            yield FALLBACK_REPLY

    def _rollback(self) -> None:
        if self.messages and self.messages[-1]["role"] == "user":
            self.messages.pop()
