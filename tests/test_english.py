"""Guard the English-only public source tree until localization is introduced."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class EnglishSourceTests(unittest.TestCase):
    def test_source_and_documentation_have_no_untranslated_cjk(self):
        paths = list(ROOT.glob('*.py')) + list(ROOT.glob('*.md'))
        paths += list((ROOT / 'static').glob('*')) + list((ROOT / 'tests').glob('test_*'))
        untranslated = []
        for path in paths:
            if path.is_file() and re.search(r'[\u3400-\u9fff]', path.read_text()):
                untranslated.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(untranslated, [])
