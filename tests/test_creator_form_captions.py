import copy
import json
from pathlib import Path
import tempfile
import unittest

from test_creator_forms import inputs
from creator_forms import collect, FormEvidence
from creator_form_captions import CAPTION, parse_caption, caption_rows, acquisition_windows, frame_time, preserve_cache_file


def reading(text=CAPTION, confidence=.96, bounds=(80,300,420,325)):
    return dict(text=text,confidence=confidence,bounds=list(bounds))


def witness(at, available):
    return dict(t=at,recognition_available_at_seconds=available,source_pts=round(at*30),
                source_time_base='1/30',caption_id='mimikyu_disguise_busted',confidence=.96)


class NativeFormCaptions(unittest.TestCase):
    def test_cache_history_stays_short_and_preserves_each_previous_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            prefix=Path(temporary).resolve()
            folder=prefix/('x'*max(1,169-len(str(prefix))))
            folder.mkdir()
            source=folder/'native-form-captions-6hz.jsonl.gz';source.write_bytes(b'first derived bytes')
            first=preserve_cache_file(source)
            self.assertLess(len(str(first)),260)
            self.assertGreater(len(str(folder/'form-caption-cache-history'/('a'*64+'-'+source.name))),260)
            self.assertEqual(first.read_bytes(),b'first derived bytes')
            self.assertEqual(preserve_cache_file(source),first)
            source.write_bytes(b'next derived bytes');second=preserve_cache_file(source)
            self.assertNotEqual(first,second)
            self.assertEqual(first.read_bytes(),b'first derived bytes')
            self.assertEqual(second.read_bytes(),source.read_bytes())
            self.assertEqual(len(json.loads((folder/'fh/manifest.json').read_text())),2)

    def test_changed_history_blob_stops_without_overwriting_original_or_history(self):
        with tempfile.TemporaryDirectory() as temporary:
            source=Path(temporary)/'cache.json';source.write_bytes(b'original derived bytes')
            blob=preserve_cache_file(source);blob.write_bytes(b'corrupted backup')
            with self.assertRaises(ValueError):preserve_cache_file(source)
            self.assertEqual(source.read_bytes(),b'original derived bytes')
            self.assertEqual(blob.read_bytes(),b'corrupted backup')

    def test_rounded_ocr_trigger_uses_exact_frame_time_without_epsilon(self):
        at=12.033307759
        clock={round(at,6):dict(clip_seconds=at,source_pts=361,source_time_base='1/30')}
        self.assertEqual(frame_time(12.033308,clock),at)
        self.assertEqual(frame_time(12.033309,clock),12.033309)
        rows=caption_rows([dict(t=12.033308,text=[['banner',CAPTION]])],alignment=clock)
        self.assertEqual(rows[0]['t'],at)
        self.assertEqual(rows[0]['recognition_available_at_seconds'],at)

    def test_buffer_trigger_can_align_only_to_the_same_source_frame(self):
        clock={12:dict(clip_seconds=12,source_pts=360,source_time_base='1/30'),
               13.033308:dict(clip_seconds=13.033307759,source_pts=391,source_time_base='1/30')}
        result=caption_rows([],[witness(12,13.033308)],alignment=clock)
        self.assertEqual(result[0]['recognition_available_at_seconds'],13.033307759)
        result=caption_rows([],[witness(12,13.033309)],alignment=clock)
        self.assertEqual(result[0]['recognition_available_at_seconds'],13.033309)

    def test_wrong_pts_timebase_or_missing_frame_cannot_supply_native_caption(self):
        clock={12:dict(clip_seconds=12,source_pts=360,source_time_base='1/30')}
        for change in (dict(source_pts=361),dict(source_time_base='1/60'),dict(t=12.1)):
            row=witness(12,13);row.update(change)
            self.assertFalse(caption_rows([],[row],alignment=clock))

    def test_native_and_regular_sampling_merge_on_physical_frame_clock(self):
        at=12.033307759
        clock={12.033308:dict(clip_seconds=at,source_pts=361,source_time_base='1/30')}
        row=witness(at,13);row['source_pts']=361
        merged=caption_rows([dict(t=12.033308,text=[['banner',CAPTION]])],[row],alignment=clock)
        self.assertEqual(len(merged),1)
        self.assertEqual(merged[0]['recognition_available_at_seconds'],at)

    def test_exact_frame_confirmation_is_available_at_that_snapshot(self):
        args=inputs();at=13.033307759
        clock={12:dict(clip_seconds=12,source_pts=360,source_time_base='1/30'),
               round(at,6):dict(clip_seconds=at,source_pts=391,source_time_base='1/30')}
        second=witness(at,13.033308);second['source_pts']=391
        args[0]=caption_rows([],[witness(12,12),second],alignment=clock)
        event=collect(*args)['events'][0]
        self.assertEqual(event['confirmed_at_seconds'],at)
        evidence=FormEvidence([event])
        evidence.advance(at,{'mine':{'pokemon':{}},'opponent':{'pokemon':{}}})
        self.assertEqual(len(evidence.pending),1)

    def test_only_exact_complete_literal_is_retained(self):
        self.assertEqual(parse_caption([reading()])['caption_id'],'mimikyu_disguise_busted')
        for text in ('BLOCKED!', "Mimikyu's disguise", 'PrivateTrainerExample',
                     "Othermon's disguise is busted!", CAPTION+' other text'):
            self.assertIsNone(parse_caption([reading(text)]))
        self.assertNotIn('text',parse_caption([reading()]))

    def test_two_spatially_adjacent_lines_can_form_one_literal(self):
        a=reading("Mimikyu's disguise",bounds=(80,300,420,325))
        b=reading('is busted!',bounds=(150,330,350,355))
        self.assertEqual(parse_caption([b,a])['bounds'],[80,300,420,355])
        for bounds in ((150,400,350,425),(450,330,500,355)):
            self.assertIsNone(parse_caption([a,reading('is busted!',bounds=bounds)]))

    def test_each_caption_line_needs_strong_confidence(self):
        self.assertIsNone(parse_caption([reading(confidence=.89)]))
        self.assertIsNone(parse_caption([reading("Mimikyu's disguise"),
            reading('is busted!',confidence=.89,bounds=(150,330,350,355))]))

    def test_same_frame_from_native_and_regular_sampling_counts_once(self):
        text=[dict(t=12.0000001,text=[['banner',CAPTION]])]
        merged=caption_rows(text,[witness(12.0000002,13)])
        self.assertEqual(len(merged),1)
        self.assertEqual(merged[0]['recognition_available_at_seconds'],12)
        args=inputs();args[0]=merged
        self.assertFalse(collect(*args)['events'])

    def test_distinct_native_frames_can_supply_repeated_caption(self):
        args=inputs();args[0]=caption_rows([],[witness(12,14),witness(12.2,14)])
        event=collect(*args)['events'][0]
        self.assertEqual(event['source_observation_seconds'],[12,12.2])
        self.assertEqual(event['confirmed_at_seconds'],14)
        self.assertEqual(event['source_availability_seconds'],[14,14])
        self.assertEqual(len(FormEvidence([event]).events),1)

    def test_future_recognition_cannot_be_exposed_at_frame_time(self):
        args=inputs();args[0]=caption_rows([],[witness(12,15),witness(12.2,15)])
        event=collect(*args)['events'][0]
        evidence=FormEvidence([event]);evidence.advance(14.99,{'mine':{'pokemon':{}},'opponent':{'pokemon':{}}})
        self.assertFalse(evidence.pending)
        evidence.advance(15,{'mine':{'pokemon':{}},'opponent':{'pokemon':{}}})
        self.assertEqual(len(evidence.pending),1)

    def test_bad_frame_witnesses_cannot_supply_proof(self):
        for change in (dict(recognition_available_at_seconds=11),dict(source_pts=True),
                       dict(source_time_base='0'),dict(source_time_base='1/0'),dict(confidence=.89),
                       dict(caption_id='other'),dict(t=float('nan'))):
            row=witness(12,13);row.update(change)
            self.assertFalse(caption_rows([],[row]),change)

    def test_altered_availability_is_rejected_when_loading_event(self):
        event=collect(*inputs())['events'][0]
        for availability in ([11,13],[12,14],[12],[12,False],[12,float('nan')]):
            changed=copy.deepcopy(event);changed['source_availability_seconds']=availability
            self.assertFalse(FormEvidence([changed]).events,availability)

    def test_shield_known_by_delayed_recognition_still_blocks_form(self):
        args=inputs();args[0]=caption_rows([],[witness(12,15),witness(12.2,15)])
        args[2][0].update(shielded=True,shield_confirmed_at_seconds=14)
        self.assertFalse(collect(*args)['events'])

    def test_release_window_uses_observed_target_and_release_knowledge_time(self):
        args=inputs();args[1]['charged'][0]['t']=9
        args[3][0]['t']=8.5;args[3][0]['values']['theirs']['confirmed_seconds']=8.5
        args[2][0]['confirmed_at_seconds']=11
        windows=acquisition_windows([],args[1],args[2],args[3])
        self.assertEqual(windows,[dict(start=10,end=18,available=11)])
        args[3][0]['values']['theirs']['species']='Othermon'
        self.assertFalse(acquisition_windows([],args[1],args[2],args[3]))

    def test_future_or_old_header_cannot_trigger_release_buffer(self):
        args=inputs();args[1]['charged'][0]['t']=9
        for header in (9.1,6.9):
            args[3][0]['t']=header
            self.assertFalse(acquisition_windows([],args[1],args[2],args[3]))

    def test_caption_lookback_is_available_only_at_trigger(self):
        windows=acquisition_windows([dict(t=12,text=[['banner',CAPTION],['header','PrivateTrainerExample']])],{},[],[])
        self.assertEqual(windows,[dict(start=11.5,end=12.5,available=12)])
        self.assertNotIn('PrivateTrainerExample',str(windows))
