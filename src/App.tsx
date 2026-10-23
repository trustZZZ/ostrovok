import React from 'react';
import { HashRouter, Routes, Route, Link, useLocation } from 'react-router-dom';
import { Home } from './pages/Home';
import { SearchPage } from './pages/Search';
import { HotelPage } from './pages/Hotel';
import { Hotelier } from './pages/Hotelier';
import { Compare } from './pages/Compare';
import { AgentLog } from './components/AgentLog';
import { Home as HomeIcon, Search, MessageSquare, GitCompare } from 'lucide-react';

const Navigation: React.FC = () => {
  const location = useLocation();
  
  const navItems = [
    { path: '/', label: 'Маршруты', icon: HomeIcon },
    { path: '/search', label: 'Поиск', icon: Search },
    { path: '/hotelier', label: 'Отельер', icon: MessageSquare },
    { path: '/compare', label: 'Сравнение', icon: GitCompare },
  ];

  return (
    <nav className="bg-white border-b border-gray-200 sticky top-0 z-50">
      <div className="max-w-6xl mx-auto px-6">
        <div className="flex items-center justify-between h-14">
          <Link to="/" className="flex items-center gap-2 font-bold text-gray-900 hover:text-ocean-600 transition">
            <span className="text-xl">🌅</span>
            <span className="hidden sm:inline">Routely × Островок</span>
          </Link>
          <div className="flex items-center gap-1">
            {navItems.map(item => {
              const isActive = location.pathname === item.path || 
                (item.path !== '/' && location.pathname.startsWith(item.path));
              const Icon = item.icon;
              return (
                <Link
                  key={item.path}
                  to={item.path}
                  className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium transition ${
                    isActive
                      ? 'bg-ocean-50 text-ocean-700'
                      : 'text-gray-600 hover:text-gray-900 hover:bg-gray-50'
                  }`}
                >
                  <Icon className="w-4 h-4" />
                  <span className="hidden sm:inline">{item.label}</span>
                </Link>
              );
            })}
          </div>
        </div>
      </div>
    </nav>
  );
};

const App: React.FC = () => {
  return (
    <HashRouter>
      <div className="min-h-screen bg-gray-50">
        <Navigation />
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/hotel/:id" element={<HotelPage />} />
          <Route path="/hotelier" element={<Hotelier />} />
          <Route path="/compare" element={<Compare />} />
        </Routes>
        <AgentLog />
      </div>
    </HashRouter>
  );
};

export default App;
