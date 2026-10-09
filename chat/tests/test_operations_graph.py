"""Compiled topology, actual execution order, safe events and reversible identifiers."""
import copy
import json
import unittest
from dataset_v2.contracts import Config,canonical
from dataset_v2.generate import generate
from operations.reasoning import public_evidence
from operations.graph import investigate,topology
from operations.identifiers import public_value,storage_value

class OperationsGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world=generate(Config(total=90))
        case=next(n for n in cls.world.of_kind('Case') if n.properties['split']=='development')
        cls.context=public_evidence(cls.world,case.properties['shipment_id'],case.properties['opened_at'])

    def run_graph(self,**kwargs):
        seen=[]
        result,_=investigate(self.context['shipment_id'],self.context['as_of'],self.world.config,
            lambda *_:self.context,lambda *_:[],on_event=lambda event,events:seen.append(copy.deepcopy(event)),**kwargs)
        return result,seen

    def test_topology_is_compiled_and_matches_executed_stage_order(self):
        t=topology();result,seen=self.run_graph()
        self.assertEqual(t['nodes'],['extract','retrieve','classify','retrieve_context','recommend','review','writeback','escalate'])
        self.assertIn({'source':'review','target':'recommend','conditional':True},t['edges'])
        completed=[e['stage'] for e in seen if e['status']=='COMPLETED']
        self.assertEqual(completed,['extract','retrieve','classify','retrieve_context','recommend','review','writeback'])
        self.assertEqual([e['sequence'] for e in seen],list(range(1,len(seen)+1)))
        self.assertEqual(sorted(e['recorded_at'] for e in seen),[e['recorded_at'] for e in seen])
        self.assertIsNone(result['outcome'])

    def test_without_a_reviewer_there_is_no_rejection_and_no_scripted_proposal(self):
        result,events=self.run_graph()
        self.assertNotIn(('review','REJECTED'),[(e['stage'],e['status']) for e in events])
        self.assertNotIn('MARK_DELIVERED_FROM_GPS',canonical(result))

    def test_deterministic_guard_rejects_gps_delivery_certification(self):
        from operations.worker import review
        visible={'GPS-1','SCAN-1'};kinds={'GPS-1':'GPSObservation','SCAN-1':'ScanEvent'}
        gps_text={'action_code':'X','action':'Vehicle GPS confirms the parcel was delivered.','evidence_ids':['SCAN-1'],'requires_approval':True}
        gps_only={'action_code':'CONFIRM_DELIVERY','action':'Close as delivered.','evidence_ids':['GPS-1'],'requires_approval':True,'resolves':True}
        for proposal in (gps_text,gps_only):
            self.assertIn('GPS cannot establish',review(proposal,visible,kinds)['feedback'])
        ok={'action_code':'BARCODE_MISMATCH','action':'Rescan the package.','evidence_ids':['SCAN-1'],'requires_approval':True}
        self.assertEqual(review(ok,visible,kinds)['verdict'],'accept')

    def test_safe_event_outputs_exclude_arbitrary_source_reasoning(self):
        self.context=copy.deepcopy(self.context)
        self.context['nodes'][0]['properties']['chain_of_thought']='PRIVATE_ANALYSIS_SENTINEL'
        result,events=self.run_graph()
        self.assertNotIn('PRIVATE_ANALYSIS_SENTINEL',canonical(result))
        self.assertNotIn('chain_of_thought',canonical(events))
        known={n['id'] for n in self.context['nodes']}
        self.assertTrue(all(set(e['output'].get('evidence_ids',[]))<=known for e in events))

    def test_failure_is_recorded_without_private_exception_text(self):
        events=[]
        def fail(*_):raise RuntimeError('PRIVATE_TOKEN_SENTINEL')
        with self.assertRaises(RuntimeError):
            investigate(self.context['shipment_id'],self.context['as_of'],self.world.config,fail,lambda *_:[],
                on_event=lambda event,_:events.append(event))
        self.assertEqual(events[-1]['status'],'FAILED')
        self.assertNotIn('PRIVATE_TOKEN_SENTINEL',canonical(events))

    def test_public_identifier_roundtrip_preserves_links_cursors_and_request_keys(self):
        original={'shipment_id':'DEMO-SHP-001241','evidence_ids':['DEMO-X'],'next_cursor':'DEMO-opaque',
                  'token':'DEMO-capability','nested':{'start':'DEMO-X','end':'DEMO-Y'}}
        exposed=public_value(original)
        self.assertEqual(exposed['shipment_id'],'SYN-SHP-001241')
        self.assertEqual(exposed['nested'],{'start':'SYN-X','end':'SYN-Y'})
        self.assertEqual(exposed['next_cursor'],original['next_cursor'])
        self.assertEqual(exposed['token'],original['token'])
        self.assertEqual(storage_value({'case_id':'SYN-X','idempotency_key':'SYN-key','cursor':'SYN-opaque'}),
                         {'case_id':'DEMO-X','idempotency_key':'SYN-key','cursor':'SYN-opaque'})

if __name__=='__main__':unittest.main()
