import unittest

from timing_utils import format_elapsed


class FormatElapsedTests(unittest.TestCase):
    def test_formats_sub_minute_duration(self):
        self.assertEqual(format_elapsed(12.345), "12.3s")

    def test_formats_minutes_and_seconds(self):
        self.assertEqual(format_elapsed(125.2), "02m05.2s")

    def test_formats_hours_minutes_and_seconds(self):
        self.assertEqual(format_elapsed(3661.8), "01h01m01.8s")


if __name__ == "__main__":
    unittest.main()
