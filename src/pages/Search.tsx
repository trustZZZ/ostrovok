import React, { useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useStore } from '../store';
import { Map } from '../components/Map';
import { ConfidenceBar } from '../components/ConfidenceBar';
import { Search, MapPin, Sparkles, ArrowRight, Star, GitCompare } from 'lucide-react';
import { AgentPipeline } from '../components/AgentPipeline';
import { findFeature, isSunsetVisible, noiseScore, walkMinutes } from '../lib/features';

export const SearchPage: React.FC = () => {
  const {
    hotels,
    searchResults,
    performSearch,
    searchQuery,
    toggleCompare,
    selectedHotelIds,
    isSearching,
    dataSource,
  } = useStore();
  const [inputValue, setInputValue] = useState('');
  const [showPipeline, setShowPipeline] = useState(false);
  const [expandedHotel, setExpandedHotel] = useState<number | null>(null);
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  useEffect(() => {
    const routeId = searchParams.get('route');
    if (routeId) {
      // Pre-fill with route hotels
      const route = useStore.getState().routes.find(r => r.id === parseInt(routeId));
      if (route) {
        const routeHotels = hotels.filter(h => route.hotel_ids.includes(h.id));
        useStore.setState({ searchResults: routeHotels, searchQuery: route.title });
        setInputValue(route.title);
      }
    }
  }, [searchParams]);

  const handleSearch = async (query: string) => {
    setShowPipeline(true);
    await performSearch(query);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (inputValue.trim()) {
      handleSearch(inputValue);
    }
  };

  const displayedHotels = searchResults.length > 0 ? searchResults : hotels;

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Search bar */}
      <div className="bg-white border-b border-gray-200 sticky top-0 z-10 shadow-sm">
        <div className="max-w-6xl mx-auto px-6 py-4">
          <form onSubmit={handleSubmit} className="flex gap-3">
            <div className="flex-1 relative">
              <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
              <input
                type="text"
                value={inputValue}
                onChange={e => setInputValue(e.target.value)}
                placeholder="Опишите, что хотите: «тихий номер с видом на закат над морем, 5 минут до пляжа»..."
                className="w-full pl-12 pr-4 py-3 border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-ocean-500 focus:border-transparent text-gray-900"
              />
            </div>
            <button
              type="submit"
              disabled={isSearching}
              className="px-6 py-3 bg-ocean-600 text-white font-semibold rounded-xl hover:bg-ocean-700 transition disabled:opacity-50 flex items-center gap-2"
            >
              {isSearching ? (
                <>
                  <Sparkles className="w-4 h-4 animate-spin" />
                  Агент ищет...
                </>
              ) : (
                <>
                  <Sparkles className="w-4 h-4" />
                  Найти
                </>
              )}
            </button>
          </form>
          
          {/* Quick search suggestions */}
          <div className="flex flex-wrap gap-2 mt-3">
            {[
              'тихий номер с видом на закат',
              '5 минут до пляжа без трассы',
              'историческое здание',
              'pet-friendly с котом',
              'семейный с детской площадкой',
            ].map(suggestion => (
              <button
                key={suggestion}
                onClick={() => { setInputValue(suggestion); handleSearch(suggestion); }}
                className="text-xs bg-ocean-50 text-ocean-700 px-3 py-1.5 rounded-full hover:bg-ocean-100 transition"
              >
                {suggestion}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-6 py-6">
        {/* Agent Pipeline Visualization */}
        {showPipeline && (
          <div className="mb-6">
            <AgentPipeline
              active={showPipeline}
              onComplete={() => setTimeout(() => setShowPipeline(false), 1000)}
            />
          </div>
        )}
        
        <div className="grid lg:grid-cols-2 gap-6">
          {/* Map */}
          <div className="h-[500px] lg:h-[calc(100vh-220px)] lg:sticky lg:top-24 rounded-xl overflow-hidden border border-gray-200 shadow-sm">
            <Map
              hotels={displayedHotels}
              showSunsetRays={true}
              selectedHotelId={expandedHotel}
              onHotelClick={(id) => navigate(`/hotel/${id}`)}
            />
          </div>

          {/* Results */}
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-gray-900">
                {searchQuery ? `Результаты: «${searchQuery}»` : 'Все отели'}
              </h2>
              <div className="flex items-center gap-2">
                <span className="text-sm text-gray-500">{displayedHotels.length} отелей</span>
                <span
                  className={`text-[11px] px-2 py-0.5 rounded-full font-medium ${
                    dataSource === 'api'
                      ? 'bg-emerald-50 text-emerald-700'
                      : 'bg-amber-50 text-amber-700'
                  }`}
                  title={
                    dataSource === 'api'
                      ? 'Характеристики собраны системой и лежат в БД'
                      : 'Бэкенд недоступен: показан демонстрационный набор'
                  }
                >
                  {dataSource === 'api' ? 'данные из БД' : 'демо-набор'}
                </span>
              </div>
            </div>

            {displayedHotels.map(hotel => {
              const sunsetFeature = findFeature(hotel, 'sunset_view');
              const noiseFeature = findFeature(hotel, 'noise_score');
              const walkFeature = findFeature(hotel, 'walk_to_sea');
              const sunsetVisible = isSunsetVisible(hotel);
              const noise = noiseScore(hotel);
              const walk = walkMinutes(hotel);
              const isExpanded = expandedHotel === hotel.id;
              const isInCompare = selectedHotelIds.includes(hotel.id);

              return (
                <div
                  key={hotel.id}
                  className={`bg-white rounded-xl border transition-all ${
                    isExpanded ? 'border-ocean-300 shadow-lg' : 'border-gray-200 shadow-sm hover:shadow-md'
                  }`}
                >
                  <div className="p-4">
                    <div className="flex gap-4">
                      <div className="text-4xl">{hotel.image}</div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-start justify-between">
                          <div>
                            <h3
                              className="font-bold text-gray-900 cursor-pointer hover:text-ocean-600"
                              onClick={() => navigate(`/hotel/${hotel.id}`)}
                            >
                              {hotel.name}
                            </h3>
                            <p className="text-sm text-gray-500 flex items-center gap-1">
                              <MapPin className="w-3 h-3" />
                              {hotel.address}
                            </p>
                          </div>
                          {hotel.price_per_night > 0 && (
                            <div className="text-right">
                              <div className="font-bold text-ocean-700">{hotel.price_per_night.toLocaleString()} ₽</div>
                              <div className="text-xs text-gray-500">за ночь</div>
                            </div>
                          )}
                        </div>

                        {/* Key features */}
                        <div className="flex flex-wrap gap-2 mt-3">
                          {sunsetFeature && (
                            <span className={`text-xs px-2 py-1 rounded-full font-medium ${
                              sunsetVisible ? 'bg-sunset-100 text-sunset-600' : 'bg-gray-100 text-gray-500'
                            }`}>
                              🌅 {sunsetFeature.value}
                            </span>
                          )}
                          {noiseFeature && (
                            <span className="text-xs px-2 py-1 rounded-full font-medium bg-emerald-50 text-emerald-700">
                              🤫 {noiseFeature.value}
                            </span>
                          )}
                          {walkFeature && (
                            <span className="text-xs px-2 py-1 rounded-full font-medium bg-blue-50 text-blue-700">
                              🚶 {walkFeature.value}
                            </span>
                          )}
                        </div>

                        {/* Actions */}
                        <div className="flex items-center gap-2 mt-3">
                          <button
                            onClick={() => setExpandedHotel(isExpanded ? null : hotel.id)}
                            className="text-xs text-ocean-600 hover:text-ocean-800 font-medium flex items-center gap-1"
                          >
                            {isExpanded ? 'Свернуть' : 'Подробнее'}
                            <ArrowRight className={`w-3 h-3 transition ${isExpanded ? 'rotate-90' : ''}`} />
                          </button>
                          <button
                            onClick={() => toggleCompare(hotel.id)}
                            className={`text-xs font-medium flex items-center gap-1 px-2 py-1 rounded-lg transition ${
                              isInCompare ? 'bg-ocean-100 text-ocean-700' : 'text-gray-500 hover:text-ocean-600'
                            }`}
                          >
                            <GitCompare className="w-3 h-3" />
                            {isInCompare ? 'В сравнении' : 'Сравнить'}
                          </button>
                          <button
                            onClick={() => navigate(`/hotel/${hotel.id}`)}
                            className="text-xs text-gray-500 hover:text-ocean-600 font-medium ml-auto"
                          >
                            Карточка →
                          </button>
                        </div>
                      </div>
                    </div>

                    {/* Expanded details */}
                    {isExpanded && (
                      <div className="mt-4 pt-4 border-t border-gray-100 space-y-3">
                        <p className="text-sm text-gray-600">{hotel.description}</p>
                        
                        {/* Why this hotel */}
                        {searchQuery && (
                          <div className="bg-ocean-50 rounded-lg p-3">
                            <p className="text-sm font-semibold text-ocean-800 flex items-center gap-1">
                              <Sparkles className="w-4 h-4" />
                              Почему подходит:
                            </p>
                            {hotel.explanation ? (
                              <p className="text-sm text-ocean-700 mt-1">{hotel.explanation}</p>
                            ) : (
                              <ul className="text-sm text-ocean-700 mt-1 space-y-1">
                                {sunsetVisible && <li>✓ Вид на закат над морем</li>}
                                {noise !== null && noise < 30 && <li>✓ Тихий район (шум {noiseFeature?.value})</li>}
                                {walk !== null && walk <= 5 && <li>✓ {walkFeature?.value} до моря пешком</li>}
                              </ul>
                            )}
                          </div>
                        )}
                        
                        {/* Confidence overview */}
                        <div className="grid grid-cols-2 gap-2">
                          {hotel.features.slice(0, 4).map(f => (
                            <div key={f.key} className="flex items-center gap-2">
                              <span className="text-sm">{f.icon}</span>
                              <span className="text-xs text-gray-600 truncate">{f.label}</span>
                              <div className="flex-1">
                                <ConfidenceBar value={f.confidence} size="sm" showLabel={false} />
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}

            {/* Compare bar */}
            {selectedHotelIds.length >= 2 && (
              <div className="fixed bottom-6 left-1/2 -translate-x-1/2 bg-ocean-700 text-white px-6 py-3 rounded-full shadow-xl flex items-center gap-3 z-20">
                <GitCompare className="w-5 h-5" />
                <span className="font-medium">Сравнить {selectedHotelIds.length} отеля</span>
                <button
                  onClick={() => navigate('/compare')}
                  className="bg-white text-ocean-700 px-4 py-1.5 rounded-full text-sm font-semibold hover:bg-ocean-50"
                >
                  Открыть →
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
