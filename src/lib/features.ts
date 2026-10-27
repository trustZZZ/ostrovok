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
