import React from 'react';
import { useStore } from '../store';
import { X, Terminal } from 'lucide-react';

export const AgentLog: React.FC = () => {
  const { agentLog, clearAgentLog } = useStore();

  if (agentLog.length === 0) return null;

  return (
    <div className="fixed bottom-4 right-4 w-80 bg-gray-900 text-gray-100 rounded-xl shadow-2xl overflow-hidden z-50">
      <div className="flex items-center justify-between px-4 py-2 bg-gray-800 border-b border-gray-700">
        <div className="flex items-center gap-2">
          <Terminal className="w-4 h-4 text-green-400" />
          <span className="text-sm font-mono font-semibold">Agent Pipeline</span>
        </div>
        <button onClick={clearAgentLog} className="text-gray-400 hover:text-white">
          <X className="w-4 h-4" />
        </button>
      </div>
      <div className="max-h-60 overflow-y-auto p-3 space-y-1 font-mono text-xs">
        {agentLog.map((msg, i) => (
          <div key={i} className="flex items-start gap-2">
            <span className="text-green-400">▸</span>
            <span className="text-gray-300">{msg}</span>
          </div>
        ))}
      </div>
    </div>
  );
};
