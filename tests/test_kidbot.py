from types import SimpleNamespace

import anthropic
import numpy as np

from kidbot.audio import FRAME_MS, Endpointer
from kidbot.brain import ERROR_REPLY, FALLBACK_REPLY, Brain, clean_for_speech, split_sentences
from kidbot.config import AudioConfig, Config, load_config
from kidbot.prompts import build_system_prompt


# --- metin işleme ---

def test_split_sentences_keeps_tail():
    done, rest = split_sentences("Merhaba Deniz! Bugün ne öğrenelim? Belki")
    assert done == ["Merhaba Deniz!", "Bugün ne öğrenelim?"]
    assert rest == "Belki"


def test_clean_for_speech_strips_markdown():
    assert clean_for_speech("**Güneş** bir `yıldız`dır") == "Güneş bir yıldızdır"
    assert clean_for_speech("- elma\n- armut") == "elma armut"


def test_system_prompt_mentions_child():
    cfg = Config()
    cfg.child.name, cfg.child.age = "Ayşe", 5
    prompt = build_system_prompt(cfg)
    assert "Ayşe" in prompt and "5 yaşındaki" in prompt
    assert "FARKLI bir yol" in prompt


def test_load_config_from_yaml(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("child:\n  name: Ali\n  age: 7\naudio:\n  silence_seconds: 2\n", encoding="utf-8")
    cfg = load_config(p)
    assert cfg.child.name == "Ali" and cfg.audio.silence_seconds == 2
    assert cfg.assistant.model == "claude-opus-5-5"


# --- konuşma algılama ---

def _frames(level, seconds):
    n = int(16000 * FRAME_MS / 1000)
    for _ in range(int(seconds * 1000 / FRAME_MS)):
        yield (np.random.default_rng(0).standard_normal(n) * level).astype(np.int16)


def _run(ep, *segments):
    for level, secs in segments:
        for f in _frames(level, secs):
            state = ep.feed(f)
            if state != "continue":
                return state
    return "continue"


def test_endpointer_detects_utterance_end():
    ep = Endpointer(AudioConfig(silence_seconds=0.6), noise_floor=100)
    assert _run(ep, (50, 0.5), (3000, 1.0), (50, 1.0)) == "done"
    # ~1 sn konuşma + ön kayıt + 0.6 sn sessizlik
    assert 1.4 < len(ep.audio()) / 16000 < 2.2


def test_endpointer_times_out_without_speech():
    ep = Endpointer(AudioConfig(start_timeout_seconds=1.0), noise_floor=100)
    assert _run(ep, (50, 2.0)) == "timeout"


def test_endpointer_ignores_single_click():
    ep = Endpointer(AudioConfig(start_timeout_seconds=1.0), noise_floor=100)
    assert _run(ep, (3000, 0.03), (50, 2.0)) == "timeout"


# --- Claude sohbeti (sahte istemci ile) ---

class FakeStream:
    def __init__(self, chunks, stop_reason="end_turn"):
        self.text_stream = iter(chunks)
        self._final = SimpleNamespace(
            stop_reason=stop_reason,
            stop_details=None,
            content=[SimpleNamespace(type="text", text="".join(chunks))],
        )

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self._final


class FakeClient:
    def __init__(self, *streams):
        self.streams = list(streams)
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        s = self.streams.pop(0)
        if isinstance(s, Exception):
            raise s
        return s


def test_brain_streams_sentences_and_keeps_history():
    client = FakeClient(
        FakeStream(["Güneş bir yıl", "dızdır. Çok sıcak", "tır! Anladın mı?"]),
        FakeStream(["Hiç sorun değil. Bir de şöyle bakalım."]),
    )
    brain = Brain(Config(), client=client)
    assert list(brain.reply("Güneş ne?")) == ["Güneş bir yıldızdır.", "Çok sıcaktır!", "Anladın mı?"]
    assert list(brain.reply("anlamadım")) == ["Hiç sorun değil.", "Bir de şöyle bakalım."]

    second = client.calls[1]
    assert [m["role"] for m in second["messages"]] == ["user", "assistant", "user"]
    assert second["model"] == "claude-opus-5-5"
    assert second["fallbacks"] == "default"
    assert second["output_config"] == {"effort": "low"}


def test_brain_refusal_is_not_added_to_history():
    client = FakeClient(FakeStream([], stop_reason="refusal"))
    brain = Brain(Config(), client=client)
    assert list(brain.reply("...")) == [FALLBACK_REPLY]
    assert brain.messages == []


def test_brain_network_error_speaks_friendly_message():
    err = anthropic.APIConnectionError(request=SimpleNamespace(method="POST", url="x"))
    brain = Brain(Config(), client=FakeClient(err))
    assert list(brain.reply("merhaba")) == [ERROR_REPLY]
    assert brain.messages == []
