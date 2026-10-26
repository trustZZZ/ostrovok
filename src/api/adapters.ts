/**
 * Приведение ответов бэкенда к модели, которую рендерит UI.
 *
 * Бэкенд отдаёт характеристики как структурированные значения
 * (например { visible: true, from_floor: 4 }), а карточки ожидают
 * человекочитаемые label/value/detail. Вся эта логика собрана здесь,
 * чтобы страницы не знали о формате хранения.
 */

import type { Hotel, HotelFeature } from '../data/mockHotels';

export interface ApiFeature {
  key: string;
  value: any;
  source: string;
  confidence: number;
  raw_evidence?: Record<string, any>;
  expires_at?: string | null;
  /** Источники дали разные значения — расхождение видно в кабинете отельера. */
  disputed?: boolean;
  /** Срок актуальности истёк: значение требует перепроверки. */
  stale?: boolean;
}

export interface ApiHotel {
  id: number;
  name: string;
  address: string | null;
  lat: number;
  lon: number;
  floors: number;
  facade_azimuth: number | null;
  features: ApiFeature[];
  explanation?: string;
  score?: number;
}

export interface ApiSearchResponse {
  hotels: ApiHotel[];
  agent_log: string[];
  intent?: Record<string, any>;
  intent_source?: string;
}

const PRESENTATION: Record<string, { label: string; icon: string }> = {
  sunset_view: { label: 'Закат', icon: '🌅' },
  noise_score: { label: 'Тишина', icon: '🤫' },
  walk_to_sea: { label: 'Пешком до моря', icon: '🚶' },
  climate_summer: { label: 'Климат летом', icon: '☀️' },
  pet_friendly: { label: 'С питомцем', icon: '🐾' },
  // Номерные характеристики: из открытых данных не выводятся,
  // значения приходят только от отельера.
  room_west_windows: { label: 'Номера на запад', icon: '🧭' },
  room_silence: { label: 'Тихие номера', icon: '🔇' },
  room_balcony: { label: 'Номер с балконом', icon: '🌤' },
};

const NO_DATA = 'нет данных';

function present(key: string): { label: string; icon: string } {
  return PRESENTATION[key] ?? { label: key, icon: '•' };
}

function formatSunset(value: any, evidence: Record<string, any>): string {
  if (!value || value.visible === undefined) return NO_DATA;
  if (!value.visible) return 'Не виден';
  const floor = value.from_floor ? ` с ${value.from_floor} этажа` : '';
  return `Виден${floor}`;
}

function formatNoise(value: any): string {
  if (!value || value.score === null || value.score === undefined) return NO_DATA;
  const level = value.level ? ` (${String(value.level).toLowerCase()})` : '';
  return `${Math.round(value.score)}/100${level}`;
}

function formatWalk(value: any): string {
  if (!value || value.minutes === null || value.minutes === undefined) return NO_DATA;
  const distance = value.distance_m ? `, ${Math.round(value.distance_m)} м` : '';
  return `${Math.round(value.minutes)} мин${distance}`;
}

function formatClimate(value: any): string {
  if (!value || value.mean_july_max_c === null || value.mean_july_max_c === undefined) {
    return NO_DATA;
  }
  const warm = value.warm_days ? `, ${value.warm_days} тёплых дней` : '';
  return `+${value.mean_july_max_c}°C в июле${warm}`;
}

function formatFlag(flag: any): string {
  if (flag === undefined || flag === null) return NO_DATA;
  return flag ? 'Да' : 'Нет';
}

function formatValue(key: string, value: any): string {
  switch (key) {
    case 'sunset_view':
      return formatSunset(value, {});
    case 'noise_score':
      return formatNoise(value);
    case 'walk_to_sea':
      return formatWalk(value);
    case 'climate_summer':
      return formatClimate(value);
    case 'pet_friendly':
      return formatFlag(value?.allowed);
    // Номерные характеристики — всегда булев факт от отельера.
    case 'room_west_windows':
      return formatFlag(value?.west_windows);
    case 'room_silence':
      return formatFlag(value?.soundproof);
    case 'room_balcony':
      return formatFlag(value?.balcony);
    default:
      if (value === null || value === undefined) return NO_DATA;
      if (typeof value === 'object') return JSON.stringify(value);
      return String(value);
  }
}

function formatDetail(feature: ApiFeature): string {
  const value = feature.value ?? {};
  const evidence = feature.raw_evidence ?? {};
  const parts: string[] = [];

  switch (feature.key) {
    case 'sunset_view': {
      if (value.visible) {
        const months = Array.isArray(value.months) && value.months.length
          ? value.months.join(', ')
          : null;
        if (months) parts.push(`Месяцы: ${months}`);
        if (value.azimuth_deg) parts.push(`азимут ${Math.round(value.azimuth_deg)}°`);
      } else if (value.reason) {
        parts.push(String(value.reason));
      }
      break;
    }
    case 'noise_score': {
      const breakdown = value.breakdown ?? {};
      const sources = Object.values(breakdown) as any[];
      const count = sources.reduce((acc, item) => acc + (item?.count ?? 0), 0);
      if (count > 0) parts.push(`Источников рядом: ${count}`);
      else if (value.score !== null) parts.push('Источников шума в радиусе нет');
      break;
    }
    case 'walk_to_sea': {
      if (value.crosses_highway) parts.push('С переходом через магистраль');
      else if (value.minutes !== null && value.minutes !== undefined) {
        parts.push('Без перехода через магистраль');
      }
      if (evidence.network) parts.push(`сеть: ${evidence.network}`);
      break;
    }
    case 'climate_summer': {
      if (evidence.period) parts.push(`по данным Open-Meteo за ${evidence.period}`);
      break;
    }
    case 'room_west_windows':
    case 'room_silence':
    case 'room_balcony': {
      if (evidence.note) parts.push(String(evidence.note));
      break;
    }
    default:
      break;
  }

  if (evidence.degraded) parts.push('данные неполные');
  // Достоверность показываем рядом со значением: гость должен видеть,
  // что данные расходятся или устарели, а не принимать их за факт.
  if (feature.disputed) parts.push('источники расходятся');
  if (feature.stale) parts.push('данные устарели, нужна перепроверка');
  parts.push(`источник: ${feature.source}`);

  return parts.join('; ');
}

/** Одна характеристика API → элемент карточки. */
export function mapFeature(feature: ApiFeature): HotelFeature {
  const { label, icon } = present(feature.key);
  return {
    key: feature.key,
    label,
    icon,
    value: formatValue(feature.key, feature.value),
    detail: formatDetail(feature),
    confidence: feature.confidence ?? 0,
    source: feature.source,
    evidence: feature.raw_evidence,
  };
}

/**
 * Ответ API → модель UI.
 *
 * Поля, которых нет в собранных данных (цена, звёзды, описание),
 * остаются пустыми: подставлять выдуманные значения нельзя, поэтому
 * UI их просто не показывает.
 */
export function mapHotel(api: ApiHotel, fallback?: Hotel): Hotel {
  const features = (api.features ?? []).map(mapFeature);
  const sunset = (api.features ?? []).find(f => f.key === 'sunset_view');

  return {
    id: api.id,
    name: api.name,
    address: api.address ?? '',
    lat: api.lat,
    lon: api.lon,
    floors: api.floors,
    facade_azimuth: api.facade_azimuth ?? 0,
    stars: fallback?.stars ?? 0,
    price_per_night: fallback?.price_per_night ?? 0,
    image: fallback?.image ?? '🏨',
    description: fallback?.description ?? '',
    features,
    questions: [],
    sunset_ray: sunset?.value?.visible
      ? { azimuth: sunset.value.azimuth_deg ?? 270, length_km: 10 }
      : undefined,
    explanation: api.explanation,
    score: api.score,
  };
}

/** Сопоставление API-отеля с демо-набором по близости координат. */
export function findFallback(hotel: ApiHotel, pool: Hotel[]): Hotel | undefined {
  const byId = pool.find(item => item.id === hotel.id);
  if (byId) return byId;
  return pool.find(
    item => Math.abs(item.lat - hotel.lat) < 0.01 && Math.abs(item.lon - hotel.lon) < 0.01,
  );
}
