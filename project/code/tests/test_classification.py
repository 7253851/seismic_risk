"""Meaningful checks for Jenks optimization, ties and interval boundaries."""
import itertools
from pathlib import Path
import sys
import unittest
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from classification import classify, jenks_breaks


class ClassificationTests(unittest.TestCase):
    def test_jenks_matches_exhaustive_partition(self):
        values = np.array([0, 0, 1, 3, 9, 10, 20, 21], dtype=float)
        breaks = jenks_breaks(values, classes=3)
        assigned = classify(values, breaks, ["A", "B", "C"])
        actual = sum(((values[assigned == name] - values[assigned == name].mean()) ** 2).sum()
                     for name in ["A", "B", "C"])
        expected = min(sum(((group - group.mean()) ** 2).sum() for group in np.split(values, cuts))
                       for cuts in itertools.combinations(range(1, len(values)), 2))
        self.assertAlmostEqual(actual, expected)

    def test_upper_inclusive_edges_and_invalid_values(self):
        values = pd.Series([0, 1, 1.01, 2, 3, 4, 5, np.nan, np.inf, -1], index=range(10, 20))
        labels = classify(values, [0, 1, 2, 3, 4, 5])
        self.assertEqual(labels.tolist(), ["Very Low", "Very Low", "Low", "Low", "Moderate", "High", "Very High", "Invalid", "Invalid", "Invalid"])
        self.assertTrue(labels.index.equals(values.index))

    def test_deterministic_representatives_preserve_extremes(self):
        values = np.linspace(0, 1, 10001) ** 3
        breaks = jenks_breaks(values, max_values=100)
        self.assertEqual(breaks, jenks_breaks(values, max_values=100))
        self.assertEqual((breaks[0], breaks[-1]), (0, 1))
        self.assertFalse(classify(values, breaks).eq("Invalid").any())

    def test_too_few_values_rejected(self):
        with self.assertRaises(ValueError):
            jenks_breaks([1, 1, 2], classes=5)


if __name__ == "__main__":
    unittest.main()
