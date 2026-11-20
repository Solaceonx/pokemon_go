import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/recording'))
from creator_announcements import parse_banner


class NativeReleaseBannerTests(unittest.TestCase):
    def record(self,text,y=0,confidence=.98):
        return dict(text=text,confidence=confidence,bounds=[0,y,300,y+30])

    def test_wrapped_release_requires_exact_named_legal_pair(self):
        pairs=(('Lapras','Sparkling Aria'),('Cramorant','Dive'))
        result=parse_banner([self.record('Lapras used'),self.record('Sparkling Aria!',40)],pairs)
        self.assertEqual((result['pokemon'],result['move']),('Lapras','Sparkling Aria'))
        self.assertIsNone(parse_banner([self.record('Lapras used Dive!')],pairs))

    def test_unrelated_low_confidence_or_conflicting_text_is_not_a_release(self):
        pairs=(('Lapras','Surf'),('Cramorant','Dive'))
        for records in [[self.record('Surf')],[self.record('Lapras used Surf',confidence=.8)],
                        [self.record('Lapras used'),self.record('Surf',200)],
                        [self.record('Lapras used Surf'),self.record('Cramorant used Dive',40)]]:
            self.assertIsNone(parse_banner(records,pairs))


if __name__=='__main__':unittest.main()
