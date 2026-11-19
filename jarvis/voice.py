"""Ears and mouth: 'Hey Jarvis' wake word, speech-to-text, and the British voice."""
import collections
import queue
import random
import re
import subprocess
import threading
import time

import numpy as np
import sounddevice as sd

from . import config, timing

RATE = 16000
CHUNK = 1280  # 80 ms, what the wake word model expects
PRETRAINED = {"hey_jarvis", "alexa", "hey_mycroft", "hey_rhasspy"}


class Voice:
    def __init__(self):
        import openwakeword
        from openwakeword.model import Model

        self.wake = None
        if config.WAKE_WORD in PRETRAINED:
            openwakeword.utils.download_models([config.WAKE_WORD])
            self.wake = Model(wakeword_models=[config.WAKE_WORD], inference_framework="onnx")
        # any other wake word is spotted by transcribing what's said
        self.wake_re = re.compile(rf"\b(?:hey |ok |okay )?{config.WAKE_PATTERN}\b[,.!? ]*", re.I)
        self.noise = 200.0
        self.ducker = Ducker()
        self.echo_ratio: float | None = None  # how loud his own voice is in the mic, learned while speaking
        self.echo_samples: collections.deque = collections.deque(maxlen=300)
        # two ears: a small model on the processor listens for "Jarvis" all day (and hears every
        # TV or song in the room), so the big GPU model only runs on real commands and never
        # competes with the brain
        from faster_whisper import WhisperModel
        self.spotter = WhisperModel("base.en", device="cpu", compute_type="int8", cpu_threads=4)
        self._stt_lock = threading.Lock()  # one transcription at a time on the GPU
        self._transcribe([np.zeros(RATE, np.int16)])  # load the speech model now, not on first use
        self.audio: queue.Queue = queue.Queue()
        self.speaking = threading.Event()
        self._say: subprocess.Popen | None = None
        self.stream = sd.InputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=CHUNK,
                                     callback=lambda d, *_: self.audio.put(d[:, 0].copy()))
        self.stream.start()
        if "_" in config.VOICE:
            self._kokoro()  # load the voice now so the first reply isn't slow

    def _drain(self):
        while not self.audio.empty():
            self.audio.get_nowait()

    @staticmethod
    def _rms(chunk) -> float:
        return float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))

    def wait_for_wake_word(self) -> str:
        """Block until the wake word is heard. Returns anything said after it in
        the same breath (e.g. "Jarvis, lights off" returns "lights off")."""
        self._drain()
        if self.wake:
            self.wake.reset()
            while True:
                chunk = self.audio.get()
                if not self.speaking.is_set() and max(self.wake.predict(chunk).values()) > 0.5:
                    return ""
        preroll = collections.deque(maxlen=4)
        while True:
            chunk = self.audio.get()
            if self.speaking.is_set():
                continue
            level = self._rms(chunk)
            if level < max(self.noise * 2.5, 300):
                self.noise = self.noise * 0.95 + level * 0.05  # track background noise
                preroll.append(chunk)
                continue
            # someone is talking: capture the phrase and check it for the wake word
            frames, silent = [*preroll, chunk], 0
            while len(frames) * CHUNK / RATE < 8:
                c = self.audio.get()
                frames.append(c)
                silent = 0 if self._rms(c) > max(self.noise * 2.5, 300) else silent + 1
                if silent * CHUNK / RATE > 0.9:
                    break
            if not self.wake_re.search(self._spot(frames)):
                preroll.clear()
                continue
            # it's for us: now hear it properly with the accurate model
            self._save_clip(frames)
            text = self._transcribe(frames)
            m = self.wake_re.search(text)
            return text[m.end():].strip() if m else ""

    def _spot(self, frames) -> str:
        """Cheap transcription on the processor, just to spot the wake word."""
        audio = np.concatenate(frames).astype(np.float32) / 32768
        segments, _ = self.spotter.transcribe(audio, language="en", vad_filter=True, beam_size=1)
        return " ".join(s.text for s in segments)

    def _transcribe(self, frames) -> str:
        import mlx_whisper

        audio = np.concatenate(frames).astype(np.float32) / 32768
        if np.sqrt(np.mean(audio ** 2)) < 0.003:  # silence: skip (whisper invents words on silence)
            return ""
        with self._stt_lock, timing.step("hearing (speech to text)"):
            text = mlx_whisper.transcribe(audio, path_or_hf_repo=config.WHISPER_MODEL, language="en",
                                          condition_on_previous_text=False)["text"].strip()
        # whisper's stock phrases on noise
        return "" if text.lower().strip(" .!") in ("thank you", "thanks for watching", "you", "bye") else text

    def listen(self, max_seconds=15, silence_seconds=1.0, wait_seconds=5.0) -> str:
        """Record until the user stops talking, then transcribe."""
        self._drain()
        threshold = max(self.noise * 2.5, 300)  # background level learned while idle
        preroll = collections.deque(maxlen=5)  # 0.4 s before speech starts, so no clipped first word
        frames, silent, waited = [], 0, 0
        for _ in range(int((max_seconds + wait_seconds) * RATE / CHUNK)):
            chunk = self.audio.get()
            loud = self._rms(chunk) > threshold
            if not frames:
                if not loud:
                    preroll.append(chunk)
                    waited += 1
                    if waited * CHUNK / RATE > wait_seconds:
                        return ""  # nobody spoke
                    continue
                frames.extend(preroll)
            frames.append(chunk)
            silent = 0 if loud else silent + 1
            if silent * CHUNK / RATE > silence_seconds or len(frames) * CHUNK / RATE > max_seconds:
                break
        self._save_clip(frames)
        return self._transcribe(frames)

    def _save_clip(self, frames):
        """Keep the last few things said, locally, so mishearings can be diagnosed."""
        import wave

        d = config.DATA / "heard"
        d.mkdir(exist_ok=True)
        for old in sorted(d.glob("*.wav"))[:-4]:
            old.unlink()
        with wave.open(str(d / f"{time.strftime('%H%M%S')}.wav"), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE)
            w.writeframes(np.concatenate(frames).tobytes())

    def _kokoro(self):
        if not hasattr(self, "_tts"):
            from kokoro_onnx import Kokoro

            models = config.ROOT / "models"
            self._tts = Kokoro(str(models / "kokoro-v1.0.onnx"), str(models / "voices-v1.0.bin"))
        return self._tts

    def say(self, text: str) -> str | None:
        """Speak a whole reply. Returns a command if the user interrupted (see Utterance.wait)."""
        u = self.utterance()
        for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
            u.put(sentence)
        u.finish()
        return u.wait()

    def utterance(self) -> "Utterance":
        """Start speaking; feed sentences with .put() as they're ready, then .finish() and .wait()."""
        return Utterance(self)

    def acknowledge(self):
        """A short spoken "Sir?" when woken with no command, instead of a beep."""
        if "_" not in config.VOICE:
            subprocess.Popen(["afplay", "/System/Library/Sounds/Tink.aiff"])
            return
        if not hasattr(self, "_acks"):
            self._acks = [self._kokoro().create(t, voice=config.VOICE, speed=SPEED, lang="en-gb")[0]
                          for t in ("Sir?", "Yes?", "At your service.", "Listening.", "Yes, sir?")]
        self.speaking.set()
        try:
            sd.play(_smooth(random.choice(self._acks)), 24000)
            sd.wait()
        finally:
            self.speaking.clear()
            self._drain()

    def chime(self):
        subprocess.Popen(["afplay", "/System/Library/Sounds/Tink.aiff"])


SPEED = 0.95  # unhurried, as a butler should be
GAP = 0.35    # seconds of silence between sentences
# anything like this, said over JARVIS, makes him stop talking
STOP_WORDS = re.compile(r"\b(stop|stop talking|be quiet|quiet|shut up|enough|that's enough|hush|shush|silence|"
                        r"pause|hold on|hang on|wait|ok ok|okay okay)\b", re.I)


def _smooth(audio) -> np.ndarray:
    audio = np.asarray(audio, dtype=np.float32).copy()
    fade = min(len(audio), 480)  # 20 ms fade in/out removes clicks
    audio[:fade] *= np.linspace(0, 1, fade)
    audio[-fade:] *= np.linspace(1, 0, fade)
    return audio


class Ducker:
    """Turns Spotify / Apple Music down while JARVIS listens or talks, and back up after,
    so the music doesn't drown out the user (or get mistaken for them)."""
    APPS = ("Spotify", "Music")
    LEVEL = 12  # percent while ducked

    def __init__(self):
        self.saved: dict[str, int] = {}
        self.active = False
        self.lock = threading.Lock()
        self.unresponsive: set[str] = set()  # apps that didn't answer (e.g. permission not granted)

    def _osa(self, script: str, app: str = "") -> str:
        try:
            return subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=3).stdout.strip()
        except subprocess.TimeoutExpired:
            self.unresponsive.add(app)  # don't keep waiting on it this session
            return ""

    def duck(self):
        """Runs in the background, so a slow music app can never hold JARVIS up."""
        self.active = True
        threading.Thread(target=self._duck, daemon=True).start()

    def _duck(self):
        with self.lock:
            if not self.active:
                return
            self.active = True
            for app in self.APPS:
                if app in self.saved or app in self.unresponsive or \
                        subprocess.run(["pgrep", "-x", app], capture_output=True).returncode:
                    continue  # already ducked, not answering, or not running
                vol = self._osa(f'tell application "{app}" to get sound volume', app)
                if vol.isdigit() and int(vol) > self.LEVEL:
                    self.saved[app] = int(vol)
                    self._osa(f'tell application "{app}" to set sound volume to {self.LEVEL}', app)

    def refresh(self):
        """Catch music that started mid-conversation (e.g. "play some music")."""
        if self.active:
            self.duck()

    def restore(self):
        self.active = False
        threading.Thread(target=self._restore, daemon=True).start()

    def _restore(self):
        with self.lock:
            if self.active:  # a new conversation started meanwhile; stay ducked
                return
            for app, vol in self.saved.items():
                self._osa(f'tell application "{app}" to set sound volume to {vol}', app)
            self.saved.clear()


class Utterance:
    """One spoken reply. Sentences are voiced as they arrive, while the mic listens for
    "Jarvis, stop" (or "Jarvis, <new command>") to cut it short."""

    def __init__(self, voice: Voice):
        self.v = voice
        self.text: queue.Queue = queue.Queue()
        self.stop = threading.Event()
        self.done = threading.Event()
        self.interrupt: str | None = None
        self.said: list[str] = []  # what JARVIS has said, to tell his own echo from the user
        self.paused = threading.Event()  # set while the user is talking over him
        self.out_levels: collections.deque = collections.deque(maxlen=6)  # loudness of the last 0.6 s played
        voice.speaking.set()
        voice._drain()
        threading.Thread(target=self._play, daemon=True).start()
        threading.Thread(target=self._watch, daemon=True).start()

    def put(self, sentence: str):
        if sentence.strip():
            self.v.ducker.refresh()
            self.text.put(sentence.strip())

    def finish(self):
        self.text.put(None)

    def wait(self) -> str | None:
        """Block until speech ends. Returns None normally, or the command spoken over
        the top ("" for a plain "stop")."""
        self.done.wait()
        self.v.speaking.clear()
        self.v._drain()
        return self.interrupt

    def _play(self):
        try:
            if "_" not in config.VOICE:  # built-in macOS voice
                while (s := self.text.get()) is not None and not self.stop.is_set():
                    self.said.append(s)
                    p = subprocess.Popen(["say", "-v", config.VOICE, "-r", "175", s])
                    while p.poll() is None:
                        if self.stop.wait(0.05):
                            p.terminate()
                return
            tts = self.v._kokoro()
            audio_q: queue.Queue = queue.Queue(maxsize=3)

            def generate():  # prepares the next sentence while the current one plays
                while (s := self.text.get()) is not None and not self.stop.is_set():
                    self.said.append(s)
                    audio_q.put(_smooth(tts.create(s, voice=config.VOICE, speed=SPEED, lang="en-gb")[0]))
                audio_q.put(None)

            threading.Thread(target=generate, daemon=True).start()
            with sd.OutputStream(samplerate=24000, channels=1, dtype="float32") as out:
                while (audio := audio_q.get()) is not None:
                    audio = np.concatenate([audio, np.zeros(int(24000 * GAP), np.float32)])
                    i = 0
                    while i < len(audio):  # 0.1 s blocks so "stop" is instant
                        if self.stop.is_set():
                            return
                        if self.paused.is_set():  # the user is talking: hold still
                            self.out_levels.append(0.0)
                            out.write(np.zeros((2400, 1), np.float32))
                            continue
                        block = audio[i:i + 2400]
                        self.out_levels.append(float(np.sqrt(np.mean(block ** 2))) * 32768)
                        out.write(block[:, None])
                        i += 2400
                out.write(np.zeros((4800, 1), np.float32))  # let the last word ring out
        finally:
            self.done.set()

    def _watch(self):
        """Barge-in: the mic hears JARVIS's own voice, at a fairly steady ratio to how loud he's
        playing. When it's much louder than that ratio explains, someone is talking over him:
        pause, listen properly, then stop, take the new command, or carry on."""
        v = self.v
        preroll = collections.deque(maxlen=8)  # 0.64 s lead-in
        ambient = collections.deque(maxlen=40)  # room level in his pauses: music, TV, fans
        over = 0
        while not self.done.is_set():
            try:
                c = v.audio.get(timeout=0.2)
            except queue.Empty:
                continue
            level, playing = v._rms(c), max(self.out_levels, default=0.0)
            if self.out_levels and self.out_levels[-1] < 100:  # between his sentences: this is the room
                ambient.append(level)
            room = float(np.median(ambient)) if len(ambient) >= 3 else 0.0
            floor = max(v.noise * 2.5, 300, room * 2.5)  # steady background never counts as a person
            if v.echo_ratio is None:  # learn how much of his own voice the mic picks up
                if playing > 500:
                    v.echo_samples.append(level / playing)
                if len(v.echo_samples) >= 15:
                    v.echo_ratio = float(np.percentile(v.echo_samples, 90))
                preroll.append(c)
                continue
            expected = v.echo_ratio * playing
            if level > 1.8 * expected + floor:
                over += 1
            else:
                over = 0
                if playing > 500:  # keep learning the room; the loud end of the range, so echo never looks like a person
                    v.echo_samples.append(level / playing)
                    v.echo_ratio = float(np.percentile(v.echo_samples, 90))
                preroll.append(c)
            strong = level > 4 * expected + floor  # a short, sharp "Stop!"
            if over < 2 and not (over and strong):  # 0.16 s louder than his own voice explains
                continue
            # someone is talking over him: pause and hear them out
            self.paused.set()
            frames, silent, still_talking = [*preroll, c], 0, 0
            while len(frames) * CHUNK / RATE < 8:
                try:
                    c = v.audio.get(timeout=0.5)
                except queue.Empty:
                    break
                frames.append(c)
                if v._rms(c) > floor:
                    silent = 0
                    still_talking += 1  # his voice has stopped, so this is a person
                else:
                    silent += 1
                if silent * CHUNK / RATE > 0.8 or (not still_talking and silent * CHUNK / RATE > 0.5):
                    break
            heard = v._transcribe(frames)
            if config.DEBUG_VOICE:
                print("talked over, heard:", repr(heard), flush=True)
            # drop JARVIS's own words caught at the start; what's left is the user
            own = set(re.findall(r"[a-z']+", " ".join(self.said).lower()))
            mine = " ".join(w for w in re.findall(r"[a-z']+", heard.lower()) if w not in own or w == "jarvis")
            person = still_talking * CHUNK / RATE >= 0.25  # kept talking after he paused
            if (person and mine) or STOP_WORDS.search(mine) or v.wake_re.search(mine):
                # they're talking to him ("Jarvis" itself is often garbled under his own voice)
                full = v.wake_re.search(heard)
                if full:
                    rest = heard[full.end():]
                else:  # no clear "Jarvis": drop his own words caught at the start of the clip
                    words = heard.split()
                    while words and re.sub(r"[^a-z']", "", words[0].lower()) in own:
                        words.pop(0)
                    rest = " ".join(words)
                rest = rest.strip(" ,.")
                stop_only = STOP_WORDS.search(mine) and len(mine.split()) <= 4
                self.interrupt = "" if (not rest or stop_only) else rest
                self.stop.set()
                self.paused.clear()
                return
            over = 0  # a cough or a stray noise: carry on
            preroll.clear()
            self.paused.clear()
