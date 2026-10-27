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
  // Партнёрский слой: место рядом с отелем, подтверждённое обзорами.
  sunset_spot_nearby: { label: 'Закат рядом', icon: '🌇' },
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
  if (value.visible) {
    const floor = value.from_floor ? ` с ${value.from_floor} этажа` : '';
    return `Виден${floor}`;
  }
  // Причина отказа меняет совет гостю: другой номер или этаж повыше.
  if (evidence.block_reason === 'facade_facing_away') return 'Окна не на запад';
  if (evidence.block_reason === 'obstructed') return 'Загорожен';
  return 'Не виден';
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

function formatSunsetSpot(value: any): string {
  if (!value || value.score === undefined || value.score === null) return NO_DATA;
  const minutes = value.nearest_minutes;
  if (typeof minutes !== 'number') return 'Есть рядом';
  return `${Math.round(minutes)} мин пешком`;
}

/** Обрезка цитаты обзора: в карточке нужен смысл, а не весь абзац. */
function shorten(text: string, limit = 90): string {
  return text.length <= limit ? text : `${text.slice(0, limit).trimEnd()}…`;
}

function formatFlag(flag: any): string {
  if (flag === undefined || flag === null) return NO_DATA;
  return flag ? 'Да' : 'Нет';
}

function formatValue(key: string, value: any, evidence: Record<string, any> = {}): string {
  switch (key) {
    case 'sunset_view':
      return formatSunset(value, evidence);
    case 'noise_score':
      return formatNoise(value);
    case 'walk_to_sea':
      return formatWalk(value);
    case 'climate_summer':
      return formatClimate(value);
    case 'sunset_spot_nearby':
      return formatSunsetSpot(value);
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
        // «Виден» означает «виден из части номеров»: считаем по стенам
        // контура здания из OSM, а не по входу с улицы.
        const walls = Array.isArray(evidence.facade_walls) ? evidence.facade_walls.length : 0;
        if (walls) {
          parts.push(`стены здания: ${walls}`);
          if (typeof value.west_share === 'number') {
            parts.push(`на закат смотрит ${Math.round(value.west_share * 100)}% фасада`);
          }
        }
      } else if (value.reason) {
        parts.push(String(value.reason));
      } else if (evidence.block_reason === 'facade_facing_away') {
        parts.push('Ни одна стена не смотрит на запад');
      } else if (evidence.block_reason === 'obstructed') {
        parts.push('Вид закрыт застройкой на западе');
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
    case 'sunset_spot_nearby': {
      if (value.place_name) parts.push(`Место: ${value.place_name}`);
      if (typeof value.reviews === 'number') parts.push(`подтверждений: ${value.reviews}`);
      if (typeof value.distance_m === 'number') {
        parts.push(`${Math.round(value.distance_m)} м по маршруту`);
      }
      const months = Array.isArray(value.best_months) ? value.best_months : [];
      if (months.length > 0 && months.length < 12) parts.push(`месяцы: ${months.join(', ')}`);
      // Атрибуция обязательна: обзор — чужая публикация, а не наш вывод.
      const reviews = Array.isArray(evidence.reviews) ? evidence.reviews : [];
      const first = reviews[0];
      if (first?.author) parts.push(`обзор: ${first.author}`);
      if (first?.quote) parts.push(`«${shorten(String(first.quote))}»`);
      if (first?.url) parts.push(String(first.url));
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
    value: formatValue(feature.key, feature.value, feature.raw_evidence ?? {}),
    detail: formatDetail(feature),
    confidence: feature.confidence ?? 0,
    source: feature.source,
    // Достоверность — часть значения, а не украшение карточки: по этим
    // флагам интерфейс показывает «устарело» и «источники расходятся».
    stale: feature.stale === true,
    disputed: feature.disputed === true,
    // Исходное значение хранится рядом с готовой строкой: сравнение отелей
    // читает поля по реестру характеристик, а не текст для человека.
    raw: feature.value,
    evidence: feature.raw_evidence,
  };
}

/**
 * Ответ API → модель UI.
 *
 * Цена, звёзды и эмодзи — витринные атрибуты демо-набора, их в собранных
 * данных нет, и на достоверность характеристик они не влияют.
 * А вот описание из мок-набора не подставляем: это выдуманный текст, который
 * утверждает факты и конкурирует с расчётом. У «Принцессы Элизы» описание
 * гласило «Фасад обращён на запад», хотя `sunset_view` для неё даёт
 * `facade_facing_away` (азимут фасада 170°) — на карточке получалось прямое
 * противоречие.
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
    description: '',
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
