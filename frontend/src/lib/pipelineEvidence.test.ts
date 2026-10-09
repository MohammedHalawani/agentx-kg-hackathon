import { describe,it,expect } from 'vitest'
import { stageEvidence } from './pipelineEvidence'
import type { ShipmentDetail } from '@/contracts/caseDetail'

describe('Stage-to-location graph provenance',()=>{
  it('traverses actual proof-to-attempt-to-address relationships, excluding disconnected positions',()=>{
    const detail:ShipmentDetail={shipment_id:'SYN-SHP',evidence:{nodes:[
      {id:'PROOF',kind:'DeliveryProof',properties:{}},{id:'ATTEMPT',kind:'DeliveryAttempt',properties:{}},
      {id:'ADDRESS',kind:'AddressVersion',properties:{}},{id:'UNRELATED',kind:'DeliveryAttempt',properties:{}},
    ],edges:[{id:'E1',kind:'HAS_PROOF',start:'ATTEMPT',end:'PROOF',properties:{}},{id:'E2',kind:'ATTEMPTED_AT',start:'ATTEMPT',end:'ADDRESS',properties:{}}]}}
    expect(stageEvidence(detail,'review')).toEqual(['PROOF','ATTEMPT','ADDRESS'])
    expect(stageEvidence(detail,'review')).not.toContain('UNRELATED')
  })
})
