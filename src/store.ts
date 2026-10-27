import { create } from 'zustand';
import { hotels, routes, type Hotel, type HotelierQuestion, type Route } from './data/mockHotels';
import type { FeatureSpec } from './lib/features';
import {
  answerQuestion as sendAnswer,
  getFeatureRegistry,
  getHotelierInbox,
  isApiAvailable,
  listHotels,
  requestHotelRefresh,
  searchHotels,
} from './api/client';

type DataSource = 'unknown' | 'api' | 'demo';

interface AppState {
  hotels: Hotel[];
  routes: Route[];
  selectedHotelIds: number[];
  searchQuery: string;
  searchResults: Hotel[];
  agentLog: string[];
  /** Откуда пришли данные: из API или из демо-набора. */
  dataSource: DataSource;
  /** Распознанные из запроса ограничения (для подсказки в UI). */
  searchIntent: Record<string, any> | null;
  isSearching: boolean;
  /** Правила сравнения характеристик из реестра (`/api/features`). */
  featureRegistry: FeatureSpec[];

  // Actions
  toggleCompare: (hotelId: number) => void;
  setSearchQuery: (query: string) => void;
  performSearch: (query: string) => Promise<void>;
  loadHotels: () => Promise<void>;
  /** Перечитывает отели, вопросы и значения после ответа или перепроверки. */
  reloadHotels: () => Promise<void>;
  /** Запускает перепроверку отеля, возвращает устаревшие характеристики. */
  refreshHotel: (hotelId: number) => Promise<string[]>;
  answerQuestion: (hotelId: number, questionId: number, answer: string) => void;
  addAgentLog: (msg: string) => void;
  clearAgentLog: () => void;
}

/**
 * Вопросы отельеру приходят отдельной ручкой `/api/hotelier/inbox`,
 * поэтому их нужно разложить по отелям: карточка и кабинет читают
 * `hotel.questions`, а не плоский список.
 *
 * Список заменяется целиком, включая пустой: инбокс отдаёт и историю
 * ответов, поэтому «вопросов больше нет» — это факт из БД, а не повод
 * оставить на экране строки из прошлого ответа.
 */
function attachQuestions(list: Hotel[], inbox: any[]): Hotel[] {
  return list.map(hotel => {
    const questions: HotelierQuestion[] = inbox
      .filter(item => item.hotel_id === hotel.id)
      .map(item => ({
        id: item.id,
        feature_key: item.feature_key,
        question: item.question,
        status: (item.status ?? 'pending') as HotelierQuestion['status'],
        asked_at: item.asked_at ?? '',
        answer_raw: item.answer_raw ?? undefined,
        answer_parsed: item.answer_parsed ?? undefined,
        answered_at: item.answered_at ?? undefined,
        // Уверенность и значение приходят из записанной характеристики
        // (source=hotelier). Клиент их не вычисляет и не подставляет.
        confidence: typeof item.confidence === 'number' ? item.confidence : undefined,
        value: item.value ?? undefined,
      }));

    return { ...hotel, questions };
  });
}

/** Отели, вопросы и реестр одним заходом: один снимок состояния из трёх ручек. */
async function fetchHotelsFromApi(): Promise<{ hotels: Hotel[]; registry: FeatureSpec[] } | null> {
  const loaded = await listHotels(hotels);
  if (loaded.length === 0) return null;

  const [inbox, registry] = await Promise.all([getHotelierInbox('all'), getFeatureRegistry()]);
  return { hotels: attachQuestions(loaded, inbox), registry };
}

/**
 * Локальный скоринг по демо-набору.
 * Используется только когда бэкенд недоступен: интерфейс остаётся
 * работоспособным, но результат помечается как демонстрационный.
 */
function scoreDemoHotels(query: string): Hotel[] {
  const q = query.toLowerCase();

  const scored = hotels.map(hotel => {
    let score = 0;

    for (const feature of hotel.features) {
      const text = `${feature.label} ${feature.value} ${feature.detail}`.toLowerCase();

      // Ветки — только по ключам реестра (`backend/app/features.yaml`).
      // Условия по `wikidata_history`, `car_access`, `air_quality`, `family`
      // не срабатывали никогда: таких характеристик нет ни в реестре, ни в
      // демо-наборе, поэтому подбор молча терял часть пожелания.
      // «Не виден» тоже содержит «Виден», поэтому сравниваем начало строки.
      if (q.includes('закат') && feature.key === 'sunset_view' && feature.value.trim().toLowerCase().startsWith('виден')) score += 30;
      if (q.includes('тих') && feature.key === 'noise_score' && parseInt(feature.value) < 30) score += 25;
      if ((q.includes('море') || q.includes('пляж')) && feature.key === 'walk_to_sea' && parseInt(feature.value) <= 5) score += 25;
      if ((q.includes('питом') || q.includes('кот') || q.includes('собак') || q.includes('животн')) && feature.key === 'pet_friendly' && feature.value.trim().toLowerCase().startsWith('да')) score += 25;
      if ((q.includes('запад') || q.includes('окн')) && feature.key === 'room_west_windows' && feature.value.trim().toLowerCase().startsWith('да')) score += 20;
      if ((q.includes('балкон') || q.includes('терас')) && feature.key === 'room_balcony' && feature.value.trim().toLowerCase().startsWith('да')) score += 20;
      if (q.includes('тих') && feature.key === 'room_silence' && feature.value.trim().toLowerCase().startsWith('да')) score += 15;
      if (text.includes(q) && q.length > 2) score += 5;
    }

    if (hotel.name.toLowerCase().includes(q) || hotel.address.toLowerCase().includes(q)) score += 10;

    return { hotel, score };
  });

  const results = scored
    .filter(item => item.score > 0)
    .sort((a, b) => b.score - a.score)
    .map(item => item.hotel);

  return results.length > 0 ? results : hotels;
}

export const useStore = create<AppState>((set, get) => ({
  hotels,
  routes,
  selectedHotelIds: [],
  searchQuery: '',
  searchResults: [],
  agentLog: [],
  dataSource: 'unknown',
  searchIntent: null,
  isSearching: false,
  featureRegistry: [],

  toggleCompare: (hotelId: number) => {
    const current = get().selectedHotelIds;
    if (current.includes(hotelId)) {
      set({ selectedHotelIds: current.filter(id => id !== hotelId) });
    } else if (current.length < 3) {
      set({ selectedHotelIds: [...current, hotelId] });
    }
  },

  setSearchQuery: (query: string) => set({ searchQuery: query }),

  /**
   * Подтягивает отели с собранными характеристиками из БД.
   * Если API недоступен — остаётся демо-набор.
   */
  loadHotels: async () => {
    const online = await isApiAvailable();
    if (!online) {
      set({ dataSource: 'demo' });
      return;
    }

    const data = await fetchHotelsFromApi();
    if (data === null) {
      set({ dataSource: 'demo' });
      return;
    }

    set({ hotels: data.hotels, featureRegistry: data.registry, dataSource: 'api' });
  },

  /**
   * Повторное чтение после записи (ответ отельера, перепроверка).
   * В отличие от loadHotels не переводит интерфейс в демо-режим: если ручка
   * моргнула, показываем прежние данные, а не подменяем их выдуманными.
   */
  reloadHotels: async () => {
    const data = await fetchHotelsFromApi();
    if (data === null) return;
    set({ hotels: data.hotels, featureRegistry: data.registry, dataSource: 'api' });
  },

  refreshHotel: async (hotelId: number) => {
    const started = await requestHotelRefresh(hotelId);
    if (started === null) {
      set(state => ({
        agentLog: [...state.agentLog, 'Перепроверка недоступна: бэкенд не отвечает'],
      }));
      return [];
    }
    set(state => ({ agentLog: [...state.agentLog, started.message] }));
    return started.stale_features;
  },

  performSearch: async (query: string) => {
    set({ searchQuery: query, isSearching: true });

    const response = await searchHotels(query, hotels);

    if (!response.offline && response.hotels.length > 0) {
      set({
        searchResults: response.hotels,
        agentLog: response.agent_log,
        searchIntent: response.intent ?? null,
        dataSource: 'api',
        isSearching: false,
      });
      return;
    }

    // Бэкенд недоступен — показываем демонстрационный результат.
    set({
      searchResults: scoreDemoHotels(query),
      agentLog: ['Бэкенд недоступен: показан демонстрационный набор'],
      searchIntent: null,
      dataSource: 'demo',
      isSearching: false,
    });
  },

  answerQuestion: (hotelId: number, questionId: number, answer: string) => {
    // Оптимистично фиксируем только текст ответа. Разбор, уверенность и
    // значение записывает бэкенд: подставлять их на клиенте нельзя, иначе
    // карточка показывала бы confidence, которого нет в базе.
    set(state => ({
      hotels: state.hotels.map(h => {
        if (h.id !== hotelId) return h;
        return {
          ...h,
          questions: h.questions.map(q => {
            if (q.id !== questionId) return q;
            return { ...q, answer_raw: answer, status: 'answered' as const };
          }),
        };
      }),
    }));

    // Ответ уходит на бэкенд: там он разбирается и сохраняется отдельным
    // источником «hotelier». Без этого шаг демо «ответ отельера» оставался
    // только в интерфейсе.
    void sendAnswer(hotelId, questionId, answer).then(delivered => {
      if (!delivered) {
        set(state => ({
          agentLog: [
            ...state.agentLog,
            'Ответ отельера не доставлен на бэкенд: изменения видны только в интерфейсе',
          ],
        }));
        return;
      }
      // Что именно записалось — читаем из БД, а не из ответа на запрос:
      // показанное значение и значение в поиске должны совпадать.
      void get().reloadHotels();
    });
  },

  addAgentLog: (msg: string) => set(state => ({ agentLog: [...state.agentLog, msg] })),
  clearAgentLog: () => set({ agentLog: [] }),
}));
