import { describe,it,vi,expect } from 'vitest'
import { fireEvent,render,screen } from '@testing-library/react'
import { LanguageProvider } from '@/components/i18n/LanguageProvider'
import { ShipmentRouteMap } from './ShipmentRouteMap'
import type { ShipmentDetail } from '@/contracts/caseDetail'
vi.mock('@/components/views/ExploreMap',()=>({ExploreMap:({visibleLayers,highlightedIds}:{visibleLayers:string[];highlightedIds:string[]})=><div data-testid="map" data-layers={visibleLayers.join(',')} data-ids={highlightedIds?.join(',')} />}))
const detail:ShipmentDetail={shipment_id:'SYN-1',evidence:{nodes:[],edges:[]},route_layers:{layers:{expected_route:[{segment_id:'SEG',points:[{lat:24,lng:46},{lat:25,lng:47}]}],custody_points:[{lat:24,lng:46,evidence_id:'CUSTODY'}],vehicle_path:[]}}}
describe('Stage-aware route evidence',()=>{
 it('highlights only provided references and disables missing telemetry rather than inventing a path',()=>{
  localStorage.setItem('agentx-language','en')
  render(<LanguageProvider><ShipmentRouteMap detail={detail} stage="classify" highlightedIds={['CUSTODY']} /></LanguageProvider>)
  expect(screen.getByTestId('map').getAttribute('data-ids')).toBe('CUSTODY')
  expect(screen.getByRole('button', { name: /Vehicle telemetry path/i }).hasAttribute('disabled')).toBe(true)
  expect(screen.getByRole('button', { name: /Traffic context/i }).getAttribute('aria-pressed')).toBe('false')
  fireEvent.click(screen.getByRole('button', { name: /Expected route \(plan\)/i }))
  expect(screen.getByTestId('map').getAttribute('data-layers')).not.toContain('expected_route')
 })
})
