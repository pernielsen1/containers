import unittest

from util_convert import UtilConvert


class TestUtilConvert(unittest.TestCase):
    def test_ascii_passthrough(self):
        self.assertEqual(UtilConvert.utf8_to_iso8859_2("Hello, world!"), "Hello, world!")

    def test_control_characters_become_space(self):
        self.assertEqual(UtilConvert.utf8_to_iso8859_2("A\tB\nC\rD"), "A B C D")

    def test_central_european_letters(self):
        source = "Łódź, Žižek, Škoda, Čapek"
        expected = "Łódź, Žižek, Škoda, Čapek"
        self.assertEqual(UtilConvert.utf8_to_iso8859_2(source), expected)

    def test_best_fit_fallback(self):
        source = "Æther – café ™"
        expected = "Ather - café T"
        self.assertEqual(UtilConvert.utf8_to_iso8859_2(source), expected)

    def test_output_length_is_preserved(self):
        source = "Æ–©™☃"
        result = UtilConvert.utf8_to_iso8859_2(source)
        self.assertEqual(len(result), len(source))
        self.assertEqual(result, "A-cT?")

    def test_none_returns_empty_string(self):
        self.assertEqual(UtilConvert.utf8_to_iso8859_2(None), "")


if __name__ == "__main__":
    unittest.main()
