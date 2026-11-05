"""The optimized hot validator must accept exactly the old JSON identifier set."""
from __future__ import annotations

import random
import unittest

from agda_evidence.core import EvidenceError, _digest_identifier


def legacy(value, field):
    if not isinstance(value, str) or not value.startswith('sha256:'):
        raise EvidenceError(f'{field} must be a sha256 identifier')
    digest = value.removeprefix('sha256:')
    if len(digest) != 64 or any(character not in '0123456789abcdef' for character in digest):
        raise EvidenceError(f'{field} must be a lowercase sha256 identifier')
    return value


def outcome(fn, value):
    try:
        return ('ok', fn(value, 'subject'))
    except EvidenceError as error:
        return ('error', str(error))


class DigestValidationTests(unittest.TestCase):
    def test_valid_lowercase_ascii_identifiers_return_original_object(self):
        for text in ['0'*64, 'f'*64, '0123456789abcdef'*4]:
            value = 'sha256:' + text
            self.assertIs(_digest_identifier(value, 'subject'), value)

    def test_rejected_shapes_suffixes_unicode_and_error_categories_match(self):
        valid = 'sha256:'+'a'*64
        cases = [None, True, 1, {}, [], b'sha256:'+b'a'*64, '', 'SHA256:'+'a'*64,
                 'sha256', 'sha256:', 'sha256:'+'a'*63, 'sha256:'+'a'*65,
                 ' sha256:'+'a'*64, valid+'\n', valid+'\r\n', valid+' ', valid+'\x00',
                 valid+'sha256:', 'sha256:'+'A'*64, 'sha256:'+'g'+'a'*63,
                 'sha256:'+'ａ'*64, 'sha256:'+'٠'*64, 'sha256:'+'a'*63+'\ud800',
                 'sha256:'+'a'*63+'\u2028', 'sha256:'+'a'*63+'\t']
        for value in cases:
            with self.subTest(value=repr(value)):
                self.assertEqual(outcome(_digest_identifier,value),outcome(legacy,value))
                self.assertEqual(outcome(_digest_identifier,value)[0],'error')

    def test_differential_seeded_mutations_and_valid_identifiers(self):
        randomizer = random.Random(1405)
        pool = '0123456789abcdefABCDEFgx\n\r\t\x00 éｆ٠\u2028'
        for number in range(2500):
            digest = ''.join(randomizer.choice('0123456789abcdef') for _ in range(64))
            if number % 4 == 0:
                value = 'sha256:' + digest
            elif number % 4 == 1:
                position = randomizer.randrange(64)
                value = 'sha256:' + digest[:position]+randomizer.choice(pool)+digest[position+1:]
            elif number % 4 == 2:
                value = 'sha256:' + ''.join(randomizer.choice(pool) for _ in range(randomizer.randrange(58,72)))
            else:
                value = randomizer.choice(['sha256:', 'SHA256:', 'sha256 :', '', 'sha256:sha256:'])+digest+randomizer.choice(['','\n',' '])
            with self.subTest(number=number):
                self.assertEqual(outcome(_digest_identifier,value),outcome(legacy,value))

    def test_each_call_revalidates_without_previous_acceptance_authority(self):
        value = 'sha256:'+'0'*64
        self.assertEqual(_digest_identifier(value,'one'),value)
        with self.assertRaisesRegex(EvidenceError,'two must be a lowercase sha256 identifier'):
            _digest_identifier(value+'\n','two')
        self.assertEqual(_digest_identifier(value,'three'),value)


if __name__ == '__main__':
    unittest.main()
