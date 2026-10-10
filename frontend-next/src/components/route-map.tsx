import { useEffect, useRef, useState } from "react";
import {
  MapContainer,
  TileLayer,
  Polyline,
  Marker,
  CircleMarker,
  Polygon,
  useMap,
  Tooltip as MapTooltip,
} from "react-leaflet";
import L from "leaflet";
import { Layers, LocateFixed, MapPinned } from "lucide-react";
import "leaflet/dist/leaflet.css";
import { facilities } from "@/data/fixtures";
import type { OperationalCase } from "@/domain/types";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Checkbox } from "@/components/ui/checkbox";
import { SelectControl } from "@/components/select-control";
import { usePreferences } from "@/state/preferences";

const country: [number, number][] = [
  [29.1, 34.9],
  [31.5, 37.1],
  [32.1, 39.2],
  [29.3, 44.8],
  [29.1, 47.9],
  [28.5, 48.4],
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
];
function MapEffects({
  c,
  selected,
  network,
  fitKey,
}: {
  c: OperationalCase;
  selected: string | null;
  network: boolean;
  fitKey: number;
}) {
  const map = useMap();
  const { preferences } = usePreferences();
  const previousSelection = useRef({ id: c.id, selected });
  const boundsKey = JSON.stringify(
    network
      ? facilities.map((f) => f.location)
      : c.evidence.map((e) => e.location),
  );
  useEffect(() => {
    map.fitBounds(JSON.parse(boundsKey), { padding: [35, 45], animate: false });
    const observer = new ResizeObserver(() => map.invalidateSize());
    observer.observe(map.getContainer());
    return () => observer.disconnect();
  }, [map, c.id, boundsKey, fitKey]);
  useEffect(() => {
    const e = c.evidence.find((e) => e.id === selected);
    const changed =
      previousSelection.current.id === c.id &&
      previousSelection.current.selected !== selected;
    previousSelection.current = { id: c.id, selected };
    if (e && changed)
      map.panTo(e.location, {
        animate:
          preferences.motion !== "reduce" &&
          !window.matchMedia("(prefers-reduced-motion: reduce)").matches,
        duration: 0.35,
      });
  }, [selected, c, map, preferences.motion]);
  return null;
}
export function RouteMap({
  c,
  selected,
  onSelect,
  stage,
  network = false,
  onFacility,
}: {
  c: OperationalCase;
  selected: string | null;
  onSelect: (id: string) => void;
  stage: number;
  network?: boolean;
  onFacility?: (id: string) => void;
}) {
  const { t } = usePreferences();
  const [layers, setLayers] = useState({
    expected: true,
    actual: true,
    vehicle: true,
    facilities: true,
    attempts: true,
  });
  const [basemap, setBasemap] = useState<"street" | "schematic">("street");
  const [errors, setErrors] = useState(0);
  const [fitKey, setFitKey] = useState(0);
  const effectiveBasemap = errors >= 3 ? "schematic" : basemap;
  const activeEvidence =
    stage === 1
      ? ["origin", "destination"]
      : stage === 2
        ? ["origin", "handover", "warehouse"]
        : stage === 6 || stage === 7
          ? ["recovery", "destination"]
          : [];
  return (
    <section
      className="visualization map-panel"
      aria-label={t("Route evidence map", "خريطة أدلة المسار")}
    >
      <div className="viz-header">
        <div className="flex items-center gap-2">
          <MapPinned size={15} />
          <h2>
            {t(
              network ? "Logistics network" : "Route evidence",
              network ? "الشبكة اللوجستية" : "أدلة المسار",
            )}
          </h2>
        </div>
        <span className="viz-subtitle">
          {t("Saudi Arabia", "المملكة العربية السعودية")}
        </span>
      </div>
      <div className="map-canvas" dir="ltr" data-testid="route-map">
        <MapContainer
          center={[25.5, 48.1]}
          zoom={6}
          zoomControl={false}
          attributionControl
          className="leaflet-canvas"
        >
          <MapEffects
            c={c}
            selected={selected}
            network={network}
            fitKey={fitKey}
          />
          <ZoomButtons />
          {effectiveBasemap === "street" && (
            <TileLayer
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a>'
              eventHandlers={{ tileerror: () => setErrors((n) => n + 1) }}
            />
          )}
          {effectiveBasemap === "schematic" && (
            <>
              <Polygon
                positions={country}
                pathOptions={{
                  fillColor: "#f1eee5",
                  fillOpacity: 0.8,
                  color: "#d9d7ca",
                  weight: 1,
                }}
              />
              <Polyline
                positions={[
                  [21.5433, 39.1728],
                  [24.7136, 46.6753],
                  [26.4207, 50.0888],
                ]}
                pathOptions={{ color: "#d5d1c4", weight: 8, opacity: 0.8 }}
              />
              <Polyline
                positions={[
                  [26.3592, 43.9818],
                  [24.7136, 46.6753],
                  [25.3646, 49.5876],
                ]}
                pathOptions={{ color: "#ded9cc", weight: 5 }}
              />
              {facilities.map((f) => (
                <Marker
                  key={f.id}
                  position={f.location}
                  interactive={false}
                  icon={L.divIcon({
                    className: "city-label",
                    html: `<span>${f.city}</span>`,
                    iconSize: [110, 20],
                    iconAnchor: [-12, -8],
                  })}
                />
              ))}
            </>
          )}
          {network &&
            facilities.map((f) => (
              <Marker
                key={f.id}
                position={f.location}
                title={f.name}
                alt={f.name}
                icon={L.divIcon({
                  className: "network-marker",
                  html: "<span>▣</span>",
                  iconSize: [28, 28],
                  iconAnchor: [14, 14],
                })}
                eventHandlers={{ click: () => onFacility?.(f.id) }}
              >
                <MapTooltip>
                  {f.name} · {f.type}
                </MapTooltip>
              </Marker>
            ))}
          {layers.expected && (
            <Polyline
              positions={c.route.expected}
              pathOptions={{
                color: "#9b94ad",
                weight: 3,
                dashArray: "7 8",
                opacity: stage === 1 ? 1 : 0.7,
              }}
            />
          )}
          {layers.actual && (
            <Polyline
              positions={c.evidence
                .filter((e) => e.confidence === "confirmed" && e.kind !== "gps")
                .map((e) => e.location)}
              pathOptions={{ color: "#8b6ccb", weight: 4, opacity: 0.85 }}
            />
          )}
          {layers.vehicle && (
            <Polyline
              positions={c.route.vehicle}
              pathOptions={{
                color: "#5a97b9",
                weight: 2,
                dashArray: "3 7",
                opacity: stage === 2 ? 1 : 0.7,
              }}
            />
          )}
          {c.evidence
            .filter((e) =>
              e.kind === "gps"
                ? layers.vehicle
                : e.kind === "facility"
                  ? layers.facilities
                  : e.kind === "delivery"
                    ? layers.attempts
                    : layers.actual,
            )
            .map((e, i) => (
              <Marker
                key={e.id}
                position={e.location}
                alt={e.label}
                title={e.label}
                icon={L.divIcon({
                  className: `evidence-marker ${e.confidence} ${selected === e.id ? "selected" : ""} ${activeEvidence.includes(e.id) ? "stage-focus" : ""}`,
                  html: `<span>${e.kind === "gps" ? "↗" : i + 1}</span>`,
                  iconSize: [28, 28],
                  iconAnchor: [14, 14],
                })}
                eventHandlers={{
                  add: (event) => {
                    (event.target as L.Marker)
                      .getElement()
                      ?.setAttribute("aria-label", e.label);
                  },
                  click: () => onSelect(e.id),
                }}
              >
                <MapTooltip direction="top">
                  <strong>{e.label}</strong>
                  <br />
                  {e.facility} · {e.time}
                  <br />
                  {e.confidence === "vehicle_only"
                    ? "Vehicle telemetry only"
                    : e.confidence === "confirmed"
                      ? "Confirmed parcel observation"
                      : "Expected / unconfirmed"}
                </MapTooltip>
              </Marker>
            ))}
          {selected && c.evidence.find((e) => e.id === selected) && (
            <CircleMarker
              center={c.evidence.find((e) => e.id === selected)!.location}
              radius={24}
              pathOptions={{ color: "#8b6ccb", weight: 2, fillOpacity: 0.08 }}
              interactive={false}
            />
          )}
        </MapContainer>
        <div className="map-tools">
          <Button
            variant="outline"
            size="icon"
            aria-label={t("Fit route", "عرض المسار بالكامل")}
            onClick={() => setFitKey((k) => k + 1)}
          >
            <LocateFixed size={16} />
          </Button>
          <Popover>
            <PopoverTrigger asChild>
              <Button
                variant="outline"
                size="icon"
                aria-label={t("Map layers", "طبقات الخريطة")}
              >
                <Layers size={16} />
              </Button>
            </PopoverTrigger>
            <PopoverContent className="layer-popover" align="end">
              <h3>{t("Map layers", "طبقات الخريطة")}</h3>
              {(Object.keys(layers) as (keyof typeof layers)[]).map((key) => (
                <label key={key} className="layer-option">
                  <Checkbox
                    checked={layers[key]}
                    onCheckedChange={(checked) =>
                      setLayers((p) => ({ ...p, [key]: checked === true }))
                    }
                  />
                  {t(
                    {
                      expected: "Expected route",
                      actual: "Confirmed observations",
                      vehicle: "Vehicle GPS",
                      facilities: "Facilities",
                      attempts: "Delivery attempts",
                    }[key],
                    {
                      expected: "المسار المتوقع",
                      actual: "الملاحظات المؤكدة",
                      vehicle: "موقع المركبة",
                      facilities: "المرافق",
                      attempts: "محاولات التسليم",
                    }[key],
                  )}
                </label>
              ))}
              <label className="basemap-label">
                {t("Base map", "الخريطة الأساسية")}
                <SelectControl
                  label="Base map"
                  value={effectiveBasemap}
                  onChange={(value) => {
                    setErrors(0);
                    setBasemap(value as "street" | "schematic");
                  }}
                  options={[
                    { value: "street", label: "OpenStreetMap" },
                    {
                      value: "schematic",
                      label: t("Offline schematic", "مخطط دون اتصال"),
                    },
                  ]}
                />
              </label>
            </PopoverContent>
          </Popover>
        </div>
        <div className="map-location-label">
          <span className="live-dot" />
          {t(
            effectiveBasemap === "schematic"
              ? "Offline schematic · evidence available"
              : "Live map · synthetic evidence",
            effectiveBasemap === "schematic"
              ? "مخطط دون اتصال · الأدلة متاحة"
              : "خريطة تفاعلية · أدلة محاكاة",
          )}
        </div>
      </div>
      <div className="viz-legend">
        <span>
          <i className="line purple" />
          {t("Confirmed custody", "حيازة مؤكدة")}
        </span>
        <span>
          <i className="line dashed" />
          {t("Expected route", "المسار المتوقع")}
        </span>
        <span>
          <i className="line blue" />
          {t("Vehicle only", "المركبة فقط")}
        </span>
      </div>
    </section>
  );
}
function ZoomButtons() {
  const map = useMap();
  return (
    <div className="map-zoom">
      <Button
        variant="ghost"
        size="icon"
        aria-label="Zoom map in"
        onClick={() => map.zoomIn()}
      >
        +
      </Button>
      <Button
        variant="ghost"
        size="icon"
        aria-label="Zoom map out"
        onClick={() => map.zoomOut()}
      >
        −
      </Button>
    </div>
  );
}
