/**
 * API клиент для связи с бэкендом.
 * В демо-режиме использует мок-данные.
 */

const API_BASE = (import.meta as any).env?.VITE_API_URL || '/api';

export interface SearchRequest {
  query: string;
  region?: string;
  limit?: number;
}

export interface HotelFeature {
  key: string;
  value: any;
  source: string;
  confidence: number;
  raw_evidence?: Record<string, any>;
}

export interface Hotel {
  id: number;
  name: string;
  address: string;
  lat: number;
  lon: number;
  floors: number;
  facade_azimuth: number;
  features: HotelFeature[];
}

export interface SearchResponse {
  hotels: (Hotel & { explanation: string; score: number })[];
  agent_log: string[];
}

// In demo mode, we use mock data directly from the frontend
const USE_MOCK = true;

export async function searchHotels(query: string): Promise<SearchResponse> {
  if (USE_MOCK) {
    // Mock response - handled in store.ts
    return { hotels: [], agent_log: [] };
  }
  
  const res = await fetch(`${API_BASE}/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query }),
  });
  return res.json();
}

export async function getHotelFeatures(hotelId: number): Promise<HotelFeature[]> {
  if (USE_MOCK) return [];
  
  const res = await fetch(`${API_BASE}/hotels/${hotelId}/features`);
  return res.json();
}

export async function enrichHotel(hotelId: number): Promise<{ thread_id: string }> {
  const res = await fetch(`${API_BASE}/hotels/${hotelId}/enrich`, { method: 'POST' });
  return res.json();
}

export async function getHotelierInbox(): Promise<any[]> {
  if (USE_MOCK) return [];
  
  const res = await fetch(`${API_BASE}/hotelier/inbox`);
  return res.json();
}

export async function answerQuestion(
  hotelId: number,
  questionId: number,
  answer: string,
): Promise<void> {
  await fetch(`${API_BASE}/hotelier/${hotelId}/answer/${questionId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ answer }),
  });
}

export async function getRoutes(): Promise<any[]> {
  if (USE_MOCK) return [];
  
  const res = await fetch(`${API_BASE}/routes`);
  return res.json();
}
