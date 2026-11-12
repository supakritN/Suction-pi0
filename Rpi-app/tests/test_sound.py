import socket
import tempfile
import time
import unittest
import wave
from pathlib import Path

from app import cough_wav, sound


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class CoughWavTest(unittest.TestCase):
    def test_writes_a_short_mono_wav(self):
        with tempfile.TemporaryDirectory() as d:
            p = cough_wav.write(Path(d) / "c.wav")
            with wave.open(str(p)) as w:
                self.assertEqual((w.getnchannels(), w.getframerate()), (1, cough_wav.RATE))
                self.assertTrue(0.4 < w.getnframes() / w.getframerate() < 1.0)


class SoundOutTest(unittest.TestCase):
    def test_off_mode_does_nothing(self):
        self.assertFalse(sound.SoundOut("off", play_cmd=[]).cough())

    def test_repeat_within_interval_is_dropped(self):
        s = sound.SoundOut("local", play_cmd=[])
        self.assertTrue(s.cough())
        self.assertFalse(s.cough())

    def test_remote_listener_gets_the_event(self):
        port = free_port()
        s = sound.SoundOut("remote", port=port, play_cmd=[])
        try:
            c = socket.create_connection(("127.0.0.1", port), timeout=2)
            time.sleep(0.2)          # let the accept thread register the client
            self.assertTrue(s.cough())
            c.settimeout(2)
            self.assertEqual(c.recv(64), b"cough\n")
            c.close()
        finally:
            s.close()


if __name__ == "__main__":
    unittest.main()
