import copy
import unittest
from unittest.mock import patch

import test_native_health as physical
import native_health as nh


class RecentHealthGeometry(unittest.TestCase):
    def setUp(self):
        self.pixels=physical.PhysicalPixels();self.pixels.setUp()
        self.old=self.pixels.frame();self.pixels.bar(self.old,120)
        self.previous=dict(t=.9,health=nh.measure_frame(self.old,154))
        self.current=self.pixels.frame();self.pixels.bar(self.current,50)

    def missing_contours(self,image,previous=None,at=1):
        # Only proposal extraction is unavailable. Rail/color proofs use real pixels.
        with patch.object(nh,'candidates',return_value=[]),patch.object(nh,'positive_fallback_candidates',return_value=[]):
            return nh.measure_with_recent_geometry(image,154,[self.previous] if previous is None else previous,at)

    def test_current_pixels_change_health_instead_of_carrying_old_value(self):
        value=self.missing_contours(self.current)['mine']['bar']
        lo,hi=value['fraction_interval']
        self.assertLessEqual(lo,50/148);self.assertGreaterEqual(hi,50/148)
        self.assertLess(hi,.5)
        self.assertEqual(value['geometry_proposal']['observed_at_seconds'],.9)
        self.assertFalse(value['geometry_proposal']['value_carried'])

    def test_future_same_time_stale_or_invalid_history_is_withheld(self):
        for at in (1,1.01,.749,float('nan'),True):
            previous=copy.deepcopy(self.previous);previous['t']=at
            self.assertEqual(self.missing_contours(self.current,[previous])['mine']['status'],'not_visible')
        previous=copy.deepcopy(self.previous);previous['t']=.75
        self.assertEqual(self.missing_contours(self.current,[previous])['mine']['status'],'observed')

    def test_no_history_cannot_supply_geometry(self):
        self.assertEqual(self.missing_contours(self.current,[])['mine']['status'],'not_visible')

    def test_current_outline_is_required_even_with_previous_positive_health(self):
        image=self.pixels.frame();image[603:611,33:83]=[0,240,170]
        self.assertEqual(self.missing_contours(image)['mine']['status'],'not_visible')

    def test_cannot_introduce_an_empty_bar_or_faint(self):
        image=self.pixels.frame();self.pixels.bar(image,0)
        self.assertEqual(self.missing_contours(image)['mine']['status'],'not_visible')
        self.assertEqual(self.missing_contours(self.pixels.frame())['mine']['status'],'not_visible')

    def test_short_or_wrong_side_geometry_cannot_attribute_a_reading(self):
        short=copy.deepcopy(self.previous);short['health']['mine']['bar']['bounds'][2]-=20
        self.assertEqual(self.missing_contours(self.current,[short])['mine']['status'],'not_visible')
        wrong=copy.deepcopy(self.previous);wrong['health']['theirs']=wrong['health']['mine']
        wrong['health']['mine']=dict(status='not_visible',bar=None)
        self.assertEqual(self.missing_contours(self.current,[wrong])['theirs']['status'],'not_visible')

    def test_small_translation_revalidates_new_rectangle(self):
        image=self.pixels.np.roll(self.pixels.np.roll(self.current,2,axis=1),-2,axis=0)
        value=self.missing_contours(image)['mine']
        self.assertEqual(value['status'],'observed')
        self.assertLess(value['bar']['fraction_interval'][1],.5)

    def test_existing_current_measurement_keeps_priority(self):
        current=nh.measure_frame(self.current,154)
        self.assertEqual(nh.measure_with_recent_geometry(self.current,154,[self.previous],1),current)

    def test_existing_ambiguity_is_not_resolved_using_a_previous_position(self):
        image=self.current+self.pixels.np.roll(self.current,50,axis=0)
        baseline=nh.measure_frame(image,154)
        self.assertEqual(baseline['mine']['status'],'ambiguous')
        self.assertEqual(nh.measure_with_recent_geometry(image,154,[self.previous],1),baseline)

    def test_two_current_valid_rectangles_remain_ambiguous(self):
        second=self.pixels.np.roll(self.old,50,axis=0)
        previous=[self.previous,dict(t=.85,health=nh.measure_frame(second,154))]
        image=self.current+self.pixels.np.roll(self.current,50,axis=0)
        value=self.missing_contours(image,previous)['mine']
        self.assertEqual(value['status'],'ambiguous');self.assertIsNone(value['bar'])
        self.assertEqual(value['candidate_count'],2)

    def test_damage_pixels_do_not_extend_current_live_prefix(self):
        image=self.pixels.frame();self.pixels.bar(image,50,30)
        value=self.missing_contours(image)['mine']['bar']
        self.assertLessEqual(value['live_pixels'],52)
        self.assertGreater(value['damage_pixels'],25)

    def test_charged_closeup_prevents_side_proposals(self):
        baseline=nh.measure_frame(self.current,154)
        baseline['mine']=dict(status='not_visible',bar=None)
        baseline['center']=dict(status='observed',bar=copy.deepcopy(self.previous['health']['mine']['bar']))
        with patch.object(nh,'measure_frame',return_value=baseline):
            self.assertEqual(nh.measure_with_recent_geometry(self.current,154,[self.previous],1),baseline)
