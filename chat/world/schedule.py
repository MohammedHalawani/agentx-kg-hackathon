"""Scenario weighting: place mechanism instances on the world's resources until each mechanism touches
enough shipments in every split.

The scheduler is the scenario designer: it looks at where parcels flow in a simulation run (which
device scans which parcels, which trips and routes carry them) and places faults on those resources:
a depot handheld drops off the network during a morning receipt, a scale drifts during an evening sort,
a linehaul truck breaks down. The fault then acts physically on whatever it touches in the next run.
Because faults change the flows, the loop re-simulates and tops up until the per-split targets
(WorldConfig.target: the committed per-mechanism rates in world/config.py times the split's shipments) are
met. Rates are recorded as scenario weighting, not as real frequencies.
"""
from collections import defaultdict
from datetime import timedelta
import math

from world.bookings import s10
from world.config import local_date, local_dt, local_hour
from world.geo import offset_point
from world.mechanisms import CLAIM_SUBTYPE, MECHANISM_TYPES, MechanismPlan
from world.physical import Simulation

# Duplicates and routine failed attempts arise on their own (base rates); everything else is placed by the scheduler.
SCHEDULED = tuple(t for t in MECHANISM_TYPES if t not in ("DUPLICATE_EVENTS", "ROUTINE_FAILED_ATTEMPT"))
RUNTIME_KEYS = ("done", "resolved", "correction_at")
MAX_ROUNDS = 5


class Scheduler:
    def __init__(self, config, network, draws, shipments):
        self.config, self.net, self.d, self.shipments = config, network, draws, shipments
        self.plan = MechanismPlan()
        self.split_of = {sid: s.split for sid, s in shipments.items()}
        self.split_sizes = {split: sum(1 for v in self.split_of.values() if v == split) for split in ("history", "development", "held_out")}
        self.round = 0

    # ------------------------------------------------------------------ loop
    def run(self):
        sim = self.simulate()
        history = []
        for self.round in range(MAX_ROUNDS):
            counts = self.counts(sim)
            need = {(m, split): self.config.target(m, split, self.split_sizes[split]) - counts.get((m, split), 0)
                    for m in SCHEDULED for split in ("history", "development", "held_out")}
            history.append({"round": self.round, "short": {f"{m}/{s}": n for (m, s), n in sorted(need.items()) if n > 0}})
            if all(n <= 0 for n in need.values()):
                break
            for (mtype, split), n in sorted(need.items()):
                if n > 0:
                    getattr(self, "add_" + mtype.lower())(sim, split, n)
            sim = self.simulate()
        self.rounds = history
        return sim

    def simulate(self):
        self.whole_seconds()
        for mech in self.plan.items.values():
            for key in RUNTIME_KEYS:
                mech.params.pop(key, None)
        for table in (self.plan.parcel, self.plan.shipment, self.plan.route, self.plan.depot_day):
            for flags in table.values():
                for _, params in flags.values():
                    for key in RUNTIME_KEYS:
                        params.pop(key, None)
        return Simulation(self.config, self.net, self.d, self.shipments, self.plan).run()

    def whole_seconds(self):
        """Mechanism windows are whole-second instants, like every record time."""
        def sec(t):
            return t.replace(microsecond=0) if hasattr(t, "replace") and t is not None else t
        plan = self.plan
        for table in (plan.device_down, plan.device_loss, plan.backlog, plan.scale_drift, plan.sms_outage):
            for key, rows in table.items():
                table[key] = [tuple(sec(v) if i < 2 else v for i, v in enumerate(row)) for row in rows]
        plan.traffic = [(c, d, sec(a), sec(b), f, m) for c, d, a, b, f, m in plan.traffic]
        for mech in plan.items.values():
            mech.started_at, mech.ended_at = sec(mech.started_at), sec(mech.ended_at)
        for flags in plan.shipment.values():
            for mid, params in flags.values():
                for key in ("start", "end", "from", "until", "at"):
                    if key in params:
                        params[key] = sec(params[key])

    # ------------------------------------------------------------------ counting
    def affected(self, sim):
        """mechanism id -> shipments it touched in this run (physical marks plus record-level effects)."""
        out = defaultdict(set)
        for mid, sids in sim.touch_ship.items():
            out[mid] |= sids
        for device, windows in self.plan.device_down.items():
            for a in sim.acts:
                if a.get("device") == device and a["type"] in ("scan", "attempt") and a.get("sid"):
                    for start, end, mid in windows:
                        if start <= a["t"] < end:
                            out[mid].add(a["sid"])
        handed = {}
        for pid, state in sim.p.items():
            for row in state.timeline:
                if row[1] == "PERSON":
                    handed.setdefault(state.shipment.sid, row[0])
        for sid, flags in self.plan.shipment.items():
            flag = flags.get("CUSTOMER_COMPLAINT")
            if not flag:
                continue
            mid, params = flag
            if params["subtype"] == CLAIM_SUBTYPE:
                if sid in handed:
                    out[mid].add(sid)
            elif sid not in handed or params["at"] < handed[sid]:
                out[mid].add(sid)
        for device, windows in self.plan.device_loss.items():
            for a in sim.acts:
                if a.get("device") == device and a["type"] in ("scan", "attempt") and a.get("sid"):
                    for start, end, fraction, mid in windows:
                        if start <= a["t"] < end and self.d.chance(fraction, "lost", a["act"]):
                            out[mid].add(a["sid"])
        return out

    def counts(self, sim):
        counts = defaultdict(int)
        for mid, sids in self.affected(sim).items():
            mtype = self.plan.items[mid].type
            for sid in sids:
                counts[(mtype, self.split_of[sid])] += 1
        # A shipment counts once per mechanism type.
        dedup = defaultdict(set)
        for mid, sids in self.affected(sim).items():
            for sid in sids:
                dedup[(self.plan.items[mid].type, self.split_of[sid])].add(sid)
        return {key: len(value) for key, value in dedup.items()}

    # ------------------------------------------------------------------ helpers
    def key(self, *parts):
        return ("sched", self.round, *parts)

    def in_split(self, sid, split):
        return self.split_of.get(sid) == split

    def consumer(self, sid):
        return self.shipments[sid].recipient_kind == "Customer"

    def pick(self, candidates, n, *key):
        candidates = sorted(set(candidates))
        return self.d.sample(candidates, n, *self.key(*key))

    def flagged(self, table, mtype):
        return {k for k, flags in table.items() if mtype in flags}

    def sized(self, rows, need, *, min_hours, max_hours, key):
        """A window over time-ordered (t, sid) rows that touches about `need` shipments."""
        rows = sorted(rows)
        if not rows:
            return None
        first = int(self.d.u(*self.key("win", *key)) * max(1, len(rows) // 3))
        start = rows[first][0]
        seen, end = set(), start
        for t, sid in rows[first:]:
            if t - start > timedelta(hours=max_hours):
                break
            seen.add(sid)
            end = t
            if len(seen) >= need:
                break
        end = max(end + timedelta(minutes=10), start + timedelta(hours=min_hours))
        return start - timedelta(minutes=self.d.integer(5, 25, *self.key("lead", *key))), end

    def choose(self, options, need, *key):
        """Among (count, ...) options prefer the smallest that still covers the need; else the largest."""
        enough = sorted((o for o in options if o[0] >= need), key=lambda o: (o[0], o[1:3]))
        if enough:
            top = enough[: max(1, len(enough) // 3)]
            return top[int(self.d.u(*self.key("choose", *key)) * len(top))]
        return max(options, key=lambda o: (o[0], o[1:3])) if options else None

    def acts(self, sim, kind, **match):
        return [a for a in sim.acts if a["type"] == kind and all(a.get(k) == v for k, v in match.items())]

    # ------------------------------------------------------------------ per-parcel and per-shipment mechanisms
    def _parcel_mech(self, mtype, pids, subtype, **params):
        for pid in pids:
            sid = pid.rsplit("-PKG-", 1)[0]
            s = self.shipments[sid]
            started = s.booked_at
            mid = self.plan.add(mtype, subtype, started, None, pid=pid, sid=sid)
            self.plan.on_parcel(pid, mtype, mid, **params(pid) if callable(params) else params)

    def _ship_mech(self, mtype, sids, subtype, params):
        for sid in sids:
            s = self.shipments[sid]
            p = params(sid)
            mid = self.plan.add(mtype, p.pop("_subtype", subtype), p.pop("_started", s.booked_at), p.pop("_ended", None), sid=sid)
            self.plan.on_shipment(sid, mtype, mid, **p)

    def add_scan_skipped_at_receipt(self, sim, split, n):
        taken = self.flagged(self.plan.parcel, "SCAN_SKIPPED_AT_RECEIPT")
        depot = [a["pid"] for a in self.acts(sim, "scan", obs="HANDHELD_RECEIPT") if a.get("facility", "").startswith("DEMO-DEPOT")
                 and self.in_split(a["sid"], split) and a["pid"] not in taken]
        hub = [a["pid"] for a in self.acts(sim, "scan", obs="CONTAINER_SCAN") if a.get("facility", "").startswith("DEMO-HUB")
               and self.in_split(a["sid"], split) and a["pid"] not in taken]
        chosen = self.pick(depot, math.ceil(n * .8), "skip-depot", split) + self.pick(hub, max(1, n - math.ceil(n * .8)), "skip-hub", split)
        for pid in sorted(set(chosen)):
            stage = "depot" if pid in depot else "hub"
            self._parcel_mech("SCAN_SKIPPED_AT_RECEIPT", [pid], stage.upper(), stage=stage)

    def add_assigned_not_loaded(self, sim, split, n):
        taken = self.flagged(self.plan.parcel, "ASSIGNED_NOT_LOADED")
        loads = [a["pid"] for a in self.acts(sim, "scan", obs="LOAD_CONFIRMATION") if a.get("route") and self.in_split(a["sid"], split)
                 and a["pid"] not in taken]
        self._parcel_mech("ASSIGNED_NOT_LOADED", self.pick(loads, n, "anl", split), "LEFT_ON_SHELF")

    def add_delivery_scan_skipped(self, sim, split, n):
        taken = self.flagged(self.plan.shipment, "DELIVERY_SCAN_SKIPPED")
        ok = {a["sid"] for a in self.acts(sim, "handoff") if a["person_type"] in ("EXPECTED_RECIPIENT", "LEFT_AT_DOOR")}
        sids = [sid for sid in ok if self.in_split(sid, split) and self.consumer(sid) and sid not in taken]
        self._ship_mech("DELIVERY_SCAN_SKIPPED", self.pick(sids, n, "dss", split), "APP_FLOW_NOT_COMPLETED", lambda sid: {})

    def add_return_scan_skipped(self, sim, split, n):
        taken = self.flagged(self.plan.parcel, "RETURN_SCAN_SKIPPED")
        returns = [a["pid"] for a in self.acts(sim, "scan", obs="RETURN_SCAN") if self.in_split(a["sid"], split) and a["pid"] not in taken]
        if len(set(returns)) < n:
            # Few parcels come back on their own: make some recipients unreachable first (a separate, overlapping cause).
            self.add_recipient_unavailable(sim, split, n - len(set(returns)) + 2, reason="return")
        self._parcel_mech("RETURN_SCAN_SKIPPED", self.pick(returns, n, "rss", split), "CHECK_IN_NOT_SCANNED")

    def add_recipient_unavailable(self, sim, split, n, reason="target"):
        taken = self.flagged(self.plan.shipment, "RECIPIENT_UNAVAILABLE")
        first_load = {}
        for a in self.acts(sim, "scan", obs="LOAD_CONFIRMATION"):
            if a.get("route"):
                first_load.setdefault(a["sid"], a["t"])
        sids = [sid for sid in first_load if self.in_split(sid, split) and self.consumer(sid) and sid not in taken]
        def params(sid):
            start = local_dt(local_date(first_load[sid]), "00:00")
            days = self.d.integer(2, 4, *self.key("ru-days", sid))
            return {"start": start, "end": start + timedelta(days=days), "_started": start, "_ended": start + timedelta(days=days)}
        self._ship_mech("RECIPIENT_UNAVAILABLE", self.pick(sids, n, "ru", split, reason), "AWAY", params)

    def add_wrong_address(self, sim, split, n):
        taken = self.flagged(self.plan.shipment, "WRONG_ADDRESS")
        sids = [sid for sid, s in self.shipments.items() if s.split == split and self.consumer(sid) and sid not in taken]
        for sid in self.pick(sids, n, "wa", split):
            s = self.shipments[sid]
            home = s.recipient["registered_point"]
            distance = self.d.uniform(2, 9, *self.key("wa-km", sid))
            angle = self.d.uniform(0, 2 * math.pi, *self.key("wa-angle", sid))
            moved = offset_point(home[0], home[1], distance * math.cos(angle), distance * math.sin(angle))
            s.recipient["home"] = (round(moved[0], 6), round(moved[1], 6))
            mid = self.plan.add("WRONG_ADDRESS", "OUTDATED_ADDRESS", s.booked_at, None, sid=sid)
            self.plan.on_shipment(sid, "WRONG_ADDRESS", mid)

    def add_wrong_gate(self, sim, split, n):
        taken = self.flagged(self.plan.shipment, "WRONG_GATE")
        sids = [sid for sid, s in self.shipments.items() if s.split == split and len(s.recipient["gates"]) >= 2 and sid not in taken]
        for sid in self.pick(sids, n, "wg", split):
            s = self.shipments[sid]
            other = [g for g in s.recipient["gates"] if g != s.recipient["gate"]]
            mid = self.plan.add("WRONG_GATE", "NAVIGATION_PIN_AT_OTHER_GATE", s.booked_at, None, sid=sid)
            self.plan.on_shipment(sid, "WRONG_GATE", mid, pin_gate=self.d.choice(other, *self.key("wg-gate", sid)))

    def add_neighbour_receives(self, sim, split, n):
        taken = self.flagged(self.plan.shipment, "NEIGHBOUR_RECEIVES")
        # Placed on OTP-protected consumer deliveries, where the driver's override is the observable failure (as for
        # misdelivery and the one-time code itself), so "the shipment uses a code" says nothing about which it was.
        sids = [sid for sid, s in self.shipments.items() if s.split == split and self.consumer(sid) and s.otp_required
                and s.recipient["preference"] == "STANDARD" and sid not in taken]
        self._ship_mech("NEIGHBOUR_RECEIVES", self.pick(sids, n, "nb", split), "UNAUTHORISED_NEIGHBOUR", lambda sid: {})

    def add_misdelivery(self, sim, split, n):
        taken = self.flagged(self.plan.shipment, "MISDELIVERY")
        sids = [sid for sid, s in self.shipments.items() if s.split == split and self.consumer(sid) and s.otp_required and sid not in taken]
        def params(sid):
            distance = self.d.uniform(.08, .45, *self.key("md-km", sid))
            angle = self.d.uniform(0, 2 * math.pi, *self.key("md-angle", sid))
            return {"north_km": distance * math.cos(angle), "east_km": distance * math.sin(angle)}
        self._ship_mech("MISDELIVERY", self.pick(sids, n, "md", split), "WRONG_BUILDING", params)

    def add_label_misread(self, sim, split, n):
        taken = self.flagged(self.plan.parcel, "LABEL_MISREAD")
        pids = [p.pid for s in self.shipments.values() if s.split == split for p in s.parcels if p.pid not in taken]
        for pid in self.pick(pids, n, "mr", split):
            stage = "sort" if self.d.chance(.7, *self.key("mr-stage", pid)) else "depot"
            self._parcel_mech("LABEL_MISREAD", [pid], f"{stage.upper()}_READ", stage=stage)

    def add_wrong_label_applied(self, sim, split, n):
        taken = self.flagged(self.plan.parcel, "WRONG_LABEL_APPLIED")
        used = {p.barcode for s in self.shipments.values() for p in s.parcels}
        pids = [p.pid for s in self.shipments.values() if s.split == split for p in s.parcels if p.pid not in taken]
        for pid in self.pick(pids, n, "wl", split):
            parcel = next(p for p in self.shipments[pid.rsplit("-PKG-", 1)[0]].parcels if p.pid == pid)
            serial = int(parcel.barcode[2:10])
            bump = self.d.integer(1, 40, *self.key("wl-near", pid))
            barcode = s10((serial + bump) % 90_000_000 + 10_000_000, parcel.barcode[:2])
            while barcode in used:
                bump += 1
                barcode = s10((serial + bump) % 90_000_000 + 10_000_000, parcel.barcode[:2])
            used.add(barcode)
            self._parcel_mech("WRONG_LABEL_APPLIED", [pid], "LABEL_FROM_OTHER_ORDER", barcode=barcode)

    def add_declared_weight_wrong(self, sim, split, n):
        taken = self.flagged(self.plan.parcel, "DECLARED_WEIGHT_WRONG")
        pids = [p.pid for s in self.shipments.values() if s.split == split for p in s.parcels
                if p.pid not in taken and p.true_kg >= 1.0]
        for pid in self.pick(pids, n, "dw", split):
            parcel = next(p for p in self.shipments[pid.rsplit("-PKG-", 1)[0]].parcels if p.pid == pid)
            factor = (self.d.uniform(.45, .72, *self.key("dw-f", pid)) if self.d.chance(.5, *self.key("dw-dir", pid))
                      else self.d.uniform(1.45, 2.2, *self.key("dw-f2", pid)))
            parcel.declared_kg = round(parcel.true_kg * factor, 2)
            self._parcel_mech("DECLARED_WEIGHT_WRONG", [pid], "DECLARATION_ERROR", factor=round(factor, 3))

    def add_customer_complaint(self, sim, split, n):
        taken = self.flagged(self.plan.shipment, "CUSTOMER_COMPLAINT")
        delivered = {a["sid"]: a["t"] for a in self.acts(sim, "handoff") if a["person_type"] == "EXPECTED_RECIPIENT"}
        sids = [sid for sid, s in self.shipments.items() if s.split == split and self.consumer(sid) and sid not in taken]
        for sid in self.pick(sids, n, "cc", split):
            s = self.shipments[sid]
            claim = sid in delivered and self.d.chance(.4, *self.key("cc-kind", sid))
            if claim:
                mid = self.plan.add("CUSTOMER_COMPLAINT", CLAIM_SUBTYPE, delivered[sid], None, sid=sid)
                self.plan.on_shipment(sid, "CUSTOMER_COMPLAINT", mid, subtype=CLAIM_SUBTYPE)
            else:
                at = s.booked_at + timedelta(hours=self.d.uniform(6, 40, *self.key("cc-at", sid)))
                mid = self.plan.add("CUSTOMER_COMPLAINT", "STATUS_QUESTION", at, None, sid=sid)
                self.plan.on_shipment(sid, "CUSTOMER_COMPLAINT", mid, subtype="STATUS_QUESTION", at=at)

    # ------------------------------------------------------------------ shared-resource mechanisms
    def _rows_by(self, sim, split, kinds, *, devices=None):
        """(device, local day) -> time-ordered (t, sid) rows of this split's records made by that device."""
        rows = defaultdict(list)
        for a in sim.acts:
            if a["type"] in kinds and a.get("device") and a.get("sid") and self.in_split(a["sid"], split):
                if devices is None or self.net.devices[a["device"]].kind in devices:
                    rows[(a["device"], local_date(a["t"]))].append((a["t"], a["sid"]))
        return rows

    def add_device_outage(self, sim, split, n):
        parts = min(3, max(1, math.ceil(n / 5)))
        each = math.ceil(n / parts)
        cycle = (("FACILITY_HANDHELD",), ("DRIVER_APP",), ("SORTER_READER", "FACILITY_HANDHELD"))
        for part in range(parts):
            kinds = cycle[(part + self.round) % len(cycle)]
            rows = self._rows_by(sim, split, ("scan", "attempt"), devices=kinds)
            options = [(len({sid for _, sid in r}), dev, day, r) for (dev, day), r in rows.items()
                       if dev not in self.plan.device_down and dev not in self.plan.device_loss]
            chosen = self.choose(options, each, "outage", split, part)
            if not chosen:
                continue
            _, device, day, r = chosen
            kind = self.net.devices[device].kind
            if kind == "DRIVER_APP":
                start, end = self.sized(r, each, min_hours=1.5, max_hours=8, key=("outage", device, day))
                end += timedelta(hours=self.d.uniform(.5, 8, *self.key("out-tail", device, day)))
                subtype = "PHONE_OFFLINE"
            else:
                start, end = self.sized(r, each, min_hours=1.5, max_hours=7, key=("outage", device, day))
                end += timedelta(hours=self.d.uniform(.25, 1.5, *self.key("out-tail", device, day)))
                subtype = "UPLINK_LOST" if kind == "SORTER_READER" else self.d.choice(("WIFI_LOST", "APP_SYNC_STALLED"), *self.key("out-sub", device, day))
            mid = self.plan.add("DEVICE_OUTAGE", subtype, start, end, device=device, device_kind=kind)
            self.plan.device_down.setdefault(device, []).append((start, end, mid))

    def add_partial_upload_loss(self, sim, split, n):
        parts = min(3, max(1, math.ceil(n / 6)))
        each = math.ceil(n / parts / .5)
        for part in range(parts):
            rows = self._rows_by(sim, split, ("scan", "attempt"), devices=("DRIVER_APP", "FACILITY_HANDHELD"))
            options = [(len({sid for _, sid in r}), dev, day, r) for (dev, day), r in rows.items()
                       if dev not in self.plan.device_loss and dev not in self.plan.device_down]
            chosen = self.choose(options, each, "loss", split, part)
            if not chosen:
                continue
            _, device, day, r = chosen
            start, end = self.sized(r, each, min_hours=1.5, max_hours=8, key=("loss", device, day))
            fraction = round(self.d.uniform(.35, .6, *self.key("loss-f", device, day)), 2)
            mid = self.plan.add("PARTIAL_UPLOAD_LOSS", "OUTBOX_STUCK", start, end, device=device, fraction=fraction)
            self.plan.device_loss.setdefault(device, []).append((start, end, fraction, mid))

    def add_facility_backlog(self, sim, split, n):
        parts = min(2, max(1, math.ceil(n / 14)))
        each = math.ceil(n / parts)
        for part in range(parts):
            options = []
            for facility, log in sim.service_log.items():
                kind = self.net.facilities[facility].kind
                if (kind == "SortingCenter") != ((part + self.round) % 2 == 0):
                    continue
                by_day = defaultdict(list)
                for ready, done, pid in log:
                    sid = pid.rsplit("-PKG-", 1)[0]
                    if self.in_split(sid, split) and (kind != "SortingCenter" or local_hour(ready) >= 12):
                        by_day[local_date(ready)].append((ready, sid))
                for day, r in by_day.items():
                    if not any(local_date(w[0]) == day for w in self.plan.backlog.get(facility, [])):
                        options.append((len({sid for _, sid in r}), facility, day, r))
            chosen = self.choose(options, each, "backlog", split, part)
            if not chosen:
                continue
            _, facility, day, r = chosen
            kind = self.net.facilities[facility].kind
            start, end = self.sized(r, max(2, round(each * .4)), min_hours=1.5 if kind == "SortingCenter" else 1, max_hours=4,
                                    key=("backlog", facility, day))
            if kind == "SortingCenter":
                factor = round(self.d.uniform(.15, .3, *self.key("bl-f", facility, day)), 2)
                subtype = self.d.choice(("SORTER_JAM", "STAFF_SHORTAGE"), *self.key("bl-sub", facility, day))
            else:
                factor = round(self.d.uniform(.12, .3, *self.key("bl-f", facility, day)), 2)
                subtype = "RECEIVING_CONGESTION"
            mid = self.plan.add("FACILITY_BACKLOG", subtype, start, end, facility=facility, factor=factor)
            self.plan.backlog.setdefault(facility, []).append((start, end, factor, mid))

    def add_late_linehaul(self, sim, split, n):
        parts = min(3, max(1, math.ceil(n / 6)))
        each = math.ceil(n / parts)
        for part in range(parts):
            options = []
            for tid, state in sim.trips.items():
                if state.plan.kind not in ("LINEHAUL", "FEEDER") or tid.endswith("-R") or tid in self.plan.trip_delay or not state.parcels:
                    continue
                mine = {pid.rsplit("-PKG-", 1)[0] for pid in state.parcels if self.in_split(pid.rsplit("-PKG-", 1)[0], split)}
                if mine:
                    options.append((len(mine), tid, state.plan.kind, mine))
            chosen = self.choose(options, each, "late", split, part)
            if not chosen:
                continue
            _, tid, _, mine = chosen
            kind = "BREAKDOWN" if self.d.chance(.5, *self.key("lh-kind", tid)) else "DEPARTURE_DELAY"
            hours = self.d.uniform(3, 8, *self.key("lh-s", tid)) if kind == "BREAKDOWN" else self.d.uniform(2, 6, *self.key("lh-s", tid))
            seconds = round(hours * 3600)
            fraction = round(self.d.uniform(.2, .7, *self.key("lh-f", tid)), 2)
            plan = self.net.trips[tid]
            mid = self.plan.add("LATE_LINEHAUL", kind, plan.scheduled_departure, plan.scheduled_arrival + timedelta(seconds=seconds),
                                trip=tid, delay_seconds=seconds)
            self.plan.trip_delay[tid] = (kind, seconds, fraction, mid)

    def add_missort(self, sim, split, n):
        # Containers loaded onto the wrong linehaul truck (shared), and single parcels put in the wrong bag.
        estimate = 0
        options = []
        for tid, state in sim.trips.items():
            plan = state.plan
            if plan.kind != "LINEHAUL" or tid in self.plan.misload or not state.containers:
                continue
            biggest = max(state.containers, key=lambda c: (len(sim.containers[c].parcels), c))
            mine = {pid.rsplit("-PKG-", 1)[0] for pid in sim.containers[biggest].parcels if self.in_split(pid.rsplit("-PKG-", 1)[0], split)}
            others = [t for t in self.net.trips.values() if t.kind == "LINEHAUL" and t.origin == plan.origin and t.destination != plan.destination
                      and timedelta(minutes=20) <= t.scheduled_departure - plan.scheduled_departure <= timedelta(hours=4)]
            if mine and others:
                options.append((len(mine), tid, sorted(others, key=lambda t: t.scheduled_departure)[0].id, mine))
        chosen = self.choose(options, max(2, math.ceil(n * .5)), "misload", split)
        if chosen:
            count, tid, wrong, mine = chosen
            mid = self.plan.add("MISSORT", "CONTAINER_ON_WRONG_TRUCK", self.net.trips[tid].scheduled_departure, None, trip=tid, wrong_trip=wrong)
            self.plan.misload[tid] = (wrong, mid)
            estimate += count
        taken = self.flagged(self.plan.parcel, "MISSORT")
        inducted = [a["pid"] for a in self.acts(sim, "scan", obs="SORTER_READ") if self.in_split(a["sid"], split) and a["pid"] not in taken]
        depots = sorted(f for f, x in self.net.facilities.items() if x.kind == "DeliveryDepot")
        for pid in self.pick(inducted, max(1, n - estimate), "ms", split):
            right = self.shipments[pid.rsplit("-PKG-", 1)[0]].depot
            wrong = self.d.choice([d for d in depots if d != right], *self.key("ms-depot", pid))
            self._parcel_mech("MISSORT", [pid], "PARCEL_IN_WRONG_BAG", depot=wrong)

    def add_scale_drift(self, sim, split, n):
        parts = min(2, max(1, math.ceil(n / 6)))
        each = math.ceil(n / parts)
        for part in range(parts):
            rows = defaultdict(list)
            for a in self.acts(sim, "scan", obs="SCALE_WEIGH"):
                if self.in_split(a["sid"], split) and a["facility"].startswith("DEMO-SORT"):   # Induction scales (not depot check scales).
                    rows[(a["device"], local_date(a["t"]))].append((a["t"], a["sid"]))
            options = [(len({sid for _, sid in r}), dev, day, r) for (dev, day), r in rows.items()
                       if not any(local_date(w[0]) == day for w in self.plan.scale_drift.get(dev, []))]
            chosen = self.choose(options, each, "drift", split, part)
            if not chosen:
                continue
            _, device, day, r = chosen
            start, end = self.sized(r, each, min_hours=1.5, max_hours=8, key=("drift", device, day))
            factor = self.d.uniform(.15, .4, *self.key("sd-f", device, day)) * (1 if self.d.chance(.7, *self.key("sd-sign", device, day)) else -1)
            mid = self.plan.add("SCALE_DRIFT", "CALIBRATION_DRIFT", start, end, device=device, factor=round(factor, 3))
            self.plan.scale_drift.setdefault(device, []).append((start, end, round(factor, 3), mid))

    def add_otp_not_received(self, sim, split, n):
        # Mostly gateway outages on one carrier route (shared), plus a few individual number problems.
        rows = defaultdict(list)
        for a in self.acts(sim, "comm", purpose="OTP"):
            if self.in_split(a["sid"], split):
                rows[(a["carrier"], local_date(a["t"]))].append((a["t"], a["sid"]))
        options = [(len({sid for _, sid in r}), route, day, r) for (route, day), r in rows.items()
                   if not any(local_date(w[0]) == day for w in self.plan.sms_outage.get(route, []))]
        want = max(1, math.ceil(n * .6))
        chosen = self.choose(options, want, "sms", split) if n >= 4 else None   # Small needs: individual number problems only.
        estimate = 0
        if chosen:
            count, route, day, r = chosen
            start, end = self.sized(r, want, min_hours=1, max_hours=5, key=("sms", route, day))
            mid = self.plan.add("OTP_NOT_RECEIVED", "SMS_ROUTE_OUTAGE", start, end, carrier_route=route)
            self.plan.sms_outage.setdefault(route, []).append((start, end, mid))
            estimate = len({sid for t, sid in r if start <= t < end})
        taken = self.flagged(self.plan.shipment, "OTP_NOT_RECEIVED")
        delivered = {sid: t for (route, day), r in rows.items() for t, sid in r}
        sids = [sid for sid in delivered if sid not in taken]
        for sid in self.pick(sids, max(1, n - estimate), "otp-ind", split):
            day = local_date(delivered[sid])
            mid = self.plan.add("OTP_NOT_RECEIVED", "NUMBER_NOT_REACHABLE", local_dt(day, "00:00"), local_dt(day, "23:59"), sid=sid)
            self.plan.on_shipment(sid, "OTP_NOT_RECEIVED", mid, **{"from": local_dt(day, "00:00"), "until": local_dt(day, "23:59")})

    def add_contractor_retains(self, sim, split, n):
        failed = defaultdict(set)
        for a in self.acts(sim, "attempt", disposition="FAILED"):
            if self.in_split(a["sid"], split):
                failed[a["route"]].add(a["sid"])
        estimate = 0
        options = []
        for rid, route in sim.routes.items():
            if self.net.drivers[route.driver].employment != "INDEPENDENT" or (route.depot, route.date, route.slot) in self.plan.route:
                continue
            mine = failed.get(rid, set())
            options.append((-len(mine), rid, route, mine))
        options.sort(key=lambda o: (o[0], o[1]))
        for _, rid, route, mine in options:
            if estimate >= n or not mine and estimate > 0:
                break
            if not mine:
                # Nobody on this route failed in the last run: make one recipient unreachable on that day.
                sid = next((s for s in route.shipments if self.in_split(s, split) and self.consumer(s)
                            and not self.plan.shipment_flag(s, "RECIPIENT_UNAVAILABLE")), None)
                if sid is None:
                    continue
                start = local_dt(route.date, "00:00")
                ru = self.plan.add("RECIPIENT_UNAVAILABLE", "AWAY", start, start + timedelta(days=2), sid=sid)
                self.plan.on_shipment(sid, "RECIPIENT_UNAVAILABLE", ru, start=start, end=start + timedelta(days=2))
                mine = {sid}
            returns = round(self.d.uniform(20, 52, *self.key("cr-ret", rid))) if self.d.chance(.5, *self.key("cr-ret?", rid)) else None
            mid = self.plan.add("CONTRACTOR_RETAINS", "PARCELS_KEPT_AFTER_SHIFT", local_dt(route.date, "08:00"), None, route=rid,
                                driver=route.driver, returns_after_hours=returns)
            self.plan.route.setdefault((route.depot, route.date, route.slot), {})["CONTRACTOR_RETAINS"] = (mid, {"returns_after_hours": returns})
            estimate += len(mine)

    def add_unrecorded_handoff(self, sim, split, n):
        by_depot_day = defaultdict(list)
        for rid, route in sim.routes.items():
            by_depot_day[(route.depot, route.date)].append(route)
        estimate = 0
        options = []
        for (depot, day), routes in by_depot_day.items():
            if (depot, day) in self.plan.depot_day:
                continue
            routes = sorted(routes, key=lambda r: r.slot)
            a = max(routes, key=lambda r: (len(r.shipments), r.rid))
            mine = [sid for sid in a.shipments if self.in_split(sid, split)]
            on_duty = [d for d in self.net.depot_drivers[depot] if self.net.drivers[d].off_weekday != day.weekday()]
            if len(a.shipments) >= 4 and mine and (len(routes) >= 2 or len(on_duty) >= 2):
                # A depot with one route that day dispatches a second driver as well (the scenario's helper run).
                options.append((-len(mine), depot, day, a.slot, 1 - a.slot if len(routes) < 2 else next(r.slot for r in routes if r.rid != a.rid)))
        options.sort(key=lambda o: (o[0], o[1], o[2]))
        for _, depot, day, a, b in options:
            if estimate >= n:
                break
            k = self.d.integer(2, 3, *self.key("uh-k", depot, day))
            after = self.d.integer(1, 2, *self.key("uh-after", depot, day))
            mid = self.plan.add("UNRECORDED_HANDOFF", "PARCELS_PASSED_BETWEEN_DRIVERS", local_dt(day, "09:00"), None, depot=depot)
            self.plan.depot_day.setdefault((depot, day), {})["UNRECORDED_HANDOFF"] = (mid, {"from": a, "to": b, "after": after, "k": k})
            estimate += k

    def add_manifest_error(self, sim, split, n):
        estimate = 0
        options = []
        for rid, route in sim.routes.items():
            key = (route.depot, route.date, route.slot)
            if "MANIFEST_ERROR" in self.plan.route.get(key, {}) or len(route.loaded) < 2:
                continue
            mine = [pid for pid in route.loaded if self.in_split(pid.rsplit("-PKG-", 1)[0], split)]
            if mine:
                options.append((rid, key))
        for rid, key in self.pick(options, n, "me", split):
            prefer = [pid for pid in sim.routes[rid].loaded if self.in_split(pid.rsplit("-PKG-", 1)[0], split)]
            mid = self.plan.add("MANIFEST_ERROR", "REVISION_DROPPED_LOADED_PARCEL", local_dt(key[1], "08:00"), None, route=rid)
            self.plan.route.setdefault(key, {})["MANIFEST_ERROR"] = (mid, {"prefer": prefer})

    def add_traffic_disruption(self, sim, split, n):
        stops = defaultdict(list)
        for a in self.acts(sim, "attempt"):
            if not self.in_split(a["sid"], split):
                continue
            s = self.shipments[a["sid"]]
            hour = local_hour(a["t"])
            if 9 <= hour < 17:
                stops[(s.dest_city, s.recipient["district"], local_date(a["t"]))].append(a)
        options = sorted(((-len({a["sid"] for a in rows}), key, rows) for key, rows in stops.items()), key=lambda o: (o[0], o[1]))
        estimate, made = 0, 0
        for _, (city, district, day), rows in options:
            if estimate >= n * 1.2 or made >= 4:
                break
            if any(c == city and local_date(s) == day for c, d, s, e, f, m in self.plan.traffic):
                continue
            times = sorted(a["t"] for a in rows)
            start = times[0] - timedelta(minutes=self.d.integer(20, 70, *self.key("tr-s", city, district, day)))
            end = start + timedelta(hours=self.d.uniform(3, 6, *self.key("tr-len", city, district, day)))
            factor = round(self.d.uniform(2.5, 4.0, *self.key("tr-f", city, district, day)), 2)
            subtype = self.d.choice(("ROAD_CLOSURE", "ACCIDENT", "HEAVY_CONGESTION"), *self.key("tr-sub", city, district, day))
            mid = self.plan.add("TRAFFIC_DISRUPTION", subtype, start, end, city=city, district=district, factor=factor)
            self.plan.traffic.append((city, district, start, end, factor, mid))
            estimate += len({a["sid"] for a in rows if start <= a["t"] < end})
            made += 1
