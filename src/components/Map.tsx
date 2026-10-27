import React, { useEffect, useRef } from "react";
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
// Vite: подключаем worker MapLibre как URL, иначе в production-сборке
// карта не рендерится ("Worker failed to load")
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker?url";
import type { Hotel } from "../data/mockHotels";
import { isSunsetVisible } from "../lib/features";

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

    const hotelFeatures: any[] = hotels.map((h) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [h.lon, h.lat] },
      properties: {
        id: h.id,
        name: h.name,
        icon: h.image,
        selected: h.id === selectedHotelId,
      },
    }));

    const rayFeatures: any[] = showSunsetRays
      ? hotels
          .filter((h) => h.sunset_ray)
          .map((h) => {
            const ray = h.sunset_ray!;
            // Азимут отсчитывается от севера по часовой стрелке, поэтому
            // северная составляющая идёт через cos, восточная — через sin.
            const azRad = (ray.azimuth * Math.PI) / 180;
            const dist = ray.length_km * 1000;
            const dLat = (dist * Math.cos(azRad)) / 111000;
            const dLon =
              (dist * Math.sin(azRad)) /
              (111000 * Math.cos((h.lat * Math.PI) / 180));
            return {
              type: "Feature" as const,
              geometry: {
                type: "LineString" as const,
                coordinates: [
                  [h.lon, h.lat],
                  [h.lon + dLon, h.lat + dLat],
                ],
              },
              properties: {
                hotel_id: h.id,
                visible: isSunsetVisible(h),
              },
            };
          })
      : [];

    const addLayers = () => {
      m.addSource("hotels", {
        type: "geojson",
        data: { type: "FeatureCollection", features: hotelFeatures },
      });

      m.addLayer({
        id: "hotels-circle",
        type: "circle",
        source: "hotels",
        paint: {
          "circle-radius": ["case", ["boolean", ["get", "selected"]], 13, 8],
          "circle-color": [
            "case",
            ["boolean", ["get", "selected"]],
            "#f97316",
            "#0ea5e9",
          ],
          "circle-stroke-width": 2,
          "circle-stroke-color": "#ffffff",
        },
      });

      if (showSunsetRays) {
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
    };

    // Новый поиск меняет набор отелей: слои не пересоздаём, а обновляем
    // данные источника, иначе на карте остаются точки прошлого запроса.
    const updateData = () => {
      const hotelSource = m.getSource("hotels") as
        | maplibregl.GeoJSONSource
        | undefined;
      hotelSource?.setData({ type: "FeatureCollection", features: hotelFeatures });

      const raySource = m.getSource("sunset-rays") as
        | maplibregl.GeoJSONSource
        | undefined;
      raySource?.setData({ type: "FeatureCollection", features: rayFeatures });
    };

    const onLoad = () => {
      if (!m.getSource("hotels")) {
        addLayers();
      } else {
        updateData();
      }
    };

    if (m.isStyleLoaded()) {
      onLoad();
    } else {
      m.on("load", onLoad);
      return () => {
        m.off("load", onLoad);
      };
    }
  }, [hotels, selectedHotelId, showSunsetRays, onHotelClick]);

  return (
    <div
      ref={mapContainer}
      className="w-full h-full rounded-xl overflow-hidden"
    />
  );
};
