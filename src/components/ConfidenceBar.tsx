import React from 'react';

interface ConfidenceBarProps {
  value: number; // 0-1
  showLabel?: boolean;
  size?: 'sm' | 'md' | 'lg';
}

export const ConfidenceBar: React.FC<ConfidenceBarProps> = ({ value, showLabel = true, size = 'md' }) => {
  const percentage = Math.round(value * 100);
  
  const getColor = () => {
    if (value >= 0.8) return 'bg-emerald-500';
    if (value >= 0.6) return 'bg-amber-500';
    return 'bg-red-500';
  };
  
  const getTextColor = () => {
    if (value >= 0.8) return 'text-emerald-700';
    if (value >= 0.6) return 'text-amber-700';
    return 'text-red-700';
  };
  
  const heights = { sm: 'h-1.5', md: 'h-2.5', lg: 'h-4' };

  return (
    <div className="flex items-center gap-2">
      <div className={`flex-1 bg-gray-200 rounded-full overflow-hidden ${heights[size]}`}>
        <div
          className={`h-full rounded-full confidence-bar-fill transition-all ${getColor()}`}
          style={{ width: `${percentage}%` }}
        />
      </div>
      {showLabel && (
        <span className={`text-xs font-semibold ${getTextColor()} min-w-[3ch]`}>
          {percentage}%
        </span>
      )}
    </div>
  );
};
