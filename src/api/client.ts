/**
 * Клиент бэкенда.
 *
 * Работает с реальными собранными характеристиками. Если API недоступен
 * (статическая сборка без бэкенда), клиент сообщает об этом, и стор
 * переходит на демонстрационный набор — интерфейс не ломается.
 */

import type { Hotel } from '../data/mockHotels';
import type { FeatureSpec } from '../lib/features';
import {
  findFallback,
  mapHotel,
  type ApiHotel,
  type ApiSearchResponse,
} from './adapters';

const API_BASE = (import.meta as any).env?.VITE_API_URL || '/api';
const HEALTH_URL = (import.meta as any).env?.VITE_HEALTH_URL || '/health';

export interface SearchResponse {
  hotels: Hotel[];
  agent_log: string[];
  intent?: Record<string, any>;
  intent_source?: string;
  /** true, если ответ собран локально из демо-набора. */
  offline: boolean;
}

let apiAvailable: boolean | null = null;

async function fetchWithTimeout(url: string, init: RequestInit = {}, ms = 20000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), ms);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Проверка доступности бэкенда.
 *
 * Успех кэшируется, отказ — нет: на холодном старте бэкенд может ещё
 * подниматься, а закэшированный на всю сессию отказ оставлял интерфейс
 * на выдуманном демо-наборе. Поэтому одна повторная попытка с паузой.
 */
export async function isApiAvailable(): Promise<boolean> {
  if (apiAvailable === true) return true;

  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      const res = await fetchWithTimeout(HEALTH_URL, {}, 2500);
      if (res.ok) {
        apiAvailable = true;
        return true;
      }
    } catch {
      // Сеть могла отвалиться на время старта — пробуем ещё раз ниже.
    }
    if (attempt === 0) {
      await new Promise(resolve => setTimeout(resolve, 400));
    }
  }

  apiAvailable = false;
  return false;
}

export function isOfflineMode(): boolean {
  return apiAvailable === false;
}

export async function checkHealth(): Promise<Record<string, any> | null> {
  try {
    const res = await fetchWithTimeout(HEALTH_URL, {}, 2500);
    return res.ok ? await res.json() : null;
  } catch {
    return null;
  }
}

/**
 * Поиск по собранным характеристикам.
 * Возвращает пустой список, если бэкенд недоступен — решение об откате
 * на демо-набор принимает стор.
 */
export async function searchHotels(query: string, pool: Hotel[] = []): Promise<SearchResponse> {
  if (!(await isApiAvailable())) {
    return { hotels: [], agent_log: [], offline: true };
  }

  try {
    const res = await fetchWithTimeout(`${API_BASE}/search`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query }),
    });
    if (!res.ok) throw new Error(`search: HTTP ${res.status}`);

    const data: ApiSearchResponse = await res.json();
    return {
      hotels: (data.hotels ?? []).map(hotel =>
        mapHotel(hotel, findFallback(hotel, pool)),
      ),
      agent_log: data.agent_log ?? [],
      intent: data.intent,
      intent_source: data.intent_source,
      offline: false,
    };
  } catch (error) {
    console.warn('Поиск через API не удался, использую демо-набор', error);
    return { hotels: [], agent_log: [], offline: true };
  }
}

/** Полный список отелей с характеристиками из БД. */
export async function listHotels(pool: Hotel[] = []): Promise<Hotel[]> {
  if (!(await isApiAvailable())) return [];
  try {
    const res = await fetchWithTimeout(`${API_BASE}/hotels`);
    if (!res.ok) throw new Error(`hotels: HTTP ${res.status}`);
    const data: ApiHotel[] = await res.json();
    return data.map(hotel => mapHotel(hotel, findFallback(hotel, pool)));
  } catch (error) {
    console.warn('Список отелей недоступен', error);
    return [];
  }
}

/** Запуск сбора характеристик по одному отелю. */
export async function enrichHotel(hotelId: number): Promise<{ thread_id: string } | null> {
  if (!(await isApiAvailable())) return null;
  try {
    const res = await fetchWithTimeout(`${API_BASE}/hotels/${hotelId}/enrich`, { method: 'POST' });
    return res.ok ? await res.json() : null;
  } catch {
    return null;
  }
}

/**
 * Инбокс вопросов отельерам.
 *
 * `all` — очередь и история ответов: без истории кабинет не может показать,
 * что именно отельер ответил и какое значение из ответа записалось.
 */
export async function getHotelierInbox(
  status: 'pending' | 'answered' | 'all' = 'all',
): Promise<any[]> {
  if (!(await isApiAvailable())) return [];
  try {
    const res = await fetchWithTimeout(`${API_BASE}/hotelier/inbox?status=${status}`);
    return res.ok ? await res.json() : [];
  } catch {
    return [];
  }
}

/** Ответ отельера на вопрос агента. */
export async function answerQuestion(
  hotelId: number,
  questionId: number,
  answer: string,
): Promise<boolean> {
  if (!(await isApiAvailable())) return false;
  try {
    const res = await fetchWithTimeout(`${API_BASE}/hotelier/${hotelId}/answer/${questionId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ answer }),
    });
    return res.ok;
  } catch {
    return false;
  }
}

/** Витрина маршрутов от блогеров. */
export async function getRoutes(): Promise<any[]> {
  if (!(await isApiAvailable())) return [];
  try {
    const res = await fetchWithTimeout(`${API_BASE}/routes`);
    return res.ok ? await res.json() : [];
  } catch {
    return [];
  }
}

/** Реестр характеристик: какие источники и инструменты система знает. */
export async function getFeatureRegistry(): Promise<FeatureSpec[]> {
  if (!(await isApiAvailable())) return [];
  try {
    const res = await fetchWithTimeout(`${API_BASE}/features`);
    if (!res.ok) return [];
    return (await res.json()) as FeatureSpec[];
  } catch {
    return [];
  }
}

// --- Достоверность: противоречия источников и актуализация ---------------

/** Вариант значения от одного источника. */
export interface ConflictVariant {
  source: string;
  confidence: number;
  value: unknown;
}

/** Противоречие: что говорят источники и что система выбрала. */
export interface ApiConflict {
  hotel_id: number;
  feature: string;
  title: string;
  /** Кому верим при расхождении: `geo` или `hotelier`. */
  authoritative: string | null;
  variants: ConflictVariant[];
  resolved: { source: string | null; value: unknown };
}

/** Характеристика с истёкшим сроком актуальности. */
export interface ApiStaleFeature {
  hotel_id: number;
  hotel_name: string;
  key: string;
  source: string;
  confidence: number;
  computed_at: string | null;
  expires_at: string | null;
  days_overdue: number | null;
}

export interface RefreshResponse {
  thread_id: string;
  status: string;
  /** Характеристики, из-за которых запущена перепроверка. */
  stale_features: string[];
  message: string;
}

export interface ResolveResponse {
  status: string;
  feature: string;
  /** Расхождение осталось: отельер считает иначе, чем геоданные. */
  still_disputed: boolean;
  rows: { source: string; value: unknown; confidence: number; disputed: boolean }[];
}

/** Противоречия источников — вход для разбора в кабинете отельера. */
export async function getConflicts(): Promise<ApiConflict[]> {
  if (!(await isApiAvailable())) return [];
  try {
    const res = await fetchWithTimeout(`${API_BASE}/conflicts`);
    if (!res.ok) throw new Error(`conflicts: HTTP ${res.status}`);
    return (await res.json()) as ApiConflict[];
  } catch (error) {
    console.warn('Противоречия недоступны', error);
    return [];
  }
}

/** Очередь перепроверки: характеристики, у которых истёк срок. */
export async function getStaleFeatures(limit = 50): Promise<ApiStaleFeature[]> {
  if (!(await isApiAvailable())) return [];
  try {
    const res = await fetchWithTimeout(`${API_BASE}/hotels/stale?limit=${limit}`);
    if (!res.ok) throw new Error(`hotels/stale: HTTP ${res.status}`);
    return (await res.json()) as ApiStaleFeature[];
  } catch (error) {
    console.warn('Список устаревших данных недоступен', error);
    return [];
  }
}

/** Перепроверка отеля: агент пересобирает характеристики в фоне. */
export async function requestHotelRefresh(hotelId: number): Promise<RefreshResponse | null> {
  if (!(await isApiAvailable())) return null;
  try {
    const res = await fetchWithTimeout(`${API_BASE}/hotels/${hotelId}/refresh`, { method: 'POST' });
    return res.ok ? ((await res.json()) as RefreshResponse) : null;
  } catch {
    return null;
  }
}

/** Отельер подтверждает или исправляет значение — противоречие пересчитывается. */
export async function resolveFeature(
  hotelId: number,
  featureKey: string,
  value: string | boolean | number,
  note?: string,
): Promise<ResolveResponse | null> {
  if (!(await isApiAvailable())) return null;
  try {
    const res = await fetchWithTimeout(
      `${API_BASE}/hotelier/${hotelId}/resolve/${featureKey}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value, note }),
      },
    );
    return res.ok ? ((await res.json()) as ResolveResponse) : null;
  } catch {
    return null;
  }
}
