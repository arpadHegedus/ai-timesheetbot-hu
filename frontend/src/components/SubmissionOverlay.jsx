import React from 'react';

// status: 'idle' | 'loading' | 'success'
export default function SubmissionOverlay({ status, onDismiss }) {
  if (status === 'idle') return null;
  const isSuccess = status === 'success';
  return (
    <div
      onClick={isSuccess ? onDismiss : undefined}
      className={`fixed inset-0 z-50 flex flex-col items-center justify-center p-6 transition-colors duration-500 ${
        isSuccess ? 'bg-emerald-600 cursor-pointer' : 'bg-slate-900/95 cursor-wait'
      }`}
    >
      {!isSuccess && (
        <div className="flex flex-col items-center space-y-4">
          <div className="w-16 h-16 border-4 border-emerald-400 border-t-transparent rounded-full animate-spin" />
          <p className="text-xl font-semibold text-white tracking-wide">Jelentés küldése...</p>
        </div>
      )}
      {isSuccess && (
        <div className="flex flex-col items-center space-y-4 text-center animate-bounce-in">
          <div className="w-20 h-20 bg-white rounded-full flex items-center justify-center shadow-lg">
            <svg className="w-12 h-12 text-emerald-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <h2 className="text-3xl font-bold text-white">Jelentés elküldve!</h2>
          <p className="text-emerald-100 text-sm">Koppints bárhová a bezáráshoz és a csevegés törléséhez</p>
        </div>
      )}
    </div>
  );
}
