import React, { useState } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { useStore } from '../store';
import { Map } from '../components/Map';
import { FeatureBadge } from '../components/FeatureBadge';
import { ConfidenceBar } from '../components/ConfidenceBar';
import { ArrowLeft, MapPin, Star, MessageSquare, GitCompare, ExternalLink, AlertTriangle, RefreshCw } from 'lucide-react';

/** Значение, записанное из ответа отельера, — как его увидит гость. */
function describeRecorded(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'boolean') return value ? 'да' : 'нет';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

export const HotelPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { hotels, toggleCompare, selectedHotelIds, refreshHotel } = useStore();
  const [expandedFeature, setExpandedFeature] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const hotel = hotels.find(h => h.id === parseInt(id || '0'));

  if (!hotel) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <p className="text-4xl mb-4">🏨</p>
          <h1 className="text-2xl font-bold text-gray-900">Отель не найден</h1>
          <Link to="/search" className="text-ocean-600 hover:underline mt-2 inline-block">← Вернуться к поиску</Link>
        </div>
      </div>
    );
  }

  const pendingQuestions = hotel.questions.filter(q => q.status === 'pending');
  const answeredQuestions = hotel.questions.filter(q => q.status === 'answered');
  const staleFeatures = hotel.features.filter(f => f.stale);
  const disputedFeatures = hotel.features.filter(f => f.disputed);
  const isInCompare = selectedHotelIds.includes(hotel.id);

  const handleRefresh = async () => {
    setRefreshing(true);
    await refreshHotel(hotel.id);
    setRefreshing(false);
  };

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <div className="bg-white border-b border-gray-200">
        <div className="max-w-6xl mx-auto px-6 py-4">
          <button onClick={() => navigate(-1)} className="flex items-center gap-1 text-gray-500 hover:text-gray-900 text-sm mb-3">
            <ArrowLeft className="w-4 h-4" /> Назад
          </button>
          <div className="flex items-start justify-between">
            <div>
              <div className="flex items-center gap-3">
                <span className="text-4xl">{hotel.image}</span>
                <div>
                  <h1 className="text-2xl font-bold text-gray-900">{hotel.name}</h1>
                  <p className="text-gray-500 flex items-center gap-1 mt-1">
                    <MapPin className="w-4 h-4" /> {hotel.address}
                  </p>
                </div>
              </div>
            </div>
            <div className="text-right">
              <div className="text-2xl font-bold text-ocean-700">{hotel.price_per_night.toLocaleString()} ₽</div>
              <div className="text-sm text-gray-500">за ночь</div>
              <div className="flex items-center gap-1 mt-1 justify-end">
                {Array.from({ length: hotel.stars }).map((_, i) => (
                  <Star key={i} className="w-3 h-3 fill-amber-400 text-amber-400" />
                ))}
              </div>
            </div>
          </div>
          <p className="text-gray-600 mt-3">{hotel.description}</p>
          
          <div className="flex gap-2 mt-4">
            <button
              onClick={() => toggleCompare(hotel.id)}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition ${
                isInCompare ? 'bg-ocean-100 text-ocean-700' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
              }`}
            >
              <GitCompare className="w-4 h-4" />
              {isInCompare ? 'В сравнении' : 'Добавить к сравнению'}
            </button>
            {selectedHotelIds.length >= 2 && (
              <button
                onClick={() => navigate('/compare')}
                className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium bg-ocean-600 text-white hover:bg-ocean-700"
              >
                Перейти к сравнению →
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-6 py-6">
        <div className="grid lg:grid-cols-3 gap-6">
          {/* Map */}
          <div className="lg:col-span-1">
            <div className="h-[350px] rounded-xl overflow-hidden border border-gray-200 shadow-sm sticky top-24">
              <Map
                hotels={[hotel]}
                showSunsetRays={true}
                selectedHotelId={hotel.id}
                center={[hotel.lon, hotel.lat]}
                zoom={13}
              />
            </div>
          </div>

          {/* Features */}
          <div className="lg:col-span-2 space-y-4">
            <h2 className="text-lg font-bold text-gray-900">Скрытые характеристики</h2>
            <p className="text-sm text-gray-500">
              Вычислены агентной системой из геоданных (SRTM, OSM, Wikidata, Open-Meteo). 
              Нажмите на карточку для подробностей.
            </p>

            {(staleFeatures.length > 0 || disputedFeatures.length > 0) && (
              <div className="bg-amber-50 border border-amber-200 rounded-xl p-4">
                <div className="flex items-start gap-3">
                  <AlertTriangle className="w-5 h-5 text-amber-500 mt-0.5 shrink-0" />
                  <div className="flex-1">
                    {staleFeatures.length > 0 && (
                      <p className="text-sm font-medium text-amber-900">
                        Устарели: {staleFeatures.map(f => f.label).join(', ')}
                      </p>
                    )}
                    <p className="text-xs text-amber-700 mt-1">
                      {staleFeatures.length > 0
                        ? 'Срок актуальности истёк: рядом могли построить дом или измениться шум. Значение не удалено, но требует перепроверки.'
                        : 'Источники дали разные значения — разбор доступен в кабинете отельера.'}
                    </p>
                  </div>
                  <button
                    onClick={handleRefresh}
                    disabled={refreshing}
                    className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium bg-amber-600 text-white hover:bg-amber-700 disabled:opacity-50 disabled:cursor-not-allowed transition shrink-0"
                  >
                    <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
                    {refreshing ? 'Запускаем…' : 'Перепроверить'}
                  </button>
                </div>
              </div>
            )}

            <div className="grid gap-3">
              {hotel.features.map(feature => (
                <FeatureBadge
                  key={feature.key}
                  feature={feature}
                  expanded={expandedFeature === feature.key}
                  onToggleExpand={() => setExpandedFeature(expandedFeature === feature.key ? null : feature.key)}
                />
              ))}
            </div>

            {/* Agent questions */}
            {pendingQuestions.length > 0 && (
              <div className="mt-6">
                <h3 className="text-lg font-bold text-gray-900 flex items-center gap-2">
                  <MessageSquare className="w-5 h-5 text-amber-500" />
                  Агент спрашивает отельера
                </h3>
                <div className="space-y-3 mt-3">
                  {pendingQuestions.map(q => (
                    <div key={q.id} className="bg-amber-50 border border-amber-200 rounded-xl p-4">
                      <div className="flex items-start gap-3">
                        <span className="text-xl">🤖</span>
                        <div className="flex-1">
                          <p className="text-sm font-medium text-amber-900">{q.question}</p>
                          <p className="text-xs text-amber-600 mt-1">
                            Ожидает ответа • feature: {q.feature_key}
                          </p>
                          <Link
                            to="/hotelier"
                            className="inline-flex items-center gap-1 text-xs text-ocean-600 hover:text-ocean-800 font-medium mt-2"
                          >
                            <ExternalLink className="w-3 h-3" />
                            Ответить в кабинете отельера →
                          </Link>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Answered questions */}
            {answeredQuestions.length > 0 && (
              <div className="mt-6">
                <h3 className="text-lg font-bold text-gray-900 flex items-center gap-2">
                  <MessageSquare className="w-5 h-5 text-emerald-500" />
                  Ответы отельера
                </h3>
                <div className="space-y-3 mt-3">
                  {answeredQuestions.map(q => (
                    <div key={q.id} className="bg-emerald-50 border border-emerald-200 rounded-xl p-4">
                      <div className="flex items-start gap-3">
                        <span className="text-xl">🤖</span>
                        <div className="flex-1">
                          <p className="text-sm font-medium text-emerald-900">Вопрос: {q.question}</p>
                          <div className="mt-2 bg-white rounded-lg p-3 border border-emerald-100">
                            <p className="text-sm text-gray-700">{q.answer_raw}</p>
                            <div className="flex items-center gap-2 mt-2 flex-wrap">
                              <span className="text-xs bg-emerald-100 text-emerald-700 px-2 py-0.5 rounded-full">
                                Источник: отельер
                              </span>
                              {typeof q.confidence === 'number' ? (
                                <ConfidenceBar value={q.confidence} size="sm" />
                              ) : (
                                <span className="text-xs text-gray-500">уверенность не записана</span>
                              )}
                              {q.answered_at && (
                                <span className="text-xs text-gray-400">{q.answered_at.slice(0, 10)}</span>
                              )}
                            </div>
                            <p className="text-xs text-gray-500 mt-2">
                              Записано в характеристики:{' '}
                              <span className="font-medium text-gray-700">{describeRecorded(q.value)}</span>
                            </p>
                          </div>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Overall confidence */}
            <div className="mt-6 bg-white border border-gray-200 rounded-xl p-5">
              <h3 className="font-bold text-gray-900 mb-3">Общая достоверность профиля</h3>
              <div className="flex items-center gap-4">
                <div className="text-4xl font-bold text-ocean-700">
                  {Math.round(hotel.features.reduce((sum, f) => sum + f.confidence, 0) / hotel.features.length * 100)}%
                </div>
                <div className="flex-1">
                  <ConfidenceBar
                    value={hotel.features.reduce((sum, f) => sum + f.confidence, 0) / hotel.features.length}
                    size="lg"
                  />
                  <p className="text-xs text-gray-500 mt-1">
                    Средний confidence по {hotel.features.length} характеристикам
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
