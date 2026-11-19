import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/recording'))
from creator_move_labels import parse_label


class DirectChargeLabelTests(unittest.TestCase):
    def test_effectiveness_text_does_not_erase_a_visible_move(self):
        value=dict(name='Drill Run',cost=45)
        for text in ['DRILL RUN','DRILLRUN SUPER EFFECTIVE','Drill Run Not Very Effective']:
            self.assertEqual(parse_label(text,.95,{'DRILLRUN':value}),value)

    def test_nonvocabulary_and_low_confidence_stay_unknown(self):
        vocabulary={'DIVE':dict(name='Dive',cost=40)}
        self.assertIsNone(parse_label('Drve',.99,vocabulary))
        self.assertIsNone(parse_label('DIVE',.7,vocabulary))
        self.assertIsNone(parse_label('AQUA TAIL DIVE',.99,vocabulary))


if __name__=='__main__':unittest.main()
