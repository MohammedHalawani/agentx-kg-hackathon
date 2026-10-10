import { useEffect, useMemo, useRef, useState } from "react";
import {
  MapContainer,
  TileLayer,
  Marker,
  Polyline,
  Popup,
  Polygon,
  useMap,
  Tooltip as MapTooltip,
} from "react-leaflet";
import L from "leaflet";
import {
  Layers,
  LocateFixed,
  MapPinned,
  Plus,
  Minus,
  Building2,
} from "lucide-react";
import "leaflet/dist/leaflet.css";
import type { OperationalCase } from "@/domain/types";
import { useOperations } from "@/state/operations";
import { displayId } from "@/domain/case-view";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { SelectControl } from "@/components/select-control";
import { usePreferences } from "@/state/preferences";
const LAB_BUILD = import.meta.env.VITE_SUHAIL_DATA === "lab";

type MapFocus = { city: string; revision: number } | null;
type Cities = Record<string, [number, number]>;
/**
 * Where a shipment is drawn: its last confirmed custody observation. A backend case whose
 * evidence is not loaded yet is drawn at its destination city instead, and labelled so.
 */
function observationLocation(c: OperationalCase, cities: Cities) {
  const observed =
    c.evidence
      .filter((e) => e.confidence === "confirmed" && e.kind !== "gps")
      .at(-1) ?? (c.backend ? undefined : c.evidence[0]);
  if (observed)
    return { location: observed.location, facility: observed.facility };
  const city = cities[c.shipment.destination];
  return city
    ? { location: city, facility: `${c.shipment.destination} · destination city` }
    : null;
}
function NetworkEffects({
  cases,
  selected,
  fitKey,
  focus,
  cityLocations,
  stable,
}: {
  cases: OperationalCase[];
  selected?: OperationalCase;
  fitKey: number;
  focus: MapFocus;
  cityLocations: Cities;
  /** Backend queues are re-read on a timer: refit only when the set of shipments changes. */
  stable: boolean;
}) {
  const map = useMap();
  const { preferences } = usePreferences();
  const animate =
    preferences.motion !== "reduce" &&
    !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const ids = cases.map((c) => c.id).join(",");
  const previous = useRef({ ids, selectedId: selected?.id });
  useEffect(() => {
    const observer = new ResizeObserver(() => map.invalidateSize());
    observer.observe(map.getContainer());
    return () => observer.disconnect();
  }, [map]);
  useEffect(() => {
    const points = cases
      .flatMap((c) => [
        observationLocation(c, cityLocations)?.location,
        cityLocations[c.shipment.origin],
        cityLocations[c.shipment.destination],
      ])
      .filter((point): point is [number, number] => !!point);
    if (points.length)
      map.fitBounds(points, { padding: [55, 55], maxZoom: 8, animate: false });
    else map.setView([24.8, 45.3], 5, { animate: false });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- refit when the shipments change (backend: their set, not every poll)
  }, [stable ? ids : cases, fitKey, map]);
  useEffect(() => {
    if (
      selected &&
      previous.current.ids === ids &&
      previous.current.selectedId !== selected.id
    ) {
      const target = observationLocation(selected, cityLocations);
      if (target) map.panTo(target.location, { animate, duration: 0.35 });
    }
    previous.current = { ids, selectedId: selected?.id };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- pan when the selection changes
  }, [map, animate, stable ? selected?.id : selected, ids]);
  useEffect(() => {
    if (focus && cityLocations[focus.city])
      map.setView(cityLocations[focus.city], 10, { animate });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- focus requests carry their own revision
  }, [focus, map, animate]);
  return null;
}
function NetworkZoom() {
  const map = useMap();
  return (
    <div className="map-zoom">
      <Button
        size="icon"
        variant="ghost"
        aria-label="Zoom network in"
        onClick={() => map.zoomIn()}
      >
        <Plus size={15} />
      </Button>
      <Button
        size="icon"
        variant="ghost"
        aria-label="Zoom network out"
        onClick={() => map.zoomOut()}
      >
        <Minus size={15} />
      </Button>
    </div>
  );
}
export function NetworkMap({
  cases,
  selected,
  onSelect,
  focus,
}: {
  cases: OperationalCase[];
  selected?: OperationalCase;
  onSelect: (id: string) => void;
  focus: MapFocus;
}) {
  const { t } = usePreferences();
  const { catalog, backend: fromBackend } = useOperations();
  // Connected build: always the backend, so lab-only branches are removed at build time.
  const backend = !LAB_BUILD || fromBackend;
  const { facilities, cityLocations } = catalog;
  const [basemap, setBasemap] = useState("street");
  const [errors, setErrors] = useState(0);
  const [layers, setLayers] = useState({
    shipments: true,
    facilities: true,
    route: true,
  });
  const [fitKey, setFitKey] = useState(0);
  const effectiveBasemap = errors >= 3 ? "schematic" : basemap;
  const clusters = useMemo(() => {
    const groups = new Map<
      string,
      { location: [number, number]; facility: string; cases: OperationalCase[] }
    >();
    for (const c of cases) {
      const e = observationLocation(c, cityLocations);
      if (!e) continue;
      const key = e.location.join(",");
      const group = groups.get(key);
      if (group) group.cases.push(c);
      else
        groups.set(key, {
          location: e.location,
          facility: e.facility,
          cases: [c],
        });
    }
    return [...groups.entries()];
  }, [cases, cityLocations]);
  return (
    <section
      className="visualization network-map"
      aria-label="Shipment network map"
    >
      <div className="viz-header">
        <div className="flex items-center gap-2">
          <MapPinned size={15} />
          <h2>{t("Logistics network", "الشبكة اللوجستية")}</h2>
        </div>
        <span className="viz-subtitle">
          {cases.length}{" "}
          {backend
            ? t("matching cases", "حالات مطابقة")
            : t("matching shipments", "شحنات مطابقة")}
        </span>
      </div>
      <div className="map-canvas" dir="ltr" data-testid="network-map">
        <MapContainer
          center={[24.8, 45.3]}
          zoom={5}
          zoomControl={false}
          className="leaflet-canvas"
        >
          <NetworkEffects
            cases={cases}
            selected={selected}
            fitKey={fitKey}
            focus={focus}
            cityLocations={cityLocations}
            stable={backend}
          />
          <NetworkZoom />
          {effectiveBasemap === "street" ? (
            <TileLayer
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a>'
              eventHandlers={{ tileerror: () => setErrors((e) => e + 1) }}
            />
          ) : (
            <>
              <Polygon
                positions={[
                  [29.1, 34.9],
                  [31.5, 37.1],
                  [32.1, 39.2],
                  [29.3, 44.8],
                  [29.1, 47.9],
                  [26.7, 50.1],
                  [24.5, 51.2],
                  [22.5, 55.7],
                  [20, 52],
                  [18, 48],
                  [16.5, 43],
                  [17.3, 42.4],
                  [20, 40.5],
                  [22, 39],
                  [25, 37.2],
                  [28, 34.7],
                ]}
                pathOptions={{
                  fillColor: "#ece9df",
                  fillOpacity: 0.85,
                  color: "#cfcbbd",
                  weight: 1,
                }}
              />
              <Polyline
                positions={[
                  [21.5433, 39.1728],
                  [24.7136, 46.6753],
                  [26.4207, 50.0888],
                ]}
                pathOptions={{ color: "#d0cabd", weight: 6 }}
              />
              {Object.entries(cityLocations).map(([city, location]) => (
                <Marker
                  key={city}
                  position={location}
                  interactive={false}
                  icon={L.divIcon({
                    className: "city-label",
                    html: `<span>${city}</span>`,
                    iconSize: [110, 20],
                    iconAnchor: [-10, 0],
                  })}
                />
              ))}
            </>
          )}
          {layers.facilities &&
            facilities.map((f) => (
              <Marker
                key={f.id}
                position={f.location}
                title={f.name}
                alt={f.name}
                icon={L.divIcon({
                  className: "network-facility-marker",
                  html: "<span>▣</span>",
                  iconSize: [20, 20],
                  iconAnchor: [10, 10],
                })}
              >
                <MapTooltip>
                  {f.name} · {f.type}
                </MapTooltip>
              </Marker>
            ))}
          {layers.route && selected && (
            <Polyline
              positions={selected.route.expected}
              pathOptions={{
                color: "#8b6ccb",
                weight: 3,
                dashArray: "6 7",
                opacity: 0.65,
              }}
            >
              <MapTooltip>
                {displayId(selected)} ·{" "}
                {t(
                  "Planned route, not confirmed custody",
                  "مسار مخطط وليس حيازة مؤكدة",
                )}
              </MapTooltip>
            </Polyline>
          )}
          {layers.shipments &&
            clusters.map(([key, group]) => (
              <Marker
                key={key}
                position={group.location}
                title={`Shipment observations at ${group.facility}`}
                alt={`Shipment observations at ${group.facility}`}
                icon={L.divIcon({
                  className: `shipment-cluster ${group.cases.some((c) => c.id === selected?.id) ? "selected" : ""}`,
                  html: `<span>${group.cases.length}</span>`,
                  iconSize: [36, 36],
                  iconAnchor: [18, 18],
                })}
                eventHandlers={{
                  click: () =>
                    onSelect(
                      group.cases.find((c) => c.id === selected?.id)?.id ??
                        group.cases[0].id,
                    ),
                }}
              >
                <MapTooltip>
                  {group.facility} · {group.cases.length}{" "}
                  {t("parcel observations", "ملاحظات طرود")}
                </MapTooltip>
                <Popup>
                  <div className="network-popup">
                    <b>{group.facility}</b>
                    <p>
                      {t(
                        "Select a shipment observed here.",
                        "اختر شحنة لوحظت هنا.",
                      )}
                    </p>
                    {group.cases.map((c) => (
                      <Button
                        key={c.id}
                        variant="ghost"
                        size="sm"
                        onClick={() => onSelect(c.id)}
                        className={c.id === selected?.id ? "selected" : ""}
                      >
                        {displayId(c)}
                        <span>{c.issue}</span>
                      </Button>
                    ))}
                  </div>
                </Popup>
              </Marker>
            ))}
        </MapContainer>
        <div className="map-tools">
          <Button
            size="icon"
            variant="outline"
            aria-label="Fit matching shipments"
            onClick={() => setFitKey((k) => k + 1)}
          >
            <LocateFixed size={16} />
          </Button>
          <Popover>
            <PopoverTrigger asChild>
              <Button
                size="icon"
                variant="outline"
                aria-label="Network map layers"
              >
                <Layers size={16} />
              </Button>
            </PopoverTrigger>
            <PopoverContent className="layer-popover" align="end">
              <h3>{t("Network layers", "طبقات الشبكة")}</h3>
              {(["shipments", "facilities", "route"] as const).map((key) => (
                <label className="layer-option" key={key}>
                  <Checkbox
                    checked={layers[key]}
                    onCheckedChange={(v) =>
                      setLayers((p) => ({ ...p, [key]: v === true }))
                    }
                  />
                  {t(
                    {
                      shipments: "Shipment observations",
                      facilities: "Facilities",
                      route: "Selected planned route",
                    }[key],
                    {
                      shipments: "ملاحظات الشحنات",
                      facilities: "المرافق",
                      route: "المسار المخطط المحدد",
                    }[key],
                  )}
                </label>
              ))}
              <SelectControl
                label="Network base map"
                value={effectiveBasemap}
                onChange={(v) => {
                  setBasemap(v);
                  setErrors(0);
                }}
                options={[
                  { value: "street", label: "OpenStreetMap" },
                  {
                    value: "schematic",
                    label: t("Offline schematic", "مخطط دون اتصال"),
                  },
                ]}
              />
            </PopoverContent>
          </Popover>
        </div>
        <div className="map-location-label">
          <span className="live-dot" />
          {t(
            effectiveBasemap === "street"
              ? backend
                ? "Street map · backend records (synthetic)"
                : "Interactive map · synthetic observations"
              : "Offline schematic · synthetic observations",
            "خريطة تفاعلية · ملاحظات محاكاة",
          )}
        </div>
      </div>
      <div className="viz-legend">
        <span>
          <i className="dot purple" />
          {backend
            ? t(
                "Last confirmed custody, or destination city until evidence is loaded",
                "آخر حيازة مؤكدة، أو مدينة الوجهة حتى تُحمّل الأدلة",
              )
            : t("Confirmed parcel observations", "ملاحظات طرود مؤكدة")}
        </span>
        <span>
          <Building2 size={11} />
          {t("Facilities", "المرافق")}
        </span>
        <span className="legend-hint">
          {t(
            "Counts grouped at observed facilities",
            "تُجمع الأعداد في المرافق المرصودة",
          )}
        </span>
      </div>
    </section>
  );
}
