import { create } from 'zustand';
import { hotels, routes, type Hotel, type Route, type HotelierQuestion } from './data/mockHotels';

interface AppState {
  hotels: Hotel[];
  routes: Route[];
  selectedHotelIds: number[];
  searchQuery: string;
  searchResults: Hotel[];
  agentLog: string[];
  
  // Actions
  toggleCompare: (hotelId: number) => void;
  setSearchQuery: (query: string) => void;
  performSearch: (query: string) => void;
  answerQuestion: (hotelId: number, questionId: number, answer: string) => void;
  addAgentLog: (msg: string) => void;
  clearAgentLog: () => void;
}

export const useStore = create<AppState>((set, get) => ({
  hotels,
  routes,
  selectedHotelIds: [],
  searchQuery: '',
  searchResults: [],
  agentLog: [],

  toggleCompare: (hotelId: number) => {
    const current = get().selectedHotelIds;
    if (current.includes(hotelId)) {
      set({ selectedHotelIds: current.filter(id => id !== hotelId) });
    } else if (current.length < 3) {
      set({ selectedHotelIds: [...current, hotelId] });
    }
  },

  setSearchQuery: (query: string) => set({ searchQuery: query }),

  performSearch: (query: string) => {
    set({ searchQuery: query });
    const q = query.toLowerCase();
    
    // Simple NLP-like search based on feature keywords
    const scored = hotels.map(hotel => {
      let score = 0;
      const features = hotel.features;
      
      // Check each feature
      for (const f of features) {
        const text = `${f.label} ${f.value} ${f.detail}`.toLowerCase();
        
        if (q.includes('закат') && f.key === 'sunset_view' && f.value.includes('Виден')) score += 30;
        if (q.includes('тих') && f.key === 'noise_score' && parseInt(f.value) < 30) score += 25;
        if ((q.includes('море') || q.includes('пляж')) && f.key === 'walk_to_sea' && parseInt(f.value) <= 5) score += 25;
        if (q.includes('истор') && f.key === 'wikidata_history' && f.value.includes('Да')) score += 20;
        if ((q.includes('семь') || q.includes('дет')) && f.key === 'family' && f.value.includes('Да')) score += 20;
        if ((q.includes('питом') || q.includes('кот') || q.includes('собак')) && f.key === 'family' && f.value.toLowerCase().includes('pet')) score += 25;
        if ((q.includes('парков') || q.includes('машин')) && f.key === 'car_access') score += 15;
        if ((q.includes('ноч') || q.includes('бар') || q.includes('ресторан')) && f.key === 'night_amenities') score += 15;
        if ((q.includes('воздух') || q.includes('эколог')) && f.key === 'air_quality') score += 15;
        if ((q.includes('спа') || q.includes('релакс')) && f.key === 'night_amenities') score += 10;
      }
      
      // Name/address matching
      if (hotel.name.toLowerCase().includes(q) || hotel.address.toLowerCase().includes(q)) score += 10;
      
      return { hotel, score };
    });
    
    const results = scored
      .filter(s => s.score > 0)
      .sort((a, b) => b.score - a.score)
      .map(s => s.hotel);
    
    // If no results, show all hotels
    set({ searchResults: results.length > 0 ? results : hotels });
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
  },

  addAgentLog: (msg: string) => set(state => ({ agentLog: [...state.agentLog, msg] })),
  clearAgentLog: () => set({ agentLog: [] }),
}));
