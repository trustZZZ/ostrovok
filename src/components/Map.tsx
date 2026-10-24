import React, { useEffect, useRef } from "react";
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
// Vite: подключаем worker MapLibre как URL, иначе в production-сборке
// карта не рендерится ("Worker failed to load")
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker?url";
import type { Hotel } from "../data/mockHotels";

maplibregl.setWorkerUrl(maplibreWorkerUrl);

interface MapProps {
  hotels: Hotel[];
  showSunsetRays?: boolean;
  selectedHotelId?: number | null;
  onHotelClick?: (hotelId: number) => void;
  center?: [number, number];
  zoom?: number;
}

export const Map: React.FC<MapProps> = ({
  hotels,
  showSunsetRays = true,
  selectedHotelId,
  onHotelClick,
  center = [20.5, 54.9],
  zoom = 9,
}) => {
  const mapContainer = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);

  useEffect(() => {
    if (!mapContainer.current) return;

    map.current = new maplibregl.Map({
      container: mapContainer.current,
      style: {
        version: 8,
        sources: {
          "osm-tiles": {
            type: "raster",
            tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
            tileSize: 256,
            attribution: "© OpenStreetMap contributors",
          },
        },
        layers: [
          {
            id: "osm-tiles",
            type: "raster",
            source: "osm-tiles",
            minzoom: 0,
            maxzoom: 19,
          },
        ],
      },
      center,
      zoom,
    });

    map.current.addControl(new maplibregl.NavigationControl(), "top-right");

    return () => {
      map.current?.remove();
    };
  }, []);

  useEffect(() => {
    if (!map.current) return;
    const m = map.current;

    // Wait for map to load before adding sources/layers
    const addLayers = () => {
      // Hotel points
      if (!m.getSource("hotels")) {
        m.addSource("hotels", {
          type: "geojson",
          data: {
            type: "FeatureCollection",
            features: hotels.map((h) => ({
              type: "Feature",
              geometry: { type: "Point", coordinates: [h.lon, h.lat] },
              properties: { id: h.id, name: h.name, icon: h.image },
            })),
          },
        });

        m.addLayer({
          id: "hotels-circle",
          type: "circle",
          source: "hotels",
          paint: {
            "circle-radius": [
              "case",
              ["boolean", ["==", ["get", "id"], selectedHotelId ?? -1]],
              12,
              8,
            ],
            "circle-color": [
              "case",
              ["boolean", ["==", ["get", "id"], selectedHotelId ?? -1]],
              "#f97316",
              "#0ea5e9",
            ],
            "circle-stroke-width": 2,
            "circle-stroke-color": "#ffffff",
          },
        });

        // Sunset rays
        if (showSunsetRays) {
          const rayFeatures: any[] = hotels
            .filter((h) => h.sunset_ray)
            .map((h) => {
              const azRad = ((h.sunset_ray!.azimuth - 90) * Math.PI) / 180;
              const lat = h.lat;
              const lon = h.lon;
              const dist = h.sunset_ray!.length_km * 1000;
              const dLat = (dist * Math.cos(azRad)) / 111000;
              const dLon =
                (dist * Math.sin(azRad)) /
                (111000 * Math.cos((lat * Math.PI) / 180));
              return {
                type: "Feature" as const,
                geometry: {
                  type: "LineString" as const,
                  coordinates: [
                    [lon, lat],
                    [lon + dLon, lat + dLat],
                  ],
                },
                properties: {
                  hotel_id: h.id,
                  visible:
                    h.features
                      .find((f) => f.key === "sunset_view")
                      ?.value.includes("Виден") ?? false,
                },
              };
            });

          m.addSource("sunset-rays", {
            type: "geojson",
            data: { type: "FeatureCollection", features: rayFeatures },
          });

          m.addLayer({
            id: "sunset-rays-line",
            type: "line",
            source: "sunset-rays",
            paint: {
              "line-color": ["case", ["get", "visible"], "#f97316", "#94a3b8"],
              "line-width": 2.5,
              "line-dasharray": [3, 2],
              "line-opacity": 0.8,
            },
          });
        }

        // Click handler
        m.on("click", "hotels-circle", (e: any) => {
          if (e.features && e.features.length > 0) {
            const hotelId = e.features[0].properties?.id;
            if (hotelId && onHotelClick) {
              onHotelClick(hotelId);
            }
          }
        });

        m.on("mouseenter", "hotels-circle", () => {
          m.getCanvas().style.cursor = "pointer";
        });
        m.on("mouseleave", "hotels-circle", () => {
          m.getCanvas().style.cursor = "";
        });
      }
    };

    if (m.isStyleLoaded()) {
      addLayers();
    } else {
      m.on("load", addLayers);
    }
  }, [hotels, selectedHotelId, showSunsetRays, onHotelClick]);

  return (
    <div
      ref={mapContainer}
      className="w-full h-full rounded-xl overflow-hidden"
    />
  );
};
