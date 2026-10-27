import { create } from 'zustand';
import { hotels, routes, type Hotel, type HotelierQuestion, type Route } from './data/mockHotels';
import {
  answerQuestion as sendAnswer,
  getHotelierInbox,
  isApiAvailable,
  listHotels,
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

  // Actions
  toggleCompare: (hotelId: number) => void;
  setSearchQuery: (query: string) => void;
  performSearch: (query: string) => Promise<void>;
  loadHotels: () => Promise<void>;
  answerQuestion: (hotelId: number, questionId: number, answer: string) => void;
  addAgentLog: (msg: string) => void;
  clearAgentLog: () => void;
}

/**
 * Вопросы отельеру приходят отдельной ручкой `/api/hotelier/inbox`,
 * поэтому их нужно разложить по отелям: карточка и кабинет читают
 * `hotel.questions`, а не плоский список.
 */
function attachQuestions(list: Hotel[], inbox: any[]): Hotel[] {
  if (inbox.length === 0) return list;

  return list.map(hotel => {
    const questions: HotelierQuestion[] = inbox
      .filter(item => item.hotel_id === hotel.id)
      .map(item => ({
        id: item.id,
        feature_key: item.feature_key,
        question: item.question,
        status: (item.status ?? 'pending') as HotelierQuestion['status'],
        asked_at: item.asked_at ?? '',
      }));

    return questions.length > 0 ? { ...hotel, questions } : hotel;
  });
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

      // «Не виден» тоже содержит «Виден», поэтому сравниваем начало строки.
      if (q.includes('закат') && feature.key === 'sunset_view' && feature.value.trim().toLowerCase().startsWith('виден')) score += 30;
      if (q.includes('тих') && feature.key === 'noise_score' && parseInt(feature.value) < 30) score += 25;
      if ((q.includes('море') || q.includes('пляж')) && feature.key === 'walk_to_sea' && parseInt(feature.value) <= 5) score += 25;
      if (q.includes('истор') && feature.key === 'wikidata_history' && feature.value.includes('Да')) score += 20;
      if ((q.includes('семь') || q.includes('дет')) && feature.key === 'family' && feature.value.includes('Да')) score += 20;
      if ((q.includes('питом') || q.includes('кот') || q.includes('собак')) && feature.key === 'family' && feature.value.toLowerCase().includes('pet')) score += 25;
      if ((q.includes('парков') || q.includes('машин')) && feature.key === 'car_access') score += 15;
      if (q.includes('воздух') && feature.key === 'air_quality') score += 15;
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

    const loaded = await listHotels(hotels);
    if (loaded.length === 0) {
      set({ dataSource: 'demo' });
      return;
    }

    // Вопросы отельеру лежат отдельной ручкой — догружаем их, иначе кабинет
    // в API-режиме показывал бы только вопросы из демо-набора.
    const inbox = await getHotelierInbox();
    set({ hotels: attachQuestions(loaded, inbox), dataSource: 'api' });
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
    set(state => ({
      hotels: state.hotels.map(h => {
        if (h.id !== hotelId) return h;
        return {
          ...h,
          questions: h.questions.map(q => {
            if (q.id !== questionId) return q;
            return {
              ...q,
              answer_raw: answer,
              status: 'answered' as const,
              answer_parsed: { parsed_by: 'LLM', confidence: 0.92 },
            };
          }),
        };
      }),
    }));

    // Ответ уходит на бэкенд: там он разбирается и сохраняется отдельным
    // источником «hotelier». Без этого шаг демо «ответ отельера» оставался
    // только в интерфейсе.
    void sendAnswer(hotelId, questionId, answer).then(delivered => {
      if (delivered) return;
      set(state => ({
        agentLog: [
          ...state.agentLog,
          'Ответ отельера не доставлен на бэкенд: изменения видны только в интерфейсе',
        ],
      }));
    });
  },

  addAgentLog: (msg: string) => set(state => ({ agentLog: [...state.agentLog, msg] })),
  clearAgentLog: () => set({ agentLog: [] }),
}));
