import React, { useEffect, useState } from 'react';
import { CheckCircle, Circle, Loader2 } from 'lucide-react';

interface PipelineStep {
  label: string;
  icon: string;
  duration: number;
}

const STEPS: PipelineStep[] = [
  { label: 'Парсинг запроса (LLM)', icon: '🧠', duration: 400 },
  { label: 'GIS: sunset_view (SRTM + OSM)', icon: '🌅', duration: 600 },
  { label: 'GIS: noise_score (OSM)', icon: '🤫', duration: 400 },
  { label: 'GIS: walk_to_sea (OSM + DEM)', icon: '🚶', duration: 500 },
  { label: 'Open Data: Wikidata', icon: '🏛️', duration: 300 },
  { label: 'Open Data: Open-Meteo', icon: '☀️', duration: 300 },
  { label: 'Поиск конфликтов', icon: '⚠️', duration: 400 },
  { label: 'Ранжирование результатов', icon: '📊', duration: 300 },
];

interface AgentPipelineProps {
  active: boolean;
  onComplete?: () => void;
}

export const AgentPipeline: React.FC<AgentPipelineProps> = ({ active, onComplete }) => {
  const [currentStep, setCurrentStep] = useState(-1);
  const [completedSteps, setCompletedSteps] = useState<number[]>([]);

  useEffect(() => {
    if (!active) {
      setCurrentStep(-1);
      setCompletedSteps([]);
      return;
    }

    let timeout: ReturnType<typeof setTimeout>;
    let stepIndex = 0;

    const runStep = () => {
      if (stepIndex >= STEPS.length) {
        onComplete?.();
        return;
      }
      
      setCurrentStep(stepIndex);
      
      timeout = setTimeout(() => {
        setCompletedSteps(prev => [...prev, stepIndex]);
        stepIndex++;
        runStep();
      }, STEPS[stepIndex].duration);
    };

    runStep();

    return () => clearTimeout(timeout);
  }, [active]);

  if (!active && currentStep === -1) return null;

  return (
    <div className="bg-gray-900 rounded-xl p-4 text-white">
      <div className="flex items-center gap-2 mb-3">
        <Loader2 className="w-4 h-4 animate-spin text-ocean-400" />
        <span className="text-sm font-semibold">Агентный конвейер</span>
      </div>
      <div className="space-y-1.5">
        {STEPS.map((step, i) => {
          const isCompleted = completedSteps.includes(i);
          const isCurrent = currentStep === i;
          
          return (
            <div
              key={i}
              className={`flex items-center gap-2 text-xs transition-all ${
                isCompleted ? 'text-emerald-400' : isCurrent ? 'text-white' : 'text-gray-500'
              }`}
            >
              {isCompleted ? (
                <CheckCircle className="w-3.5 h-3.5 text-emerald-400" />
              ) : isCurrent ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin text-ocean-400" />
              ) : (
                <Circle className="w-3.5 h-3.5" />
              )}
              <span>{step.icon}</span>
              <span className={isCurrent ? 'font-medium' : ''}>{step.label}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
};
