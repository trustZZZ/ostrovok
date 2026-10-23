import React from 'react';
import { Link } from 'react-router-dom';
import { useStore } from '../store';
import { MapPin, Calendar, Star } from 'lucide-react';

export const Home: React.FC = () => {
  const { routes, hotels } = useStore();

  return (
    <div className="min-h-screen bg-gradient-to-b from-ocean-50 to-white">
      {/* Hero */}
      <section className="relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-br from-ocean-600 via-ocean-700 to-ocean-900" />
        <div className="absolute inset-0 opacity-20">
          <div className="absolute top-10 right-20 text-8xl">🌅</div>
          <div className="absolute bottom-10 left-10 text-6xl">🏨</div>
          <div className="absolute top-1/2 right-1/3 text-5xl">🐱</div>
        </div>
        <div className="relative max-w-6xl mx-auto px-6 py-20 text-white">
          <div className="flex items-center gap-2 mb-4">
            <span className="text-2xl">🌅</span>
            <span className="font-bold text-xl">Routely × Островок</span>
          </div>
          <h1 className="text-4xl md:text-5xl font-bold mb-4 leading-tight">
            Отели по скрытым<br />характеристикам
          </h1>
          <p className="text-xl text-ocean-100 mb-8 max-w-2xl">
            Не звёзды и не фильтры — а реальные данные: вид на закат над морем, тишина, 
            5 минут до пляжа без трассы. Агентная система на основе геоданных.
          </p>
          <div className="flex gap-4 flex-wrap">
            <Link
              to="/search"
              className="px-6 py-3 bg-white text-ocean-700 font-semibold rounded-xl hover:bg-ocean-50 transition shadow-lg"
            >
              🔍 Поиск на естественном языке
            </Link>
            <Link
              to="/hotelier"
              className="px-6 py-3 bg-ocean-500/30 text-white font-semibold rounded-xl hover:bg-ocean-500/50 transition border border-ocean-300/50"
            >
              📋 Кабинет отельера
            </Link>
          </div>
        </div>
      </section>

      {/* How it works */}
      <section className="max-w-6xl mx-auto px-6 py-12">
        <h2 className="text-2xl font-bold text-gray-900 mb-6">Как это работает</h2>
        <div className="grid md:grid-cols-4 gap-4">
          {[
            { icon: '🛰️', title: 'Геоданные', desc: 'SRTM DEM, OSM 3D-здания, Wikidata' },
            { icon: '🤖', title: 'Агент', desc: 'LangGraph: вычисляет, ищет конфликты, спрашивает' },
            { icon: '💬', title: 'Отельер', desc: 'Свободные ответы → структурированные данные' },
            { icon: '🎯', title: 'Поиск', desc: '«Тихий номер с видом на закат» → топ отелей' },
          ].map((step, i) => (
            <div key={i} className="bg-white rounded-xl p-5 border border-gray-100 shadow-sm">
              <span className="text-3xl">{step.icon}</span>
              <h3 className="font-semibold mt-2">{step.title}</h3>
              <p className="text-sm text-gray-600 mt-1">{step.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Routes */}
      <section className="max-w-6xl mx-auto px-6 py-12">
        <h2 className="text-2xl font-bold text-gray-900 mb-2">Маршруты от блогеров</h2>
        <p className="text-gray-600 mb-6">Готовые подборки отелей, подобранных по скрытым характеристикам</p>
        <div className="grid md:grid-cols-2 gap-6">
          {routes.map(route => {
            const routeHotels = hotels.filter(h => route.hotel_ids.includes(h.id));
            return (
              <Link
                key={route.id}
                to={`/search?route=${route.id}`}
                className="group bg-white rounded-2xl border border-gray-100 overflow-hidden shadow-sm hover:shadow-xl transition-all"
              >
                <div className="h-40 bg-gradient-to-br from-ocean-100 to-sunset-100 flex items-center justify-center relative">
                  <span className="text-6xl">{route.cover_emoji}</span>
                  <div className="absolute top-3 right-3 bg-white/90 rounded-full px-3 py-1 text-xs font-semibold flex items-center gap-1">
                    <Calendar className="w-3 h-3" />
                    {route.days} дня
                  </div>
                </div>
                <div className="p-5">
                  <h3 className="font-bold text-lg text-gray-900 group-hover:text-ocean-600 transition">
                    {route.title}
                  </h3>
                  <p className="text-sm text-gray-500 mt-1">by {route.author}</p>
                  <p className="text-sm text-gray-600 mt-2 line-clamp-2">{route.description}</p>
                  
                  <div className="flex flex-wrap gap-2 mt-3">
                    {route.key_features.map(f => (
                      <span key={f} className="text-xs bg-ocean-50 text-ocean-700 px-2 py-1 rounded-full font-medium">
                        {f}
                      </span>
                    ))}
                  </div>
                  
                  <div className="flex items-center gap-2 mt-4 pt-3 border-t border-gray-100">
                    {routeHotels.map(h => (
                      <div key={h.id} className="flex items-center gap-1 text-xs text-gray-500">
                        <span>{h.image}</span>
                        <span className="truncate max-w-[100px]">{h.name}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </Link>
            );
          })}
        </div>
      </section>

      {/* Stats */}
      <section className="max-w-6xl mx-auto px-6 py-12">
        <div className="bg-gradient-to-r from-ocean-600 to-ocean-800 rounded-2xl p-8 text-white">
          <h2 className="text-2xl font-bold mb-6">Данные, которые мы используем</h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {[
              { label: 'Отелей в базе', value: '8', icon: '🏨' },
              { label: 'Фич на отель', value: '6+', icon: '📊' },
              { label: 'Источников данных', value: '10', icon: '🛰️' },
              { label: 'Точность sunset_view', value: '88%', icon: '🎯' },
            ].map((stat, i) => (
              <div key={i} className="text-center">
                <span className="text-2xl">{stat.icon}</span>
                <div className="text-2xl font-bold mt-1">{stat.value}</div>
                <div className="text-ocean-200 text-sm">{stat.label}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-gray-100 py-8 text-center text-sm text-gray-500">
        <p>Хакатон «О!дин шаг до идеального отеля» — Островок × Routely</p>
        <p className="mt-1">Агентная система подбора отелей по скрытым характеристикам</p>
      </footer>
    </div>
  );
};
