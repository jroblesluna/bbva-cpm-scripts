'use client';

import React from 'react';
import { RefreshCw } from 'lucide-react';

interface RefreshOverlayProps {
  isRefreshing: boolean;
  children: React.ReactNode;
}

export function RefreshOverlay({ isRefreshing, children }: RefreshOverlayProps) {
  return (
    <>
      {children}
      {isRefreshing && (
        <div className="fixed inset-0 z-50 bg-white/60 backdrop-blur-[1px] flex items-center justify-center">
          <RefreshCw className="w-10 h-10 text-blue-600 animate-spin" />
        </div>
      )}
    </>
  );
}
