import React from 'react';
import { ConfidenceBar } from './ConfidenceBar';
import type { HotelFeature } from '../data/mockHotels';

interface FeatureBadgeProps {
  feature: HotelFeature;
  expanded?: boolean;
  onToggleExpand?: () => void;
}

export const FeatureBadge: React.FC<FeatureBadgeProps> = ({ feature, expanded = false, onToggleExpand }) => {
  return (
    <div
      className={`border rounded-xl p-4 transition-all cursor-pointer hover:shadow-md ${
        expanded ? 'border-ocean-300 bg-ocean-50 shadow-md' : 'border-gray-200 bg-white'
      }`}
      onClick={onToggleExpand}
    >
      <div className="flex items-start gap-3">
        <span className="text-2xl">{feature.icon}</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between">
            <h4 className="font-semibold text-gray-900 text-sm">{feature.label}</h4>
            <span className="text-xs text-gray-500 bg-gray-100 px-2 py-0.5 rounded-full">
              {feature.source}
            </span>
          </div>
          <p className="text-ocean-700 font-medium mt-1">{feature.value}</p>
          
          <div className="mt-2">
            <ConfidenceBar value={feature.confidence} size="sm" />
          </div>
          
          {expanded && (
            <div className="mt-3 space-y-2 animate-in">
              <p className="text-sm text-gray-600">{feature.detail}</p>
              {feature.evidence && (
                <div className="bg-gray-50 rounded-lg p-3 mt-2">
                  <p className="text-xs font-semibold text-gray-500 uppercase mb-1">Доказательства</p>
                  <pre className="text-xs text-gray-700 overflow-x-auto whitespace-pre-wrap">
                    {JSON.stringify(feature.evidence, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
