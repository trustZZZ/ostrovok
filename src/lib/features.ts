/**
 * Чтение характеристик отеля для UI.
 *
 * Значение характеристики — человекочитаемая строка (её формирует
 * `src/api/adapters.ts`), поэтому проверки «виден ли закат», «сколько минут
 * до пляжа» собраны здесь, а не размазаны по страницам. Сравнение строк
 * вида `value.includes('Виден')` давало ложное срабатывание на «Не виден».
 */

import type { Hotel, HotelFeature } from '../data/mockHotels';

export function findFeature(hotel: Hotel, key: string): HotelFeature | undefined {
  return hotel.features.find(feature => feature.key === key);
}

/** Виден ли закат над морем с какого-либо этажа. */
export function isSunsetVisible(hotel: Hotel): boolean {
  const sunset = findFeature(hotel, 'sunset_view');
  if (!sunset) return false;
  return sunset.value.trim().toLowerCase().startsWith('виден');
}

/** Балл шума 0..100, либо null, если значения нет. */
export function noiseScore(hotel: Hotel): number | null {
  const noise = findFeature(hotel, 'noise_score');
  if (!noise) return null;
  const match = noise.value.match(/(\d+)\s*\/\s*100/);
  return match ? Number(match[1]) : null;
}

/** Пешее время до пляжа в минутах, либо null. */
export function walkMinutes(hotel: Hotel): number | null {
  const walk = findFeature(hotel, 'walk_to_sea');
  if (!walk) return null;
  const match = walk.value.match(/(\d+)\s*мин/);
  return match ? Number(match[1]) : null;
}

/** Правило характеристики из реестра (`GET /api/features`). */
export interface FeatureSpec {
  key: string;
  title: string;
  value_type?: string;
  /** Поле структурированного значения, по которому идёт сравнение. */
  value_field?: string;
  search?: { op?: string; hint?: string };
}

export type BetterDirection = 'higher' | 'lower';

/**
 * Направление сравнения. `search.op` описывает пожелание пользователя, но
 * именно оно задаёт порядок: «<=» — меньше лучше (шум, минуты), «>=» —
 * больше лучше, «==» — наличие лучше отсутствия.
 */
export function betterDirection(feature: HotelFeature, spec?: FeatureSpec): BetterDirection {
  const op = spec?.search?.op;
  if (op === '<=') return 'lower';
  if (op === '>=' || op === '==') return 'higher';
  // Реестр недоступен (демо-набор) — опираемся на смысл характеристики.
  return feature.key === 'noise_score' || feature.key === 'walk_to_sea' ? 'lower' : 'higher';
}

/**
 * Число для сравнения. Поле берётся из реестра, флаг превращается в 1/0.
 * null — сравнивать нечего. Произвольные числа из текста не выдёргиваем:
 * «Да, 1912 год» не должно обгонять характеристику с реальным баллом.
 */
export function comparableValue(feature: HotelFeature, spec?: FeatureSpec): number | null {
  const raw = feature.raw;
  const field = spec?.value_field;

  if (raw !== null && raw !== undefined && field) {
    const value = typeof raw === 'object' ? (raw as Record<string, unknown>)[field] : raw;
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    if (typeof value === 'boolean') return value ? 1 : 0;
  }

  switch (feature.key) {
    case 'sunset_view':
      return feature.value.trim().toLowerCase().startsWith('виден') ? 1 : 0;
    case 'noise_score': {
      const score = feature.value.match(/(\d+)\s*\/\s*100/);
      return score ? Number(score[1]) : null;
    }
    case 'walk_to_sea': {
      const minutes = feature.value.match(/(\d+)\s*мин/);
      return minutes ? Number(minutes[1]) : null;
    }
    case 'climate_summer': {
      const degrees = feature.value.match(/(\d+)\s*°C/);
      return degrees ? Number(degrees[1]) : null;
    }
    default:
      return null;
  }
}
