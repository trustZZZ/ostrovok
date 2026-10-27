import React from 'react';
import { useStore } from '../store';
import { ConfidenceBar } from '../components/ConfidenceBar';
import { ArrowLeft, Trophy } from 'lucide-react';
import { Link } from 'react-router-dom';
import { isSunsetVisible } from '../lib/features';

export const Compare: React.FC = () => {
  const { hotels, selectedHotelIds, toggleCompare } = useStore();
  const selectedHotels = hotels.filter(h => selectedHotelIds.includes(h.id));

  if (selectedHotels.length < 2) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center max-w-md">
          <span className="text-5xl">📊</span>
          <h1 className="text-2xl font-bold text-gray-900 mt-4">Недостаточно отелей</h1>
          <p className="text-gray-500 mt-2">
            Выберите минимум 2 отеля для сравнения. Вернитесь к поиску и нажмите «Сравнить».
          </p>
          <Link
            to="/search"
            className="inline-flex items-center gap-2 mt-4 px-6 py-3 bg-ocean-600 text-white rounded-xl font-medium hover:bg-ocean-700"
          >
            <ArrowLeft className="w-4 h-4" />
            К поиску
          </Link>
        </div>
      </div>
    );
  }

  // Collect all unique feature keys
  const allFeatureKeys = Array.from(
    new Set(selectedHotels.flatMap(h => h.features.map(f => f.key)))
  );

  const getFeatureValue = (hotel: typeof selectedHotels[0], key: string) => {
    return hotel.features.find(f => f.key === key);
  };

  const getWinner = (key: string): number | null => {
    const values = selectedHotels.map(h => {
      const f = getFeatureValue(h, key);
      if (!f) return null;
      
      // Different scoring logic per feature
      if (key === 'sunset_view') return isSunsetVisible(h) ? 100 : 0;
      if (key === 'noise_score') {
        const match = f.value.match(/(\d+)/);
        return match ? 100 - parseInt(match[1]) : 50; // lower noise = better
      }
      if (key === 'walk_to_sea') {
        const match = f.value.match(/(\d+)/);
        return match ? 100 - parseInt(match[1]) * 10 : 50; // fewer minutes = better
      }
      if (key === 'air_quality') {
        const match = f.value.match(/AQI\s*(\d+)/);
        return match ? 100 - parseInt(match[1]) * 2 : 50;
      }
      return f.confidence * 100;
    });
    
    const maxVal = Math.max(...values.filter(v => v !== null) as number[]);
    const winnerIdx = values.indexOf(maxVal);
    return winnerIdx >= 0 ? selectedHotels[winnerIdx].id : null;
  };

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <div className="bg-white border-b border-gray-200">
        <div className="max-w-6xl mx-auto px-6 py-4">
          <Link to="/search" className="flex items-center gap-1 text-gray-500 hover:text-gray-900 text-sm mb-3">
            <ArrowLeft className="w-4 h-4" /> К поиску
          </Link>
          <h1 className="text-2xl font-bold text-gray-900">Сравнение отелей</h1>
          <p className="text-gray-500 text-sm">Сравнение по скрытым характеристикам с учётом достоверности</p>
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-6 py-6">
        {/* Hotel cards */}
        <div className="grid gap-4 mb-6" style={{ gridTemplateColumns: `repeat(${selectedHotels.length}, 1fr)` }}>
          {selectedHotels.map(hotel => (
            <div key={hotel.id} className="bg-white rounded-xl border border-gray-200 p-4">
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <span className="text-3xl">{hotel.image}</span>
                  <div>
                    <h3 className="font-bold text-gray-900">{hotel.name}</h3>
                    <p className="text-xs text-gray-500">{hotel.address}</p>
                  </div>
                </div>
                <button
                  onClick={() => toggleCompare(hotel.id)}
                  className="text-xs text-red-500 hover:text-red-700"
                >
                  ✕
                </button>
              </div>
              <div className="mt-3 flex items-center justify-between">
                <span className="font-bold text-ocean-700">{hotel.price_per_night.toLocaleString()} ₽</span>
                <div className="flex items-center gap-0.5">
                  {Array.from({ length: hotel.stars }).map((_, i) => (
                    <span key={i} className="text-amber-400 text-xs">★</span>
                  ))}
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Comparison table */}
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="text-left px-4 py-3 text-sm font-semibold text-gray-600 w-48">Характеристика</th>
                {selectedHotels.map(h => (
                  <th key={h.id} className="text-center px-4 py-3 text-sm font-semibold text-gray-600">
                    {h.name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {allFeatureKeys.map((key, idx) => {
                const winnerId = getWinner(key);
                const sampleFeature = selectedHotels.flatMap(h => h.features).find(f => f.key === key);
                if (!sampleFeature) return null;

                return (
                  <tr key={key} className={idx % 2 === 0 ? 'bg-white' : 'bg-gray-50/50'}>
                    <td className="px-4 py-3 border-t border-gray-100">
                      <div className="flex items-center gap-2">
                        <span className="text-lg">{sampleFeature.icon}</span>
                        <span className="text-sm font-medium text-gray-900">{sampleFeature.label}</span>
                      </div>
                    </td>
                    {selectedHotels.map(hotel => {
                      const feature = getFeatureValue(hotel, key);
                      const isWinner = winnerId === hotel.id;
                      
                      if (!feature) {
                        return (
                          <td key={hotel.id} className="px-4 py-3 text-center border-t border-gray-100">
                            <span className="text-gray-300">—</span>
                          </td>
                        );
                      }

                      return (
                        <td
                          key={hotel.id}
                          className={`px-4 py-3 text-center border-t border-gray-100 ${
                            isWinner ? 'bg-emerald-50/50' : ''
                          }`}
                        >
                          <div className="space-y-1">
                            <div className="flex items-center justify-center gap-1">
                              {isWinner && <Trophy className="w-3 h-3 text-amber-500" />}
                              <span className={`text-sm font-medium ${isWinner ? 'text-emerald-700' : 'text-gray-700'}`}>
                                {feature.value}
                              </span>
                            </div>
                            <ConfidenceBar value={feature.confidence} size="sm" />
                            <span className="text-xs text-gray-400">{feature.source}</span>
                          </div>
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
              
              {/* Overall score row */}
              <tr className="bg-ocean-50 border-t-2 border-ocean-200">
                <td className="px-4 py-3 font-bold text-ocean-900">
                  <div className="flex items-center gap-2">
                    <span className="text-lg">📊</span>
                    Общая достоверность
                  </div>
                </td>
                {selectedHotels.map(hotel => {
                  const avgConfidence = hotel.features.reduce((sum, f) => sum + f.confidence, 0) / hotel.features.length;
                  return (
                    <td key={hotel.id} className="px-4 py-3 text-center">
                      <div className="text-lg font-bold text-ocean-700">
                        {Math.round(avgConfidence * 100)}%
                      </div>
                      <ConfidenceBar value={avgConfidence} size="sm" />
                    </td>
                  );
                })}
              </tr>
            </tbody>
          </table>
        </div>

        {/* Agent explanation */}
        <div className="mt-6 bg-white rounded-xl border border-gray-200 p-5">
          <h3 className="font-bold text-gray-900 flex items-center gap-2">
            🤖 Объяснение агента
          </h3>
          <p className="text-sm text-gray-600 mt-2">
            На основе анализа скрытых характеристик, {selectedHotels.length > 2 
              ? `из ${selectedHotels.length} отелей` 
              : 'из двух отелей'
            } лучше всего соответствует запросу «тихий отдых у моря с видом на закат»:
          </p>
          <div className="mt-3 bg-ocean-50 rounded-lg p-4">
            <p className="text-sm text-ocean-800">
              <strong>{selectedHotels[0]?.name}</strong> — 
              {selectedHotels[0] && isSunsetVisible(selectedHotels[0])
                ? ' прямой вид на закат над Балтикой'
                : ' нет вида на закат, но компенсируется другими характеристиками'}
              , шум {selectedHotels[0]?.features.find(f => f.key === 'noise_score')?.value || 'N/A'},
              {' '}{selectedHotels[0]?.features.find(f => f.key === 'walk_to_sea')?.value || 'N/A'} до моря.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};
