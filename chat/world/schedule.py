"""Scenario weighting: place mechanism instances on the world's resources until each mechanism is the cause of
enough deviations in every split.

The scheduler is the scenario designer. It looks at where parcels flow in a simulation run (which device scans
which parcels, which trips and routes carry them, which clerk shift receives them) and places faults on those
resources and people: a depot handheld drops off the network during a morning receipt, a scale drifts during an
evening sort, a driver does not finish the app flow at several doors of one route, a dock clerk waves containers
through a shift, a label printer batch goes wrong. The fault then acts physically on whatever it touches in the
next run, at a rate below one for behaviour faults, so the other parcels of the same actor, device or window are
real evidence. Only a few causes are placed on one parcel or one recipient, where the cause really is local (a
wrong declared weight, an outdated address, a wrong navigation pin, a recipient away for days, a phone number
that cannot be reached, a customer's own claim).

Targets count CAUSES, not touches: a mechanism counts for a shipment only where it produced a deviation there
(world.physical marks them; device faults by world.observe.held_past_deadline). Because faults change the flows,
the loop re-simulates and tops up until the per-split targets (WorldConfig.target: the committed per-mechanism
rates in world/config.py times the split's shipments) are met. A shipment that already carries a scheduled cause
is avoided when the next one is placed, so multi-cause shipments come from mechanisms that physically meet, not
from stacking. Rates are recorded as scenario weighting, not as real frequencies.

Ordinary operation (origin "base", real-frequency, never topped up): short coverage gaps and upload retries on
driver phones and handhelds, rush-hour congestion, long holds of a truck at origin, the odd misread, status
questions from recipients. They are instances of the same mechanisms and mostly harmless (exposures); they are a
cause only where they made something miss a deadline.
"""
from collections import defaultdict
from datetime import datetime, timedelta
import math

from world.config import local_date, local_dt, local_hour
from world.geo import districts, offset_point
from world.mechanisms import CLAIM_SUBTYPE, MECHANISM_TYPES, MechanismPlan
from world.observe import held_past_deadline, upload_times
from world.physical import Simulation

# Duplicates and routine failed attempts arise on their own (base rates); everything else is placed by the scheduler.
SCHEDULED = tuple(t for t in MECHANISM_TYPES if t not in ("DUPLICATE_EVENTS", "ROUTINE_FAILED_ATTEMPT"))
RUNTIME_KEYS = ("done", "resolved", "correction_at")
MAX_ROUNDS = 8
SPLITS = ("history", "development", "held_out")


def sid_of(pid):
    return pid.rsplit("-PKG-", 1)[0]


class Scheduler:
    def __init__(self, config, network, draws, shipments):
        self.config, self.net, self.d, self.shipments = config, network, draws, shipments
        self.plan = MechanismPlan()
        self.split_of = {sid: s.split for sid, s in shipments.items()}
        self.split_sizes = {split: sum(1 for v in self.split_of.values() if v == split) for split in SPLITS}
        self.round = 0
        self.caused, self.exposed = {}, {}
        self.ordinary()

    # ------------------------------------------------------------------ ordinary operation (base rates)
    def ordinary(self):
        """Real-frequency variation placed once, before any scenario weighting."""
        config, plan, d = self.config, self.plan, self.d
        days = [config.day1 + timedelta(days=n) for n in range(config.days + config.horizon_days)]
        for device, info in sorted(self.net.devices.items()):
            for day in days:
                key = ("ordinary", device, day.isoformat())
                if info.kind == "DRIVER_APP" and d.chance(.06, *key, "gap"):
                    # A dead zone, a flat battery, the app in the background: the phone is off the network for a while.
                    start = local_dt(day, "09:00") + timedelta(minutes=d.integer(0, 420, *key, "gap-start"))
                    end = start + timedelta(seconds=round(min(max(d.lognormal(2700, .8, *key, "gap-length"), 900), 5 * 3600)))
                    mid = plan.add("DEVICE_OUTAGE", "COVERAGE_GAP", start, end, origin="base", device=device, device_kind=info.kind)
                    plan.device_down.setdefault(device, []).append((start, end, mid))
                elif info.kind == "FACILITY_HANDHELD" and d.chance(.03, *key, "gap"):
                    start = local_dt(day, "05:00") + timedelta(minutes=d.integer(0, 960, *key, "gap-start"))
                    end = start + timedelta(minutes=d.integer(20, 150, *key, "gap-length"))
                    mid = plan.add("DEVICE_OUTAGE", "WIFI_LOST", start, end, origin="base", device=device, device_kind=info.kind)
                    plan.device_down.setdefault(device, []).append((start, end, mid))
                elif info.kind == "DRIVER_APP" and d.chance(.03, *key, "retry"):
                    # Uploads that keep failing and retrying until the app is restarted.
                    start = local_dt(day, "09:00") + timedelta(minutes=d.integer(0, 420, *key, "retry-start"))
                    end = start + timedelta(minutes=d.integer(60, 180, *key, "retry-length"))
                    release = end + timedelta(minutes=d.integer(20, 240, *key, "retry-release"))
                    fraction = round(d.uniform(.15, .35, *key, "retry-share"), 2)
                    mid = plan.add("PARTIAL_UPLOAD_LOSS", "UPLOAD_RETRIES", start, end, origin="base", device=device, fraction=fraction)
                    plan.device_loss.setdefault(device, []).append((start, end, fraction, mid, release))
        for day in days:
            for city in ("RUH", "JED", "DMM"):
                for slot in ("07:00", "16:30"):
                    key = ("ordinary-traffic", city, day.isoformat(), slot)
                    if not d.chance(.7, *key):
                        continue
                    district = d.choice(districts(city), *key, "district")
                    start = local_dt(day, slot) + timedelta(minutes=d.integer(0, 50, *key, "m"))
                    end = start + timedelta(minutes=d.integer(60, 150, *key, "len"))
                    factor = round(d.uniform(1.15, 1.9, *key, "factor"), 2)
                    mid = plan.add("TRAFFIC_DISRUPTION", "RUSH_CONGESTION", start, end, origin="base", city=city, district=district[0], factor=factor)
                    plan.traffic.append((city, district[0], start, end, factor, mid))
        for device, info in sorted(self.net.devices.items()):
            for day in days:
                key = ("ordinary-night", device, day.isoformat())
                if info.kind == "DRIVER_APP" and d.chance(.015, *key) and not any(local_date(w[0]) == day for w in plan.device_down.get(device, ())):
                    # A phone that dies in the afternoon and is charged the next morning.
                    start = local_dt(day, "13:00") + timedelta(minutes=d.integer(0, 300, *key, "start"))
                    end = local_dt(day + timedelta(days=1), "06:30") + timedelta(minutes=d.integer(0, 90, *key, "end"))
                    mid = plan.add("DEVICE_OUTAGE", "PHONE_OFFLINE", start, end, origin="base", device=device, device_kind=info.kind)
                    plan.device_down.setdefault(device, []).append((start, end, mid))
        for sid, s in sorted(self.shipments.items()):
            for parcel in s.parcels:
                if parcel.true_kg >= 1.5 and d.chance(.025, "ordinary-declaration", parcel.pid):
                    # A sender who guessed the weight: usually within tolerance, sometimes not.
                    factor = d.uniform(.78, .95, "ordinary-declaration-f", parcel.pid) if d.chance(.5, "ordinary-declaration-dir", parcel.pid) \
                        else d.uniform(1.06, 1.3, "ordinary-declaration-f", parcel.pid)
                    parcel.declared_kg = round(parcel.true_kg * factor, 2)
                    mid = plan.add("DECLARED_WEIGHT_WRONG", "ROUGH_ESTIMATE", s.booked_at, None, origin="base", pid=parcel.pid, sid=sid)
                    plan.on_parcel(parcel.pid, "DECLARED_WEIGHT_WRONG", mid, factor=round(factor, 3))
        for sid, s in sorted(self.shipments.items()):
            if s.recipient_kind == "Customer" and d.chance(.03, "ordinary-question", sid):
                at = s.booked_at + timedelta(hours=d.uniform(6, 40, "ordinary-question-at", sid))
                mid = plan.add("CUSTOMER_COMPLAINT", "STATUS_QUESTION", at, None, origin="base", sid=sid)
                plan.on_shipment(sid, "CUSTOMER_COMPLAINT", mid, subtype="STATUS_QUESTION", at=at)

    # ------------------------------------------------------------------ loop
    def run(self):
        sim = self.simulate()
        history = []
        for self.round in range(MAX_ROUNDS):
            counts = self.counts()
            need = {(m, split): self.config.target(m, split, self.split_sizes[split]) - counts.get((m, split), 0)
                    for m in SCHEDULED for split in SPLITS}
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
        sim = Simulation(self.config, self.net, self.d, self.shipments, self.plan).run()
        self.caused, self.exposed = self.consequences(sim)
        return sim

    def whole_seconds(self):
        """Mechanism windows are whole-second instants, like every record time."""
        def sec(t):
            return t.replace(microsecond=0) if isinstance(t, datetime) else t
        plan = self.plan
        for table in (plan.device_down, plan.device_loss, plan.backlog, plan.scale_drift, plan.sms_outage, plan.clerk, plan.reader,
                      plan.printer, plan.chute):
            for key, rows in table.items():
                table[key] = [tuple(sec(v) for v in row) for row in rows]
        plan.traffic = [(c, d, sec(a), sec(b), f, m) for c, d, a, b, f, m in plan.traffic]
        for mech in plan.items.values():
            mech.started_at, mech.ended_at = sec(mech.started_at), sec(mech.ended_at)
        for flags in plan.shipment.values():
            for mid, params in flags.values():
                for key in ("start", "end", "from", "until", "at"):
                    if key in params:
                        params[key] = sec(params[key])

    # ------------------------------------------------------------------ counting causes
    def consequences(self, sim):
        """(mid -> shipments the mechanism caused a deviation on, mid -> shipments it only touched)."""
        caused = defaultdict(set, {mid: set(sids) for mid, sids in sim.touch_ship.items()})
        exposed = defaultdict(set, {mid: set(sids) for mid, sids in sim.exposed_ship.items()})
        held, harmless = held_past_deadline(self.config, sim, upload_times(self.config, self.net, self.d, self.shipments, sim, self.plan))
        for mid, sids in held.items():
            caused[mid] |= sids
        for mid, sids in harmless.items():
            exposed[mid] |= sids
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
                    caused[mid].add(sid)       # A claim on a delivered parcel needs a person.
            elif sid not in handed or params["at"] < handed[sid]:
                exposed[mid].add(sid)          # A question: an inbound message, never a cause.
        for mid in caused:
            exposed[mid] -= caused[mid]
        return dict(caused), {mid: sids for mid, sids in exposed.items() if sids}

    def affected(self, sim=None):
        return self.caused

    def counts(self):
        dedup = defaultdict(set)
        for mid, sids in self.caused.items():
            for sid in sids:
                dedup[(self.plan.items[mid].type, self.split_of[sid])].add(sid)   # A shipment counts once per mechanism type.
        return {key: len(value) for key, value in dedup.items()}

    def busy(self):
        """Shipments that already carry a scheduled cause: the next cause is placed elsewhere when it can be."""
        out = {sid for mid, sids in self.caused.items() if self.plan.items[mid].origin == "scheduled" for sid in sids}
        for table in (self.plan.shipment, self.plan.parcel):
            for key, flags in table.items():
                if any(self.plan.items[mid].origin == "scheduled" for mid, _ in flags.values()):
                    out.add(sid_of(key))
        return out

    # ------------------------------------------------------------------ helpers
    def key(self, *parts):
        return ("sched", self.round, *parts)

    def in_split(self, sid, split):
        return self.split_of.get(sid) == split

    def consumer(self, sid):
        return self.shipments[sid].recipient_kind == "Customer"

    def pick(self, candidates, n, *key):
        """n of the candidates, preferring shipments without a scheduled cause."""
        busy = self.busy()
        candidates = sorted(set(candidates))
        free = [c for c in candidates if sid_of(c) not in busy]
        chosen = self.d.sample(free, n, *self.key(*key))
        if len(chosen) < n:
            chosen += self.d.sample([c for c in candidates if c not in set(free)], n - len(chosen), *self.key(*key, "busy"))
        return chosen

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
        """One of the (count, ...) options that cover the need, at random; if none does, one of the three largest.
        Random on purpose: a rule such as "the smallest that fits" would tie each mechanism to the same facilities,
        devices and routes in every world, and a resource's identity would then predict the cause."""
        ranked = sorted(options, key=lambda o: (-o[0], str(o[1:3])))
        # Among those that fit without much excess when there are any (a fault placed for three shipments should not
        # land on thirty), else among the three smallest that cover it, else among the three largest.
        enough = [o for o in ranked if need <= o[0] <= 2 * need + 1] or [o for o in ranked if o[0] >= need][-3:] or ranked[:3]
        return enough[int(self.d.u(*self.key("choose", *key)) * len(enough))] if enough else None

    def acts(self, sim, kind, **match):
        return [a for a in sim.acts if a["type"] == kind and all(a.get(k) == v for k, v in match.items())]

    def fresh(self, sids):
        busy = self.busy()
        return {sid for sid in sids if sid not in busy}

    def routes_with(self, sim, split, mtype, per_route):
        """Route options (count of fresh shipments of the split it would act on, rid, key, route), most first.
        per_route: route -> shipments of the split the fault could act on there."""
        options = []
        for rid, route in sorted(sim.routes.items()):
            key = (route.depot, route.date, route.slot)
            if mtype in self.plan.route.get(key, {}):
                continue
            mine = self.fresh(sid for sid in per_route(route) if self.in_split(sid, split))
            if mine:
                options.append((len(mine), rid, key, route))
        return options

    def on_routes(self, sim, split, n, mtype, subtype, per_route, low, high, *, started="08:00", extra=None):
        """Give routes a behaviour fault with a propensity in [low, high] until about n shipments are expected."""
        expected = 0.0
        options = self.routes_with(sim, split, mtype, per_route)
        while options and expected < n:
            chosen = self.choose(options, max(1, math.ceil((n - expected) / ((low + high) / 2))), mtype, split, len(options))
            options.remove(chosen)
            count, rid, key, route = chosen
            p = round(self.d.uniform(low, high, *self.key(mtype, "p", rid)), 2)
            params = {"p": p, **(extra(route) if extra else {})}
            mid = self.plan.add(mtype, subtype, local_dt(route.date, started), local_dt(route.date, self.config.session_end),
                                route=rid, driver=route.driver, propensity=p)
            self.plan.route.setdefault(key, {})[mtype] = (mid, params)
            expected += count * p

    def in_window(self, table, key, rows, n, mtype, subtype, low, high, *, min_hours, max_hours, tag, **params):
        """A propensity window on a facility or device covering about n / propensity of its records."""
        p = round(self.d.uniform(low, high, *self.key(mtype, "p", *tag)), 2)
        start, end = self.sized(rows, max(2, math.ceil(n / p)), min_hours=min_hours, max_hours=max_hours, key=(mtype, *tag))
        mid = self.plan.add(mtype, subtype, start, end, propensity=p, **params)
        getattr(self.plan, table).setdefault(key, []).append((start, end, p, mid))
        return sum(1 for t, _ in rows if start <= t < end) * p

    # ------------------------------------------------------------------ causes local to one parcel or one recipient
    def _parcel_mech(self, mtype, pids, subtype, **params):
        for pid in pids:
            sid = sid_of(pid)
            mid = self.plan.add(mtype, subtype, self.shipments[sid].booked_at, None, pid=pid, sid=sid)
            self.plan.on_parcel(pid, mtype, mid, **params(pid) if callable(params) else params)

    def _ship_mech(self, mtype, sids, subtype, params):
        for sid in sids:
            s = self.shipments[sid]
            p = params(sid)
            mid = self.plan.add(mtype, p.pop("_subtype", subtype), p.pop("_started", s.booked_at), p.pop("_ended", None), sid=sid)
            self.plan.on_shipment(sid, mtype, mid, **p)

    def add_recipient_unavailable(self, sim, split, n):
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
        self._ship_mech("RECIPIENT_UNAVAILABLE", self.pick(sids, n, "ru", split), "AWAY", params)

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

    def add_declared_weight_wrong(self, sim, split, n):
        taken = self.flagged(self.plan.parcel, "DECLARED_WEIGHT_WRONG")
        pids = [p.pid for s in self.shipments.values() if s.split == split for p in s.parcels if p.pid not in taken and p.true_kg >= 1.5]
        for pid in self.pick(pids, n, "dw", split):
            parcel = next(p for p in self.shipments[sid_of(pid)].parcels if p.pid == pid)
            # The range overlaps what a drifting scale shows (a tenth to nearly half off), so the size of the gap says little.
            factor = (self.d.uniform(.55, .88, *self.key("dw-f", pid)) if self.d.chance(.5, *self.key("dw-dir", pid))
                      else self.d.uniform(1.14, 1.9, *self.key("dw-f2", pid)))
            parcel.declared_kg = round(parcel.true_kg * factor, 2)
            self._parcel_mech("DECLARED_WEIGHT_WRONG", [pid], "DECLARATION_ERROR", factor=round(factor, 3))

    def add_customer_complaint(self, sim, split, n):
        # A non-receipt claim on a parcel that was handed to its recipient with complete proof.
        taken = self.flagged(self.plan.shipment, "CUSTOMER_COMPLAINT")
        delivered = {a["sid"]: a["t"] for a in self.acts(sim, "handoff") if a["person_type"] == "EXPECTED_RECIPIENT"}
        sids = [sid for sid in delivered if self.in_split(sid, split) and self.consumer(sid) and sid not in taken]
        for sid in self.pick(sids, n, "cc", split):
            mid = self.plan.add("CUSTOMER_COMPLAINT", CLAIM_SUBTYPE, delivered[sid], None, sid=sid)
            self.plan.on_shipment(sid, "CUSTOMER_COMPLAINT", mid, subtype=CLAIM_SUBTYPE)

    # ------------------------------------------------------------------ behaviour of a driver on a route
    def route_stops(self, sim, split, *, consumer=True):
        """route -> shipments of the split loaded on it (consumer deliveries only by default)."""
        return lambda route: {sid_of(pid) for pid in route.loaded if not consumer or self.consumer(sid_of(pid))}

    def add_assigned_not_loaded(self, sim, split, n):
        self.on_routes(sim, split, n, "ASSIGNED_NOT_LOADED", "LEFT_ON_SHELF", lambda route: {sid_of(pid) for pid in route.parcels}, .12, .28,
                       started="07:30")

    def add_delivery_scan_skipped(self, sim, split, n):
        done = defaultdict(set)
        for a in self.acts(sim, "handoff"):
            if a["person_type"] in ("EXPECTED_RECIPIENT", "LEFT_AT_DOOR"):
                done[sim.acts_by_id(a["attempt"])["route"]].add(a["sid"])
        self.on_routes(sim, split, n, "DELIVERY_SCAN_SKIPPED", "APP_FLOW_NOT_COMPLETED",
                       lambda route: {sid for sid in done.get(route.rid, ()) if self.consumer(sid)}, .2, .4)

    def add_return_scan_skipped(self, sim, split, n):
        back = defaultdict(set)
        for a in self.acts(sim, "scan", obs="RETURN_SCAN"):
            back[a["route"]].add(a["sid"])
        for row in sim.events:
            if row["type"] == "returned_unscanned":
                back[row["route"]].add(sid_of(row["pid"]))
        self.on_routes(sim, split, n, "RETURN_SCAN_SKIPPED", "CHECK_IN_NOT_SCANNED", lambda route: back.get(route.rid, set()), .6, .9,
                       started="16:00")

    def add_neighbour_receives(self, sim, split, n):
        # Acts where the recipient is out: the stops that failed for that reason in the last run.
        out = defaultdict(set)
        for a in self.acts(sim, "attempt"):
            if a["disposition"] == "FAILED" and a.get("reason") in ("RECIPIENT_NOT_REACHED", "CUSTOMER_REQUESTED_RESCHEDULE"):
                out[a["route"]].add(a["sid"])
        for a in self.acts(sim, "handoff"):
            if a["person_type"] in ("OTHER_PERSON",):
                out[sim.acts_by_id(a["attempt"])["route"]].add(a["sid"])
        self.on_routes(sim, split, n, "NEIGHBOUR_RECEIVES", "HANDED_TO_NEIGHBOUR",
                       lambda route: {sid for sid in out.get(route.rid, ()) if self.consumer(sid)}, .6, .9)

    def add_misdelivery(self, sim, split, n):
        self.on_routes(sim, split, n, "MISDELIVERY", "WRONG_BUILDING", self.route_stops(sim, split), .12, .25)

    def add_contractor_retains(self, sim, split, n):
        # A driver who keeps what is left on board after the shift, or leaves the route early with it.
        undelivered = defaultdict(set)
        for a in self.acts(sim, "attempt", disposition="FAILED"):
            undelivered[a["route"]].add(a["sid"])
        expected = 0
        options = []
        for rid, route in sorted(sim.routes.items()):
            key = (route.depot, route.date, route.slot)
            if "CONTRACTOR_RETAINS" in self.plan.route.get(key, {}) or self.net.drivers[route.driver].employment == "EMPLOYEE":
                continue
            stops = [s for s in route.stops if not s.get("foreign")]
            mine = self.fresh(s["sid"] for s in stops if self.in_split(s["sid"], split))
            if len(stops) >= 3 and mine:
                options.append((len(mine), rid, key, route, stops))
        options = self.d.shuffled(sorted(options, key=lambda o: o[1]), *self.key("cr-order", split))
        for count, rid, key, route, stops in options:
            if expected >= n:
                break
            kept = self.fresh(sid for sid in undelivered.get(rid, ()) if self.in_split(sid, split))
            leaves = not kept or self.d.chance(.5, *self.key("cr-kind", rid))
            quit_after = None
            if leaves:
                wanted = min(max(1, n - expected), 3)
                quit_after = max(1, len(stops) - wanted - self.d.integer(0, 1, *self.key("cr-quit", rid)))
                expected += len({s["sid"] for s in stops[quit_after:] if self.in_split(s["sid"], split)})
            else:
                expected += len(kept)
            returns = round(self.d.uniform(20, 52, *self.key("cr-ret", rid))) if self.d.chance(.5, *self.key("cr-ret?", rid)) else None
            mid = self.plan.add("CONTRACTOR_RETAINS", "LEFT_ROUTE_WITH_PARCELS" if leaves else "PARCELS_KEPT_AFTER_SHIFT",
                                local_dt(route.date, "08:00"), None, route=rid, driver=route.driver, returns_after_hours=returns)
            self.plan.route.setdefault(key, {})["CONTRACTOR_RETAINS"] = (mid, {"returns_after_hours": returns, "quit_after": quit_after})

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
            mine = self.fresh(sid for sid in a.shipments if self.in_split(sid, split))
            on_duty = [d for d in self.net.depot_drivers[depot] if self.net.drivers[d].off_weekday != day.weekday()]
            if len(a.shipments) >= 4 and mine and (len(routes) >= 2 or len(on_duty) >= 2):
                # A depot with one route that day dispatches a second driver as well (the scenario's helper run).
                options.append((-len(mine), depot, day, a.slot, 1 - a.slot if len(routes) < 2 else next(r.slot for r in routes if r.rid != a.rid)))
        options = self.d.shuffled(sorted(options, key=lambda o: (o[1], o[2])), *self.key("uh-order", split))
        for _, depot, day, a, b in options:
            if estimate >= n:
                break
            k = min(max(1, n - estimate), self.d.integer(2, 3, *self.key("uh-k", depot, day)))
            after = self.d.integer(1, 2, *self.key("uh-after", depot, day))
            mid = self.plan.add("UNRECORDED_HANDOFF", "PARCELS_PASSED_BETWEEN_DRIVERS", local_dt(day, "09:00"), None, depot=depot)
            self.plan.depot_day.setdefault((depot, day), {})["UNRECORDED_HANDOFF"] = (mid, {"from": a, "to": b, "after": after, "k": k})
            estimate += k

    def add_manifest_error(self, sim, split, n):
        options = []
        for rid, route in sim.routes.items():
            key = (route.depot, route.date, route.slot)
            if "MANIFEST_ERROR" in self.plan.route.get(key, {}) or len(route.loaded) < 2:
                continue
            if self.fresh(sid_of(pid) for pid in route.loaded if self.in_split(sid_of(pid), split)):
                options.append((rid, key))
        for rid, key in self.d.sample(sorted(options), n, *self.key("me", split)):
            fresh = self.fresh(sid_of(pid) for pid in sim.routes[rid].loaded if self.in_split(sid_of(pid), split))
            prefer = [pid for pid in sim.routes[rid].loaded if sid_of(pid) in fresh]
            mid = self.plan.add("MANIFEST_ERROR", "REVISION_DROPPED_LOADED_PARCEL", local_dt(key[1], "08:00"), None, route=rid)
            self.plan.route.setdefault(key, {})["MANIFEST_ERROR"] = (mid, {"prefer": prefer})

    # ------------------------------------------------------------------ a clerk shift, a reader, a printer, a chute
    def _rows(self, sim, split, match, key_of):
        """key -> time-ordered (t, sid) rows of this split's scan acts matching `match`, per local day."""
        rows = defaultdict(list)
        for a in sim.acts:
            if a["type"] == "scan" and a.get("sid") and self.in_split(a["sid"], split) and match(a):
                rows[(key_of(a), local_date(a["t"]))].append((a["t"], a["sid"]))
        return rows

    def _window_options(self, rows, table):
        return [(len(self.fresh(sid for _, sid in r)), key, day, r) for (key, day), r in sorted(rows.items())
                if not any(local_date(w[0]) == day for w in getattr(self.plan, table).get(key, []))]

    def add_scan_skipped_at_receipt(self, sim, split, n):
        depot = self._rows(sim, split, lambda a: a["obs"] == "HANDHELD_RECEIPT" and a.get("facility", "").startswith("DEMO-DEPOT"),
                           lambda a: a["facility"])
        hub = self._rows(sim, split, lambda a: a["obs"] == "CONTAINER_SCAN" and a.get("facility", "").startswith("DEMO-HUB") and not a.get("trip"),
                         lambda a: a["facility"])
        for part, (rows, stage) in enumerate(((depot, "depot"), (hub, "hub")) if n >= 3 else ((depot, "depot"),)):
            want = n - n // 3 if stage == "depot" and n >= 3 else n // 3 if stage == "hub" else n
            chosen = self.choose(self._window_options(rows, "clerk"), want, "skip", split, stage)
            if chosen:
                _, facility, day, r = chosen
                self.in_window("clerk", facility, r, want, "SCAN_SKIPPED_AT_RECEIPT", f"{stage.upper()}_RECEIPT_NOT_SCANNED", .35, .6,
                               min_hours=1, max_hours=5, tag=(facility, day), facility=facility, stage=stage)

    def add_label_misread(self, sim, split, n):
        sorter = self._rows(sim, split, lambda a: a["obs"] == "SORTER_READ", lambda a: a["device"])
        handheld = self._rows(sim, split, lambda a: a["obs"] == "HANDHELD_RECEIPT" and a.get("facility", "").startswith("DEMO-DEPOT"),
                              lambda a: a["device"])
        rows, stage = (sorter, "SORT") if self.d.chance(.7, *self.key("mr-stage", split)) else (handheld, "DEPOT")
        chosen = self.choose(self._window_options(rows, "reader"), math.ceil(n / .2), "misread", split)
        if chosen:
            _, device, day, r = chosen
            self.in_window("reader", device, r, n, "LABEL_MISREAD", f"{stage}_READER_MISREADS", .12, .28, min_hours=1.5, max_hours=8,
                           tag=(device, day), device=device)

    def add_wrong_label_applied(self, sim, split, n):
        rows = self._rows(sim, split, lambda a: a["obs"] == "HANDHELD_RECEIPT" and a.get("facility") == self.shipments[a["sid"]].origin_facility
                          and not a.get("trip"), lambda a: a["facility"])
        chosen = self.choose(self._window_options(rows, "printer"), math.ceil(n / .45), "label", split)
        if chosen:
            _, facility, day, r = chosen
            self.in_window("printer", facility, r, n, "WRONG_LABEL_APPLIED", "LABEL_BATCH_MIXED_UP", .3, .6, min_hours=1, max_hours=6,
                           tag=(facility, day), facility=facility)

    def add_missort(self, sim, split, n):
        # A container loaded onto the wrong linehaul truck, and a sorter chute mapped to another depot's bag for a while.
        estimate = 0
        options = []
        for tid, state in sim.trips.items():
            plan = state.plan
            if plan.kind != "LINEHAUL" or tid in self.plan.misload or not state.containers:
                continue
            biggest = max(state.containers, key=lambda c: (len(sim.containers[c].parcels), c))
            mine = self.fresh(sid_of(pid) for pid in sim.containers[biggest].parcels if self.in_split(sid_of(pid), split))
            others = [t for t in self.net.trips.values() if t.kind == "LINEHAUL" and t.origin == plan.origin and t.destination != plan.destination
                      and timedelta(minutes=20) <= t.scheduled_departure - plan.scheduled_departure <= timedelta(hours=4)]
            if mine and others:
                options.append((len(mine), tid, sorted(others, key=lambda t: t.scheduled_departure)[0].id, mine))
        chosen = self.choose(options, max(1, n // 2), "misload", split) if n >= 2 else None
        if chosen and chosen[0] <= n:
            count, tid, wrong, mine = chosen
            mid = self.plan.add("MISSORT", "CONTAINER_ON_WRONG_TRUCK", self.net.trips[tid].scheduled_departure, None, trip=tid, wrong_trip=wrong)
            self.plan.misload[tid] = (wrong, mid)
            estimate += count
        if estimate >= n:
            return
        rows = self._rows(sim, split, lambda a: a["obs"] == "SORTER_READ", lambda a: a["facility"])
        chosen = self.choose(self._window_options(rows, "chute"), math.ceil((n - estimate) / .4), "chute", split)
        if chosen:
            _, sort, day, r = chosen
            depots = sorted(f for f, x in self.net.facilities.items() if x.kind == "DeliveryDepot")
            wrong = self.d.choice(depots, *self.key("ms-depot", sort, day))
            self.in_window("chute", sort, r, n - estimate, "MISSORT", "CHUTE_MAPPED_TO_WRONG_BAG", .3, .5, min_hours=1, max_hours=5,
                           tag=(sort, day), facility=sort, depot=wrong)

    # ------------------------------------------------------------------ shared-resource mechanisms
    def _rows_by(self, sim, split, kinds, *, devices=None):
        """(device, local day) -> time-ordered (t, sid) rows of this split's records made by that device."""
        rows = defaultdict(list)
        for a in sim.acts:
            if a["type"] in kinds and a.get("device") and a.get("sid") and self.in_split(a["sid"], split):
                if devices is None or (a["device"] in self.net.devices and self.net.devices[a["device"]].kind in devices):
                    rows[(a["device"], local_date(a["t"]))].append((a["t"], a["sid"]))
        return rows

    def _device_free(self, device, day):
        return not any(local_date(w[0]) == day or local_date(w[1]) == day
                       for table in (self.plan.device_down, self.plan.device_loss) for w in table.get(device, ()))

    def add_device_outage(self, sim, split, n):
        # Several outages of two or three shipments each, on the device kinds in turn.
        parts = max(1, math.ceil(n / 3))
        each = math.ceil(n / parts)
        cycle = (("DRIVER_APP",), ("FACILITY_HANDHELD",), ("SORTER_READER", "FACILITY_HANDHELD"))
        for part in range(parts):
            kinds = cycle[(part + self.round) % len(cycle)]
            rows = self._rows_by(sim, split, ("scan", "attempt"), devices=kinds)
            options = [(len(self.fresh(sid for _, sid in r)), dev, day, r) for (dev, day), r in sorted(rows.items()) if self._device_free(dev, day)]
            chosen = self.choose(options, each, "outage", split, part)
            if not chosen:
                continue
            _, device, day, r = chosen
            kind = self.net.devices[device].kind
            if kind == "DRIVER_APP":
                start, end = self.sized(r, each, min_hours=1, max_hours=8, key=("outage", device, day))
                if self.d.chance(.6, *self.key("out-night", device, day)):
                    # The phone dies before the day's last few stops and stays off until the driver logs in the next morning.
                    last = sorted(r)[-min(len(r), each + 1):]
                    start = last[0][0] - timedelta(minutes=self.d.integer(3, 15, *self.key("out-dies", device, day)))
                    end = local_dt(day + timedelta(days=1), "06:30") + timedelta(minutes=self.d.integer(0, 120, *self.key("out-login", device, day)))
                else:
                    end += timedelta(hours=self.d.uniform(.5, 6, *self.key("out-tail", device, day)))
                subtype = "PHONE_OFFLINE"
            else:
                start, end = self.sized(r, each, min_hours=1, max_hours=7, key=("outage", device, day))
                end += timedelta(hours=self.d.uniform(.5, 4, *self.key("out-tail", device, day)))
                subtype = "UPLINK_LOST" if kind == "SORTER_READER" else self.d.choice(("WIFI_LOST", "APP_SYNC_STALLED"), *self.key("out-sub", device, day))
            mid = self.plan.add("DEVICE_OUTAGE", subtype, start, end, device=device, device_kind=kind)
            self.plan.device_down.setdefault(device, []).append((start, end, mid))

    def add_partial_upload_loss(self, sim, split, n):
        parts = max(1, math.ceil(n / 3))
        each = math.ceil(n / parts)
        for part in range(parts):
            rows = self._rows_by(sim, split, ("scan", "attempt"), devices=("DRIVER_APP", "FACILITY_HANDHELD"))
            options = [(len(self.fresh(sid for _, sid in r)), dev, day, r) for (dev, day), r in sorted(rows.items()) if self._device_free(dev, day)]
            chosen = self.choose(options, each, "loss", split, part)
            if not chosen:
                continue
            _, device, day, r = chosen
            start, end = self.sized(r, each, min_hours=.25, max_hours=8, key=("loss", device, day))
            fraction = round(self.d.uniform(.35, .6, *self.key("loss-f", device, day)), 2)
            # The stuck records leave with the nightly full sync, or earlier when someone restarts the app.
            nightly = local_dt(local_date(end) + timedelta(days=1), "02:30") if local_hour(end) >= 2.5 else local_dt(local_date(end), "02:30")
            release = nightly if self.d.chance(.5, *self.key("loss-release", device, day)) else min(
                nightly, end + timedelta(minutes=self.d.integer(30, 360, *self.key("loss-restart", device, day))))
            mid = self.plan.add("PARTIAL_UPLOAD_LOSS", "OUTBOX_STUCK", start, end, device=device, fraction=fraction)
            self.plan.device_loss.setdefault(device, []).append((start, end, fraction, mid, release))

    def add_facility_backlog(self, sim, split, n):
        # A backlog is placed where it makes parcels miss something: at a sort before the evening linehaul cutoffs, at
        # a depot while the morning feeder is being shelved before loading.
        options = []
        for facility, log in sorted(sim.service_log.items()):
            kind = self.net.facilities[facility].kind
            if (kind == "SortingCenter") != (self.round % 2 == 0):
                continue
            by_day = defaultdict(list)
            for ready, done, pid in log:
                if not self.in_split(sid_of(pid), split):
                    continue
                # Slack to what the parcel went on to catch: the bag's departure cutoff at a sort, the morning's
                # route planning at a depot. Only parcels with little slack can be made to miss it.
                if kind == "SortingCenter":
                    trip = sim.bag_trip(pid, facility, done)
                    slack = (trip.cutoff - done).total_seconds() / 3600 if trip else 99
                else:
                    slack = (local_dt(sim.route_day(done), "08:40") - done).total_seconds() / 3600
                if 0 < slack < 2.2:
                    by_day[local_date(ready)].append((ready, sid_of(pid)))
            for day, r in by_day.items():
                if not any(local_date(w[0]) == day for w in self.plan.backlog.get(facility, [])):
                    options.append((len(self.fresh(sid for _, sid in r)), facility, day, r))
        # A facility-day whose volume is close to what is still needed (a backlog acts on everything it holds): one of
        # the four closest, at random.
        near = sorted(options, key=lambda o: (abs(o[0] - n), o[1], o[2]))[:4]
        chosen = near[int(self.d.u(*self.key("backlog", split)) * len(near))] if near else None
        if not chosen:
            return
        _, facility, day, r = chosen
        kind = self.net.facilities[facility].kind
        start = min(t for t, _ in r) - timedelta(minutes=self.d.integer(10, 40, *self.key("bl-lead", facility, day)))
        end = max(t for t, _ in r) + timedelta(hours=self.d.uniform(2.2, 3.2, *self.key("bl-len", facility, day)))
        factor = round(self.d.uniform(.12, .25, *self.key("bl-f", facility, day)), 2)
        subtype = (self.d.choice(("SORTER_JAM", "STAFF_SHORTAGE"), *self.key("bl-sub", facility, day)) if kind == "SortingCenter"
                   else self.d.choice(("RECEIVING_CONGESTION", "STAFF_SHORTAGE"), *self.key("bl-sub", facility, day)))
        mid = self.plan.add("FACILITY_BACKLOG", subtype, start, end, facility=facility, factor=factor)
        self.plan.backlog.setdefault(facility, []).append((start, end, factor, mid))

    def add_late_linehaul(self, sim, split, n):
        parts = max(1, math.ceil(n / 3))
        each = math.ceil(n / parts)
        for part in range(parts):
            options = []
            for tid, state in sorted(sim.trips.items()):
                if state.plan.kind not in ("LINEHAUL", "FEEDER") or tid.endswith("-R") or tid in self.plan.trip_delay or not state.parcels:
                    continue
                mine = self.fresh(sid_of(pid) for pid in state.parcels if self.in_split(sid_of(pid), split))
                if mine:
                    options.append((len(mine), tid, state.plan.kind, mine))
            chosen = self.choose(options, each, "late", split, part)
            if not chosen:
                continue
            _, tid, _, mine = chosen
            kind = "BREAKDOWN" if self.d.chance(.5, *self.key("lh-kind", tid)) else "DEPARTURE_DELAY"
            hours = self.d.uniform(3, 8, *self.key("lh-s", tid)) if kind == "BREAKDOWN" else self.d.uniform(2.5, 6, *self.key("lh-s", tid))
            seconds = round(hours * 3600)
            fraction = round(self.d.uniform(.2, .7, *self.key("lh-f", tid)), 2)
            plan = self.net.trips[tid]
            mid = self.plan.add("LATE_LINEHAUL", kind, plan.scheduled_departure, plan.scheduled_arrival + timedelta(seconds=seconds),
                                trip=tid, delay_seconds=seconds)
            self.plan.trip_delay[tid] = (kind, seconds, fraction, mid)

    def add_scale_drift(self, sim, split, n):
        rows = defaultdict(list)
        for a in self.acts(sim, "scan", obs="SCALE_WEIGH"):
            if self.in_split(a["sid"], split) and a["facility"].startswith("DEMO-SORT"):   # Induction scales (not depot check scales).
                rows[(a["device"], local_date(a["t"]))].append((a["t"], a["sid"]))
        options = [(len(self.fresh(sid for _, sid in r)), dev, day, r) for (dev, day), r in sorted(rows.items())
                   if not any(local_date(w[0]) == day for w in self.plan.scale_drift.get(dev, []))]
        chosen = self.choose(options, n, "drift", split)
        if not chosen:
            return
        _, device, day, r = chosen
        start, end = self.sized(r, n + 1, min_hours=1.5, max_hours=8, key=("drift", device, day))
        factor = self.d.uniform(.12, .45, *self.key("sd-f", device, day)) * (1 if self.d.chance(.7, *self.key("sd-sign", device, day)) else -1)
        mid = self.plan.add("SCALE_DRIFT", "CALIBRATION_DRIFT", start, end, device=device, factor=round(factor, 3))
        self.plan.scale_drift.setdefault(device, []).append((start, end, round(factor, 3), mid))

    def add_otp_not_received(self, sim, split, n):
        # Mostly gateway outages on one carrier route (shared), plus individual number problems.
        rows = defaultdict(list)
        for a in self.acts(sim, "comm", purpose="OTP"):
            if self.in_split(a["sid"], split):
                rows[(a["carrier"], local_date(a["t"]))].append((a["t"], a["sid"]))
        options = [(len(self.fresh(sid for _, sid in r)), route, day, r) for (route, day), r in sorted(rows.items())
                   if not any(local_date(w[0]) == day for w in self.plan.sms_outage.get(route, []))]
        want = max(1, math.ceil(n * .6))
        chosen = self.choose(options, want, "sms", split) if n >= 3 else None   # Small needs: individual number problems only.
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

    def add_traffic_disruption(self, sim, split, n):
        # A road closure or a serious accident shuts a district to delivery vans from some point of the day until the
        # evening: the stops still open there cannot be attempted. (Rush-hour congestion is ordinary operation.)
        stops = defaultdict(list)
        for a in self.acts(sim, "attempt"):
            if self.in_split(a["sid"], split) and 9 <= local_hour(a["t"]) < 18:
                s = self.shipments[a["sid"]]
                stops[(s.dest_city, s.recipient["district"], local_date(a["t"]))].append((a["t"], a["sid"]))
        options = [(len(self.fresh(sid for _, sid in rows)), (city, district, day), rows) for (city, district, day), rows in sorted(stops.items())
                   if not any(c == city and local_date(s) == day and self.plan.items[m].origin == "scheduled" for c, d, s, e, f, m in self.plan.traffic)]
        left = n
        while left > 0 and options:
            chosen = self.choose(options, min(left, 3), "closure", split, len(options))
            options.remove(chosen)
            _, (city, district, day), rows = chosen
            rows = sorted(rows)
            wanted = {sid for _, sid in rows[-min(left, 3):]}
            start = min(t for t, sid in rows if sid in wanted) - timedelta(minutes=self.d.integer(20, 60, *self.key("tr-s", city, district, day)))
            end = local_dt(day, self.config.session_end)
            subtype = self.d.choice(("ROAD_CLOSURE", "ACCIDENT"), *self.key("tr-sub", city, district, day))
            mid = self.plan.add("TRAFFIC_DISRUPTION", subtype, start, end, city=city, district=district, factor=8.0)
            self.plan.traffic.append((city, district, start, end, 8.0, mid))
            left -= len(wanted)
