"""Exercise actual terminal behavior without using live credentials."""
import fcntl
import os
import pty
import select
import subprocess
import sys
import termios
import time
import unittest

from authorize_openlist import read_refresh_token
from unittest.mock import patch
import getpass


class HiddenInputTests(unittest.TestCase):
    def test_real_terminal_accepts_input_without_echo(self):
        master, slave = pty.openpty()

        def controlling_terminal():
            os.setsid()
            fcntl.ioctl(0, termios.TIOCSCTTY, 0)

        code = (
            "from authorize_openlist import read_refresh_token; "
            "value=read_refresh_token(); "
            "print('INPUT_OK' if value == 'synthetic-test-secret' else 'INPUT_BAD')"
        )
        process = subprocess.Popen(
            [sys.executable, "-c", code], stdin=slave, stdout=slave, stderr=slave,
            preexec_fn=controlling_terminal,
        )
        os.close(slave)
        output = b""
        sent = False
        deadline = time.monotonic() + 5
        try:
            while time.monotonic() < deadline:
                ready, _, _ = select.select([master], [], [], 0.1)
                if ready:
                    try:
                        chunk = os.read(master, 4096)
                    except OSError:
                        break
                    if not chunk:
                        break
                    output += chunk
                if not sent and b"(hidden): " in output:
                    os.write(master, b"synthetic-test-secret\n")
                    sent = True
            self.assertEqual(process.wait(timeout=1), 0)
            self.assertIn(b"INPUT_OK", output)
            self.assertNotIn(b"synthetic-test-secret", output)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            os.close(master)

    def test_echo_fallback_is_rejected(self):
        with patch("authorize_openlist.os.open", return_value=123), \
             patch("authorize_openlist.os.close"), \
             patch("authorize_openlist.getpass.getpass",
                   side_effect=getpass.GetPassWarning("cannot hide input")):
            with self.assertRaises(OSError):
                read_refresh_token()


if __name__ == "__main__":
    unittest.main()
