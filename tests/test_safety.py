from types import SimpleNamespace
import unittest

from ptcg_ai.safety import emergency_selection, sanitize_selection


class SafetyTests(unittest.TestCase):
    def make_select(self, minimum, maximum, count, types=None):
        if types is None:
            types = [999] * count
        return SimpleNamespace(
            minCount=minimum,
            maxCount=maximum,
            option=[SimpleNamespace(type=t) for t in types],
        )

    def test_sanitize_removes_invalid_and_duplicates(self):
        select = self.make_select(2, 3, 4)
        self.assertEqual(sanitize_selection(select, [3, 3, -1, 8, 1], 2), [3, 1])

    def test_sanitize_fills_minimum(self):
        select = self.make_select(2, 3, 4)
        self.assertEqual(sanitize_selection(select, [], 0), [0, 1])

    def test_optional_emergency_is_empty(self):
        select = self.make_select(0, 3, 4)
        self.assertEqual(emergency_selection(select), [])


if __name__ == "__main__":
    unittest.main()

