import React, { useState } from 'react';
import { useStore } from '../store';
import { MessageSquare, Send, CheckCircle, Clock, AlertTriangle } from 'lucide-react';

export const Hotelier: React.FC = () => {
  const { hotels, answerQuestion } = useStore();
  const [answers, setAnswers] = useState<Record<number, string>>({});

  // Collect all pending questions across all hotels
  const allQuestions = hotels.flatMap(hotel =>
    hotel.questions.map(q => ({ ...q, hotel_name: hotel.name, hotel_id: hotel.id, hotel_image: hotel.image }))
  );

  const pendingQuestions = allQuestions.filter(q => q.status === 'pending');
  const answeredQuestions = allQuestions.filter(q => q.status === 'answered');

  const handleSubmit = (hotelId: number, questionId: number) => {
    const answer = answers[questionId];
    if (answer && answer.trim()) {
      answerQuestion(hotelId, questionId, answer.trim());
      setAnswers(prev => { const n = { ...prev }; delete n[questionId]; return n; });
    }
  };

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <div className="bg-white border-b border-gray-200">
        <div className="max-w-4xl mx-auto px-6 py-6">
          <div className="flex items-center gap-3">
            <span className="text-3xl">📋</span>
            <div>
              <h1 className="text-2xl font-bold text-gray-900">Кабинет отельера</h1>
              <p className="text-gray-500 text-sm">
                Агентная система задала вопросы по вашему отелю. Ответьте — и данные обогатятся.
              </p>
            </div>
          </div>
        </div>
      </div>

      <div className="max-w-4xl mx-auto px-6 py-6 space-y-6">
        {/* Stats */}
        <div className="grid grid-cols-3 gap-4">
          <div className="bg-white rounded-xl border border-gray-200 p-4 text-center">
            <div className="text-2xl font-bold text-amber-600">{pendingQuestions.length}</div>
            <div className="text-sm text-gray-500">Ожидают ответа</div>
          </div>
          <div className="bg-white rounded-xl border border-gray-200 p-4 text-center">
            <div className="text-2xl font-bold text-emerald-600">{answeredQuestions.length}</div>
            <div className="text-sm text-gray-500">Отвечено</div>
          </div>
          <div className="bg-white rounded-xl border border-gray-200 p-4 text-center">
            <div className="text-2xl font-bold text-ocean-600">{hotels.length}</div>
            <div className="text-sm text-gray-500">Отелей в системе</div>
          </div>
        </div>

        {/* Pending questions */}
        {pendingQuestions.length > 0 && (
          <div>
            <h2 className="text-lg font-bold text-gray-900 flex items-center gap-2 mb-4">
              <Clock className="w-5 h-5 text-amber-500" />
              Ожидают ответа
            </h2>
            <div className="space-y-4">
              {pendingQuestions.map(q => (
                <div key={q.id} className="bg-white rounded-xl border border-amber-200 overflow-hidden">
                  <div className="p-5">
                    <div className="flex items-start gap-3">
                      <span className="text-2xl">{q.hotel_image}</span>
                      <div className="flex-1">
                        <p className="font-semibold text-gray-900">{q.hotel_name}</p>
                        <p className="text-sm text-gray-500">feature: {q.feature_key}</p>
                      </div>
                      <span className="text-xs bg-amber-100 text-amber-700 px-2 py-1 rounded-full">
                        Ожидает
                      </span>
                    </div>
                    
                    <div className="mt-4 bg-amber-50 rounded-lg p-4 border border-amber-100">
                      <div className="flex items-start gap-2">
                        <span className="text-lg">🤖</span>
                        <p className="text-gray-800">{q.question}</p>
                      </div>
                    </div>

                    <div className="mt-4">
                      <textarea
                        value={answers[q.id] || ''}
                        onChange={e => setAnswers(prev => ({ ...prev, [q.id]: e.target.value }))}
                        placeholder="Введите ваш ответ..."
                        className="w-full border border-gray-200 rounded-lg p-3 text-sm focus:outline-none focus:ring-2 focus:ring-ocean-500 resize-none h-24"
                      />
                      <div className="flex items-center justify-between mt-2">
                        <p className="text-xs text-gray-400">
                          Ответ будет обработан LLM и преобразован в структурированные данные
                        </p>
                        <button
                          onClick={() => handleSubmit(q.hotel_id, q.id)}
                          disabled={!answers[q.id]?.trim()}
                          className="flex items-center gap-2 px-4 py-2 bg-ocean-600 text-white rounded-lg text-sm font-medium hover:bg-ocean-700 disabled:opacity-50 disabled:cursor-not-allowed transition"
                        >
                          <Send className="w-4 h-4" />
                          Отправить
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Answered questions */}
        {answeredQuestions.length > 0 && (
          <div>
            <h2 className="text-lg font-bold text-gray-900 flex items-center gap-2 mb-4">
              <CheckCircle className="w-5 h-5 text-emerald-500" />
              Отвечено
            </h2>
            <div className="space-y-4">
              {answeredQuestions.map(q => (
                <div key={q.id} className="bg-white rounded-xl border border-emerald-200 overflow-hidden">
                  <div className="p-5">
                    <div className="flex items-start gap-3">
                      <span className="text-2xl">{q.hotel_image}</span>
                      <div className="flex-1">
                        <p className="font-semibold text-gray-900">{q.hotel_name}</p>
                        <p className="text-sm text-gray-500">feature: {q.feature_key}</p>
                      </div>
                      <span className="text-xs bg-emerald-100 text-emerald-700 px-2 py-1 rounded-full">
                        ✓ Обработано
                      </span>
                    </div>
                    
                    <div className="mt-3 space-y-2">
                      <div className="bg-gray-50 rounded-lg p-3">
                        <p className="text-xs font-semibold text-gray-500 uppercase mb-1">Вопрос агента</p>
                        <p className="text-sm text-gray-700">{q.question}</p>
                      </div>
                      <div className="bg-emerald-50 rounded-lg p-3">
                        <p className="text-xs font-semibold text-emerald-600 uppercase mb-1">Ваш ответ</p>
                        <p className="text-sm text-gray-800">{q.answer_raw}</p>
                      </div>
                      {q.answer_parsed && (
                        <div className="bg-blue-50 rounded-lg p-3">
                          <p className="text-xs font-semibold text-blue-600 uppercase mb-1">Распознано LLM</p>
                          <pre className="text-xs text-gray-700 overflow-x-auto">
                            {JSON.stringify(q.answer_parsed, null, 2)}
                          </pre>
                          <div className="flex items-center gap-2 mt-2">
                            <span className="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full">
                              Источник: отельер
                            </span>
                            <span className="text-xs text-gray-500">confidence: 0.92</span>
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Empty state */}
        {pendingQuestions.length === 0 && answeredQuestions.length === 0 && (
          <div className="text-center py-12">
            <span className="text-5xl">✅</span>
            <h2 className="text-xl font-bold text-gray-900 mt-4">Всё обработано!</h2>
            <p className="text-gray-500 mt-2">Нет вопросов, ожидающих ответа.</p>
          </div>
        )}

        {/* Info box */}
        <div className="bg-ocean-50 border border-ocean-200 rounded-xl p-5">
          <h3 className="font-bold text-ocean-900 flex items-center gap-2">
            <AlertTriangle className="w-5 h-5" />
            Как это работает
          </h3>
          <ol className="text-sm text-ocean-800 mt-2 space-y-1 list-decimal list-inside">
            <li>Агент вычисляет характеристики из геоданных (OSM, SRTM, Wikidata)</li>
            <li>При неуверенности (confidence &lt; 0.7) или конфликте — формулирует вопрос</li>
            <li>Вы отвечаете свободным текстом</li>
            <li>LLM парсит ответ в структурированные данные (JSONB)</li>
            <li>Новая фича сохраняется с источником «hotelier» и confidence 0.92</li>
          </ol>
        </div>
      </div>
    </div>
  );
};
