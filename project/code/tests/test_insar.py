"""Checks for the LOS-to-vertical conversion and its radian guard."""
from pathlib import Path
import sys
import unittest
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from insar import vertical_rate


class VerticalRateTests(unittest.TestCase):
    def test_radian_incidence_projects_los_to_vertical(self):
        inc = np.array([0.52, 0.83])
        expected = np.array([2.0, -3.0]) / np.cos(inc)
        np.testing.assert_allclose(vertical_rate([2.0, -3.0], inc), expected)
        self.assertGreater(abs(vertical_rate([1.0], [0.83])[0]), 1.47)

    def test_degree_valued_incidence_is_rejected(self):
        with self.assertRaises(ValueError):
            vertical_rate([1.0, 1.0], [33.0, 47.5])

    def test_missing_incidence_is_rejected(self):
        with self.assertRaises(ValueError):
            vertical_rate([1.0, 1.0], [0.6, np.nan])


if __name__ == "__main__":
    unittest.main()
