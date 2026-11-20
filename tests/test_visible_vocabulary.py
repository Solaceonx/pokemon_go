import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts/recording'))
from visible_vocabulary import species_key, move_key, header_species_names, legal_release_pairs
from creator_identity import header_identity, fresh_cp_anchors
from creator_announcements import parse_banner
from creator_charge_evidence import actor_for_release
from native_controls import move_vocabulary
from creator_move_labels import parse_label
from assemble import nearest, public_announced_move
from score_creator_events import species_name
from evaluate_creator_fullstate import anchor_fields


class VisibleVocabularyTests(unittest.TestCase):
    def test_explicit_mega_form_is_equivalent_to_registered_name_but_not_base(self):
        self.assertEqual(species_key('Mega Houndoom'), species_key('Houndoom (Mega)'))
        self.assertNotEqual(species_key('Houndoom'), species_key('Mega Houndoom'))
        self.assertNotEqual(species_key('Charizard (Mega X)'), species_key('Mega Charizard Y'))
        self.assertEqual(species_name('Mega Charizard X'), species_name('Charizard (Mega X)'))

    def test_header_cannot_upgrade_base_species_without_explicit_form(self):
        names=header_species_names({'pokemon':[{'speciesName':'Houndoom'}, {'speciesName':'Houndoom (Mega)'}, {'speciesName':'Houndoom (Shadow)'}]})
        read=lambda text:header_identity([dict(text=text,confidence=.99)],names)
        self.assertEqual(read('Mega Houndoom CP1493')['species'],'Houndoom (Mega)')
        self.assertEqual(read('Houndoom CP1493')['species'],'Houndoom')
        self.assertIsNone(read('Stranger CP1493'))

    def test_cp_geometry_needs_observed_past_fresh_text(self):
        cp=dict(value=1493,status='observed',evidence=dict(observed_at_seconds=1,bounds_normalized_frame=[140,110,200,125]))
        context={'mine':{'cp':cp}}
        self.assertEqual(len(fresh_cp_anchors(context,1.5)),1)
        self.assertEqual(fresh_cp_anchors(context,.99),[])
        self.assertEqual(fresh_cp_anchors(context,1.91),[])
        cp['status']='contradictory'
        self.assertEqual(fresh_cp_anchors(context,1.5),[])

    def test_extra_move_vocabulary_comes_only_from_registered_species(self):
        gm=dict(pokemon=[dict(speciesName='Houndoom',chargedMoves=['CRUNCH']),
                         dict(speciesName='Houndoom (Mega)',chargedMoves=['CRUNCH'],extraChargedMoves=['DARK_PULSE_PLUS'])],
                moves=[dict(moveId='CRUNCH',name='Crunch'),dict(moveId='DARK_PULSE_PLUS',name='Dark Pulse+')])
        pairs=legal_release_pairs(gm)
        self.assertIn(('Houndoom (Mega)','Dark Pulse+'),pairs)
        self.assertNotIn(('Houndoom','Dark Pulse+'),pairs)
        self.assertEqual(actor_for_release('Mega Houndoom','Dark Pulse+',pairs)['name'],'Houndoom (Mega)')

    def test_banner_keeps_extra_move_suffix_and_registered_form(self):
        read=lambda text:dict(text=text,confidence=.99,bounds=[0,0,300,30])
        pairs=(('Houndoom (Mega)','Dark Pulse+'),)
        self.assertEqual(parse_banner([read('Mega Houndoom used Dark Pulse+!')],pairs)['move'],'Dark Pulse+')
        self.assertIsNone(parse_banner([read('Mega Houndoom used Dark Pulse!')],pairs))

    def test_move_matching_does_not_erase_enhanced_variant(self):
        for text in ('Dark Pulse+','DARKPULSE\uff0b!'):
            self.assertEqual(nearest(text,['Dark Pulse','Dark Pulse+']),'Dark Pulse+')
        self.assertEqual(nearest('Dark Pulse',['Dark Pulse','Dark Pulse+']),'Dark Pulse')
        self.assertEqual(public_announced_move('Dark Pulse+','Houndoom (Mega)'),'Dark Pulse+')
        self.assertIsNone(public_announced_move('Dark Pulse','Houndoom (Mega)'))

    def test_button_labels_with_different_costs_do_not_collide(self):
        vocab=move_vocabulary({'moves':[dict(name='Dark Pulse',energy=50),dict(name='Dark Pulse+',energy=40)]})
        self.assertEqual(vocab['DARKPULSE']['cost'],50)
        self.assertEqual(vocab['DARKPULSE+']['cost'],40)
        self.assertEqual(parse_label('Dark Pulse+ Not Very Effective',.99,vocab)['name'],'Dark Pulse+')
        self.assertNotEqual(move_key('Dark Pulse'),move_key('Dark Pulse+'))

    def test_state_grade_keeps_mega_distinct_from_regular_species(self):
        mon={'species':dict(value='Houndoom (Mega)',status='observed')}
        state={'sides':{'mine':dict(active='x',active_status='observed',pokemon={'x':mon})}}
        self.assertTrue(anchor_fields(state,dict(expected={'mine.species':'Mega Houndoom'}))[0]['correct'])
        mon['species']['value']='Houndoom'
        self.assertFalse(anchor_fields(state,dict(expected={'mine.species':'Mega Houndoom'}))[0]['correct'])


if __name__=='__main__':
    unittest.main()
