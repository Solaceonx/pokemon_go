import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/recording'))
from creator_identity import header_identity, split_header_reading, measure_identity


class HeaderTokens(unittest.TestCase):
    def records(self,name='Azumaril',cp_conf=.95,name_conf=.95):
        return [dict(text='CP1499',confidence=cp_conf),dict(text=name,confidence=name_conf)]

    def test_whole_line_default_remains_exact(self):
        self.assertIsNone(header_identity(self.records(),['Azumarill']))
        self.assertEqual(header_identity(self.records('Azumarill'),['Azumarill'])['species'],'Azumarill')

    def test_one_missing_doubled_letter_requires_explicit_recovery_and_unique_vocabulary(self):
        read=header_identity(self.records(),['Azumarill'],allow_collapsed_double=True)
        self.assertEqual((read['species'],read['cp']),('Azumarill',1499))
        self.assertIn('unique_collapsed_double',read['method'])
        self.assertIsNone(header_identity(self.records(),['Azumarill','Azzumaril'],allow_collapsed_double=True))

    def test_arbitrary_edits_extra_letters_and_multiple_omissions_are_rejected(self):
        for text in ['Azmarill','Azumeril','Azumari','Azummarrill']:
            self.assertIsNone(header_identity(self.records(text),['Azumarill'],allow_collapsed_double=True))

    def test_either_low_confidence_token_prevents_recovery(self):
        for a,b in [(.89,.99),(.99,.89)]:
            self.assertIsNone(header_identity(self.records(cp_conf=a,name_conf=b),['Azumarill'],allow_collapsed_double=True))

    def optional_pixels(self):
        try:
            import cv2,numpy as np
            if not hasattr(cv2,'cvtColor'):self.skipTest('optional video dependencies unavailable')
        except ImportError:self.skipTest('optional video dependencies unavailable')
        return cv2,np

    def test_empty_pixels_do_not_call_recognizer_or_manufacture_header(self):
        _,np=self.optional_pixels()
        def forbidden(*args,**kwargs):self.fail('Recognizer called without measured text/header geometry')
        image=np.full((1080,508,3),245,dtype=np.uint8)
        self.assertIsNone(split_header_reading(image,[0,70,200,130],forbidden,['Azumarill']))
        self.assertEqual(measure_identity(image,forbidden,['Azumarill']),dict(mine=None,theirs=None))

    def test_separate_text_regions_keep_original_confidence_floor_and_typed_method(self):
        cv2,np=self.optional_pixels()
        image=np.full((1080,508,3),245,dtype=np.uint8)
        cv2.rectangle(image,(10,80),(25,92),(60,60,60),-1)
        cv2.rectangle(image,(150,80),(190,92),(60,60,60),-1)
        reads=iter([[['CP1499',.95]],[['Azumaril',.95]]])
        read=split_header_reading(image,[0,70,200,130],lambda *a,**k:(next(reads),None),['Azumarill'])
        self.assertEqual(read['species'],'Azumarill')
        self.assertIn('separate_tokens_unique_collapsed_double',read['method'])
