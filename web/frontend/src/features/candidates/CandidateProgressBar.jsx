import React from 'react';

const STAGES = [
  { id: 'New', label: 'New' },
  { id: 'Reviewed', label: 'Reviewed' },
  { id: 'Shortlisted', label: 'Shortlisted' },
  { id: 'Contacted', label: 'Contacted' },
];

export function CandidateProgressBar({ currentStatus }) {
  // If Rejected, we handle it slightly differently
  const isRejected = currentStatus === 'Rejected';
  
  // Find index. If rejected, it's not in the main path usually, or we can just show the steps leading up to it.
  let currentIndex = STAGES.findIndex(s => s.id === currentStatus);
  if (currentIndex === -1 && !isRejected) currentIndex = 0; // fallback

  return (
    <div className="w-full py-4 mb-4">
      <div className="flex items-center justify-between relative">
        {/* Background track line */}
        <div className="absolute left-0 top-1/2 -translate-y-1/2 w-full h-1 bg-slate-200 rounded-full z-0"></div>
        
        {/* Active track line */}
        {!isRejected && currentIndex > 0 && (
          <div 
            className="absolute left-0 top-1/2 -translate-y-1/2 h-1 bg-orange-500 rounded-full z-0 transition-all duration-500 ease-in-out"
            style={{ width: `${(currentIndex / (STAGES.length - 1)) * 100}%` }}
          ></div>
        )}

        {STAGES.map((stage, idx) => {
          const isCompleted = idx <= currentIndex && !isRejected;
          const isCurrent = idx === currentIndex && !isRejected;
          const isPast = idx < currentIndex && !isRejected;

          return (
            <div key={stage.id} className="relative z-10 flex flex-col items-center group">
              <div 
                className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-semibold transition-colors duration-300 shadow-sm
                  ${isCurrent ? 'bg-orange-600 text-white ring-4 ring-orange-100' : 
                    isPast ? 'bg-orange-500 text-white' : 
                    isRejected ? 'bg-slate-200 text-slate-400' : 'bg-white text-slate-400 border-2 border-slate-200'}
                `}
              >
                {isPast ? (
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7"></path></svg>
                ) : (
                  idx + 1
                )}
              </div>
              <div className={`mt-2 text-xs font-medium transition-colors duration-300
                ${isCurrent ? 'text-orange-700' : isCompleted ? 'text-slate-700' : 'text-slate-400'}
              `}>
                {stage.label}
              </div>
            </div>
          );
        })}
      </div>
      
      {isRejected && (
        <div className="mt-4 flex justify-center">
          <span className="px-3 py-1 bg-red-100 text-red-700 text-xs font-semibold rounded-full shadow-sm border border-red-200 flex items-center gap-1">
             <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12"></path></svg>
            Candidate Rejected
          </span>
        </div>
      )}
    </div>
  );
}
