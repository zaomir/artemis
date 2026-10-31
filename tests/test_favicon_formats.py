"""favicon.ico is a real ICO (it used to be a byte copy of favicon-32x32.png); the PNG icons are PNGs."""
import struct
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class FaviconFormatTest(unittest.TestCase):
    def test_ico_is_ico_with_16_32_48(self):
        b = (STATIC / "favicon.ico").read_bytes()
        reserved, kind, count = struct.unpack("<HHH", b[:6])
        self.assertEqual((reserved, kind), (0, 1))                 # ICONDIR, type 1 = icon
        sizes = {struct.unpack("<BB", b[6 + 16 * i:8 + 16 * i]) for i in range(count)}
        self.assertTrue({(16, 16), (32, 32)} <= sizes, sizes)
        self.assertNotEqual(b, (STATIC / "favicon-32x32.png").read_bytes())

    def test_png_icons_are_png_of_their_size(self):
        for name, size in (("favicon-32x32.png", 32), ("favicon-192x192.png", 192), ("apple-touch-icon.png", 180)):
            b = (STATIC / name).read_bytes()
            self.assertEqual(b[:8], PNG_MAGIC, name)
            self.assertEqual(b[12:16], b"IHDR", name)
            self.assertEqual(struct.unpack(">II", b[16:24]), (size, size), name)


if __name__ == "__main__":
    unittest.main()
