"""Narrow public --prompt declaration admission; controlled non-private fixtures."""
import copy
import unittest
from studio.connectors.synthesis.evidence import admit
from studio.domain import Fault
from tests.synthesis_support import selection


class PromptDeclaration(unittest.TestCase):
    def selected(self, text):
        value = copy.deepcopy(selection())
        value['sources'][0]['excerpts'][0]['text'] = text
        return value

    def test_exact_technical_declaration_keeps_original_flag(self):
        value = self.selected('Argument 1 uses --prompt for direction.')
        self.assertEqual(admit(value), value)

    def test_private_or_extended_prompt_text_stays_excluded(self):
        for text in ('Private prompt contents.', 'Argument 1 uses --prompt for direction. Prompt contents.',
                     'Argument 1 uses --prompt-secret for direction.', 'Argument 1 uses --prompt for direction. Extra text.',
                     'Argument 1 uses --prompt for private direction.'):
            with self.subTest(case=text.split()[0]), self.assertRaises(Fault):
                admit(self.selected(text))
