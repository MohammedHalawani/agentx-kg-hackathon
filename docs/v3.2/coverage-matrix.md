# V3.2 case coverage — 136 scenarios, 12 families

Catalogue presence, source availability, investigatability, action support and verified lifecycle are distinct. No live model accuracy is claimed. This catalogue is not a shipment answer key.

All 136 titles and evidence/response descriptions are retained verbatim in `case-taxonomy.json`, with the original source hash. Priorities cover twelve scenarios; all other rows remain catalogued, with implementation unassessed rather than implied complete.

`Source partial` means the frozen world has relevant source kinds and bounded tools, not that a curated shipment proves that scenario. The source-backed 000064/000194 reference checks use saved visible records and do not assume a preferred cause. Test-world response events are explicitly synthetic and do not alter that bundle.

| Priority | Case | Alternatives | Action | Verification / current limit | Controlled lifecycle |
|---|---|---|---|---|---|
| 1 | S03 Barcode misread | Compare optical error with wrong label/parcel and duplicate identity. | REQUEST_RESCAN | Independent high-quality, package/facility-bound matching read; clear remaining exceptions. | tested; safety boundaries included |
| 2 | S04 Wrong label on parcel | Repeated mismatch can mean wrong label or wrong physical parcel; neither is established by one read. | REQUEST_RESCAN | Continued mismatch remains unresolved; identity disposition needs authorized review. | tested; safety boundaries included |
| 3 | C03 Driver returns, one parcel isn't scanned back | Unrecorded return, retained parcel, buffered scan or incomplete load evidence. | INITIATE_CUSTODY_RECONCILIATION | Corroborated stock/custody check plus original gaps addressed; session-end policy floor remains human. | not extended |
| 4 | C04 Handover between drivers unrecorded | Missing observation versus unconfirmed handover versus contradictory possession. | INITIATE_CUSTODY_RECONCILIATION | New independent source/corroborated custody at directed location; no invented historical handover. | tested; safety boundaries included |
| 5 | D02 Records created offline, uploaded later | Buffered original observation versus genuinely absent event or wrong device. | REQUEST_DEVICE_SYNC | Exact missing package observations received from target device, original occurrence time, validated provenance. | tested; safety boundaries included |
| 6 | D11 Same device affects many shipments | Common device outage versus multiple unrelated parcel exceptions. | REQUEST_DEVICE_SYNC | Verify each affected shipment separately; incident-wide deduplication is deferred. | not extended |
| 7 | P01 Parcel delivered, tracking still says in transit | Valid delayed proof versus stale status or genuinely incomplete delivery. | REQUEST_ADDITIONAL_EVIDENCE | Authoritative bound proof and read-model agreement; no vehicle-GPS substitution. | not extended |
| 8 | P11 Delivery proof belongs to another shipment | Proof association error versus disputed delivery. | REQUEST_ADDITIONAL_EVIDENCE | Correct package/attempt/recipient-bound proof; foreign proof cannot resolve. | not extended |
| 9 | W04 Package placed in wrong container | Mis-sort versus incorrect container membership or stale manifest. | REQUEST_HUB_CHECK, REROUTE_TO_CONFIRMED_DESTINATION | New physical receiving/location evidence; operational reroute retains approval. | not extended |
| 10 | G08 Vehicle appears near address, no delivery evidence | Vehicle near address versus independent parcel handover; GPS uncertainty remains. | REQUEST_ADDITIONAL_EVIDENCE | Parcel-bound proof, never proximity alone. | not extended |
| 11 | Q01 Weight differs from declaration | Scale error versus declaration error or real integrity discrepancy. | REQUEST_REWEIGH | Independent calibrated package-bound measurement within policy tolerances. | not extended |
| 12 | R01 Customer says not delivered; valid proof exists | Carrier proof and recipient nonreceipt are attributed competing evidence. | DELIVERY_DISPUTE_REVIEW | Authorized human finding with policy-required evidence; no automatic dismissal. | not extended |

## How far each priority scenario actually goes

Four separate levels. A scenario at one level is not implied to reach the next.

- **Classified**: catalogued with alternatives and a mapped action. All 12.
- **Source evidence**: the frozen world contains the relevant source kinds (`source-inventory.json`) and bounded tools can read them. Recorded as `partial` for all 12 by the original V3.2 author; no curated shipment is claimed to prove any of them.
- **Action support**: an action code with an authority rule and a verifier rule for its effect. All 12 (DELIVERY_DISPUTE_REVIEW is a human-authority action with no automatic verifier).
- **Verified end to end**: request, synthetic operational responses, actual verifier and closure code run in the controlled in-memory store (`offline-evaluation.json` case traces). Not the frozen world, not Neo4j, not a live model.

| Priority | Case | Verified end to end | What the trace shows |
|---|---|---|---|
| 1 | S03 Barcode misread | **Yes, resolved** | Independent matching rescan from a different device → action VERIFIED → case VERIFIED_RESOLVED. |
| 2 | S04 Wrong label on parcel | Negative path only | Rescan still differs → VERIFIED_FAILURE → case stays UNRESOLVED. No resolution path is claimed. |
| 3 | C03 Driver returns, one parcel not scanned back | No | Action and verifier exist; no trace. |
| 4 | C04 Handover between drivers unrecorded | Action verified, case **not** resolved | New corroborated stock check verifies the request; the unconfirmed original handover remains, so the case stays UNRESOLVED (HUMAN_REVIEW). |
| 5 | D02 Records created offline, uploaded later | **Yes, resolved** | Original records from the targeted device arrive after the request → VERIFIED → VERIFIED_RESOLVED. Healthy-device, GPS-only and wrong-device variants stay pending. |
| 6 | D11 Same device affects many shipments | No | Per-shipment verification only; incident deduplication deferred. |
| 7 | P01 Delivered, tracking says in transit | No | |
| 8 | P11 Proof belongs to another shipment | No | |
| 9 | W04 Wrong container | No | |
| 10 | G08 Vehicle near address, no delivery evidence | No | Verifier never accepts proximity. |
| 11 | Q01 Weight differs from declaration | No | Reweigh verifier exists; no trace. |
| 12 | R01 Not delivered; valid proof exists | Authority check only | Verifier probe: a serious nonreceipt report blocks a rescan success; DELIVERY_DISPUTE_REVIEW is HUMAN_REVIEW and cannot auto-execute. |

Totals: 136 catalogued, 12 classified priorities, 2 verified resolved end to end (S03, D02), 2 more traced to a safe unresolved end (S04, C04), 0 exercised on a real database, 0 measured with a live model.

## Complete coverage matrix

| Case | Catalogued | Source support | Investigatable | Action support | V3.2 end-to-end |
|---|---|---|---|---|---|
| S01 No scan recorded | yes | unassessed | unassessed | unassessed | not claimed |
| S02 Barcode unreadable | yes | unassessed | unassessed | unassessed | not claimed |
| S03 Barcode misread | yes | partial | bounded tools / guide | REQUEST_RESCAN | controlled tests |
| S04 Wrong label on parcel | yes | partial | bounded tools / guide | REQUEST_RESCAN | controlled tests |
| S05 Duplicate tracking barcode | yes | unassessed | unassessed | unassessed | not claimed |
| S06 Duplicate scan event | yes | unassessed | unassessed | unassessed | not claimed |
| S07 Scan from wrong facility | yes | unassessed | unassessed | unassessed | not claimed |
| S08 Impossible scan sequence | yes | unassessed | unassessed | unassessed | not claimed |
| S09 Scanner systematically misreads | yes | unassessed | unassessed | unassessed | not claimed |
| S10 Scan accepted but status unchanged | yes | unassessed | unassessed | unassessed | not claimed |
| W01 Package received but not shelved | yes | unassessed | unassessed | unassessed | not claimed |
| W02 Package assigned to wrong shelf | yes | unassessed | unassessed | unassessed | not claimed |
| W03 Parcel disappears during sorting | yes | unassessed | unassessed | unassessed | not claimed |
| W04 Package placed in wrong container | yes | partial | bounded tools / guide | REQUEST_HUB_CHECK, REROUTE_TO_CONFIRMED_DESTINATION | not claimed |
| W05 Container delivered, one parcel unaccounted for | yes | unassessed | unassessed | unassessed | not claimed |
| W06 Parcel marked received but absent from inventory | yes | unassessed | unassessed | unassessed | not claimed |
| W07 Parcel found in wrong warehouse | yes | unassessed | unassessed | unassessed | not claimed |
| W08 Warehouse backlog | yes | unassessed | unassessed | unassessed | not claimed |
| W09 Parcels left after truck departure | yes | unassessed | unassessed | unassessed | not claimed |
| W10 Parcel physically present, system says departed | yes | unassessed | unassessed | unassessed | not claimed |
| W11 Damaged parcel held in warehouse | yes | unassessed | unassessed | unassessed | not claimed |
| W12 Parcel scanned into two storage locations | yes | unassessed | unassessed | unassessed | not claimed |
| C01 Assigned to driver, no load scan | yes | unassessed | unassessed | unassessed | not claimed |
| C02 Loaded, no delivery or return record | yes | unassessed | unassessed | unassessed | not claimed |
| C03 Driver returns, one parcel isn't scanned back | yes | partial | bounded tools / guide | INITIATE_CUSTODY_RECONCILIATION | not claimed |
| C04 Handover between drivers unrecorded | yes | partial | bounded tools / guide | INITIATE_CUSTODY_RECONCILIATION | controlled tests |
| C05 Two parties claim custody | yes | unassessed | unassessed | unassessed | not claimed |
| C06 Parcel possibly fell from vehicle | yes | unassessed | unassessed | unassessed | not claimed |
| C07 Last scan at transit hub, no later records | yes | unassessed | unassessed | unassessed | not claimed |
| C08 Package found after being marked missing | yes | unassessed | unassessed | unassessed | not claimed |
| C09 Custody scan exists but no physical confirmation | yes | unassessed | unassessed | unassessed | not claimed |
| C10 Multiple parcels missing from one vehicle | yes | unassessed | unassessed | unassessed | not claimed |
| C11 Parcel stolen or tampered with — suspected | yes | unassessed | unassessed | unassessed | not claimed |
| C12 Missing parcel eventually declared lost | yes | unassessed | unassessed | unassessed | not claimed |
| G01 Vehicle deviates from planned route | yes | unassessed | unassessed | unassessed | not claimed |
| G02 Vehicle stopped for an unusually long period | yes | unassessed | unassessed | unassessed | not claimed |
| G03 Vehicle is late arriving at depot | yes | unassessed | unassessed | unassessed | not claimed |
| G04 Vehicle passes destination without delivery | yes | unassessed | unassessed | unassessed | not claimed |
| G05 Vehicle GPS disappears | yes | unassessed | unassessed | unassessed | not claimed |
| G06 GPS reports impossible jump | yes | unassessed | unassessed | unassessed | not claimed |
| G07 Route finished, parcels remain unresolved | yes | unassessed | unassessed | unassessed | not claimed |
| G08 Vehicle appears near address, no delivery evidence | yes | partial | bounded tools / guide | REQUEST_ADDITIONAL_EVIDENCE | not claimed |
| G09 Driver visits wrong gate or entrance | yes | unassessed | unassessed | unassessed | not claimed |
| G10 Driver takes longer route | yes | unassessed | unassessed | unassessed | not claimed |
| G11 Vehicle reported at two locations simultaneously | yes | unassessed | unassessed | unassessed | not claimed |
| G12 GPS indicates vehicle at depot but customer status remains out for delivery | yes | unassessed | unassessed | unassessed | not claimed |
| G13 Multiple routes late in one district | yes | unassessed | unassessed | unassessed | not claimed |
| G14 Repeated missed stops near deadline | yes | unassessed | unassessed | unassessed | not claimed |
| D01 Driver phone offline | yes | unassessed | unassessed | unassessed | not claimed |
| D02 Records created offline, uploaded later | yes | partial | bounded tools / guide | REQUEST_DEVICE_SYNC | controlled tests |
| D03 Device online but uploads failing | yes | unassessed | unassessed | unassessed | not claimed |
| D04 Device battery failure | yes | unassessed | unassessed | unassessed | not claimed |
| D05 Scanner disconnected from backend | yes | unassessed | unassessed | unassessed | not claimed |
| D06 Device clock incorrect | yes | unassessed | unassessed | unassessed | not claimed |
| D07 Events arrive out of order | yes | unassessed | unassessed | unassessed | not claimed |
| D08 Integration drops events | yes | unassessed | unassessed | unassessed | not claimed |
| D09 Tracking API returns stale status | yes | unassessed | unassessed | unassessed | not claimed |
| D10 Device records associated with wrong driver | yes | unassessed | unassessed | unassessed | not claimed |
| D11 Same device affects many shipments | yes | partial | bounded tools / guide | REQUEST_DEVICE_SYNC | not claimed |
| D12 System outage across many facilities | yes | unassessed | unassessed | unassessed | not claimed |
| P01 Parcel delivered, tracking still says in transit | yes | partial | bounded tools / guide | REQUEST_ADDITIONAL_EVIDENCE | not claimed |
| P02 System says delivered, no proof exists | yes | unassessed | unassessed | unassessed | not claimed |
| P03 Delivery photograph exists, no OTP | yes | unassessed | unassessed | unassessed | not claimed |
| P04 OTP valid, photograph missing | yes | unassessed | unassessed | unassessed | not claimed |
| P05 Wrong OTP or failed verification | yes | unassessed | unassessed | unassessed | not claimed |
| P06 Parcel handed to another person | yes | unassessed | unassessed | unassessed | not claimed |
| P07 Delivery recorded at wrong address | yes | unassessed | unassessed | unassessed | not claimed |
| P08 Wrong compound gate | yes | unassessed | unassessed | unassessed | not claimed |
| P09 Driver marks recipient unavailable | yes | unassessed | unassessed | unassessed | not claimed |
| P10 Failed delivery reported but recipient says no attempt occurred | yes | unassessed | unassessed | unassessed | not claimed |
| P11 Delivery proof belongs to another shipment | yes | partial | bounded tools / guide | REQUEST_ADDITIONAL_EVIDENCE | not claimed |
| P12 Delivery status reversed | yes | unassessed | unassessed | unassessed | not claimed |
| P13 Driver delivers, then returns to depot before syncing | yes | unassessed | unassessed | unassessed | not claimed |
| P14 Parcel left at doorstep without authorized handover | yes | unassessed | unassessed | unassessed | not claimed |
| P15 Delivery confirmed, recipient later reports non-receipt | yes | unassessed | unassessed | unassessed | not claimed |
| P16 Multi-package shipment only partly delivered | yes | unassessed | unassessed | unassessed | not claimed |
| R01 Customer says not delivered; valid proof exists | yes | partial | bounded tools / guide | DELIVERY_DISPUTE_REVIEW | not claimed |
| R02 Customer says delivered; system says missing | yes | unassessed | unassessed | unassessed | not claimed |
| R03 Driver says delivered; no proof exists | yes | unassessed | unassessed | unassessed | not claimed |
| R04 Driver says parcel was returned; depot has no scan | yes | unassessed | unassessed | unassessed | not claimed |
| R05 Customer says delivery attempted while nobody visited | yes | unassessed | unassessed | unassessed | not claimed |
| R06 Customer reports wrong item | yes | unassessed | unassessed | unassessed | not claimed |
| R07 Recipient denies OTP handover | yes | unassessed | unassessed | unassessed | not claimed |
| R08 Customer reports damaged package despite delivered status | yes | unassessed | unassessed | unassessed | not claimed |
| R09 Incorrect lost-shipment claim | yes | unassessed | unassessed | unassessed | not claimed |
| R10 Multiple contradictory reports | yes | unassessed | unassessed | unassessed | not claimed |
| T01 Missed linehaul departure | yes | unassessed | unassessed | unassessed | not claimed |
| T02 Truck departs late | yes | unassessed | unassessed | unassessed | not claimed |
| T03 Truck arrives late | yes | unassessed | unassessed | unassessed | not claimed |
| T04 Shipment sent toward wrong destination | yes | unassessed | unassessed | unassessed | not claimed |
| T05 Parcel misses sorting cutoff | yes | unassessed | unassessed | unassessed | not claimed |
| T06 Warehouse capacity exceeded | yes | unassessed | unassessed | unassessed | not claimed |
| T07 Traffic closure | yes | unassessed | unassessed | unassessed | not claimed |
| T08 Extreme weather | yes | unassessed | unassessed | unassessed | not claimed |
| T09 Vehicle breakdown | yes | unassessed | unassessed | unassessed | not claimed |
| T10 Fuel or charging delay | yes | unassessed | unassessed | unassessed | not claimed |
| T11 Delivery route overloaded | yes | unassessed | unassessed | unassessed | not claimed |
| T12 Delivery commitment at risk | yes | unassessed | unassessed | unassessed | not claimed |
| T13 Holiday or business closure | yes | unassessed | unassessed | unassessed | not claimed |
| T14 No available delivery appointment | yes | unassessed | unassessed | unassessed | not claimed |
| Q01 Weight differs from declaration | yes | partial | bounded tools / guide | REQUEST_REWEIGH | not claimed |
| Q02 One scale reads many parcels incorrectly | yes | unassessed | unassessed | unassessed | not claimed |
| Q03 Parcel weight drops unexpectedly | yes | unassessed | unassessed | unassessed | not claimed |
| Q04 Parcel damaged in transit | yes | unassessed | unassessed | unassessed | not claimed |
| Q05 Seal broken | yes | unassessed | unassessed | unassessed | not claimed |
| Q06 Parcel empty at delivery | yes | unassessed | unassessed | unassessed | not claimed |
| Q07 Temperature excursion | yes | unassessed | unassessed | unassessed | not claimed |
| Q08 Shock/tilt excursion | yes | unassessed | unassessed | unassessed | not claimed |
| Q09 Leakage or hazardous condition | yes | unassessed | unassessed | unassessed | not claimed |
| Q10 Suspected counterfeit/replaced parcel | yes | unassessed | unassessed | unassessed | not claimed |
| L01 Return requested but parcel remains with recipient | yes | unassessed | unassessed | unassessed | not claimed |
| L02 Driver collects return but no depot receipt | yes | unassessed | unassessed | unassessed | not claimed |
| L03 Return sent to wrong facility | yes | unassessed | unassessed | unassessed | not claimed |
| L04 Return lost in transit | yes | unassessed | unassessed | unassessed | not claimed |
| L05 Return received but refund not triggered | yes | unassessed | unassessed | unassessed | not claimed |
| L06 Returned item does not match original order | yes | unassessed | unassessed | unassessed | not claimed |
| L07 Parcel returned without required reason | yes | unassessed | unassessed | unassessed | not claimed |
| L08 Return scan appears before original delivery attempt | yes | unassessed | unassessed | unassessed | not claimed |
| I01 Customs documentation missing | yes | unassessed | unassessed | unassessed | not claimed |
| I02 HS classification dispute | yes | unassessed | unassessed | unassessed | not claimed |
| I03 Duty or tax clearance pending | yes | unassessed | unassessed | unassessed | not claimed |
| I04 Restricted or prohibited goods suspected | yes | unassessed | unassessed | unassessed | not claimed |
| I05 Border security inspection | yes | unassessed | unassessed | unassessed | not claimed |
| I06 International transfer missing | yes | unassessed | unassessed | unassessed | not claimed |
| I07 Different carriers report conflicting statuses | yes | unassessed | unassessed | unassessed | not claimed |
| I08 Flight/port disruption | yes | unassessed | unassessed | unassessed | not claimed |
| X01 One offline phone affects 30 parcels | yes | unassessed | unassessed | unassessed | not claimed |
| X02 One scanner misreads hundreds of labels | yes | unassessed | unassessed | unassessed | not claimed |
| X03 Sorting chute creates repeated missorts | yes | unassessed | unassessed | unassessed | not claimed |
| X04 One hub processing backlog affects several routes | yes | unassessed | unassessed | unassessed | not claimed |
| X05 Several parcels omitted from one manifest revision | yes | unassessed | unassessed | unassessed | not claimed |
| X06 One vehicle breakdown delays multiple shipments | yes | unassessed | unassessed | unassessed | not claimed |
| X07 Large regional connectivity outage | yes | unassessed | unassessed | unassessed | not claimed |
| X08 Shared incorrect address master data | yes | unassessed | unassessed | unassessed | not claimed |
| X09 Duplicate operational requests | yes | unassessed | unassessed | unassessed | not claimed |
| X10 Many false overdue statuses after system recovery | yes | unassessed | unassessed | unassessed | not claimed |

Remaining: live investigator/reviewer accuracy evaluation, full discriminating records for the other prioritized cases, incident-wide request coordination, real response adapters and Composer UI implementation. These are not represented as implemented.
