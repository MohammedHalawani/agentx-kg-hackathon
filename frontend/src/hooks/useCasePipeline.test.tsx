import { afterEach,describe,it,vi,expect } from 'vitest'
import { act,renderHook } from '@testing-library/react'
import { useCasePipeline } from './useCasePipeline'
class RecordedStream extends EventTarget { static latest:RecordedStream; close=vi.fn(); onerror:()=>void=()=>{}; constructor(){super();RecordedStream.latest=this} }
afterEach(()=>vi.unstubAllGlobals())
describe('Real event stream state',()=>{
 it('refreshes an initial SSE version newer than a late case response only once',()=>{
  vi.stubGlobal('EventSource',RecordedStream)
  const refresh=vi.fn()
  const {rerender}=renderHook(({version})=>useCasePipeline('SYN-CASE',refresh,version),{initialProps:{version:undefined as number|undefined}})
  act(()=>RecordedStream.latest.dispatchEvent(new MessageEvent('pipeline',{data:JSON.stringify({state_version:3,status:'REVIEWED',workflow_state:'HUMAN_REVIEW',events:[]})})))
  expect(refresh).not.toHaveBeenCalled()
  rerender({version:2});expect(refresh).toHaveBeenCalledOnce()
  rerender({version:2});expect(refresh).toHaveBeenCalledOnce()
 })
 it('updates from committed server states without timers and closes on unmount',()=>{
  vi.stubGlobal('EventSource',RecordedStream)
  const refresh=vi.fn()
  const {result,unmount}=renderHook(()=>useCasePipeline('SYN-CASE',refresh))
  const send=(state_version:number,status:string)=>RecordedStream.latest.dispatchEvent(new MessageEvent('pipeline',{data:JSON.stringify({state_version,status,workflow_state:status==='RUNNING'?'INVESTIGATING':'HUMAN_REVIEW',events:[{stage:'retrieve',status,sequence:1}]})}))
  act(()=>send(2,'RUNNING'))
  expect(result.current.live?.events[0].status).toBe('RUNNING')
  expect(refresh).not.toHaveBeenCalled()
  act(()=>send(3,'COMPLETED'))
  expect(refresh).toHaveBeenCalledOnce()
  act(()=>RecordedStream.latest.onerror())
  expect(result.current.unavailable).toBe(true)
  unmount();expect(RecordedStream.latest.close).toHaveBeenCalledOnce()
 })
})
