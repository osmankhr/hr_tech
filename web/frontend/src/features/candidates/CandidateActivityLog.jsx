import React, { useEffect, useState } from 'react';
import { candidateApi } from '../../api/candidateApi';
import { format } from 'date-fns'; // We need date-fns or similar, we'll assume it exists or use native

export function CandidateActivityLog({ candidateId }) {
  const [activities, setActivities] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (candidateId) {
      candidateApi.getActivities(candidateId).then(data => {
        setActivities(data);
        setLoading(false);
      }).catch(err => {
        console.error("Failed to load activities", err);
        setLoading(false);
      });
    }
  }, [candidateId]);

  if (loading) return <div className="p-4 text-center text-sm text-slate-500">Loading activity...</div>;
  if (activities.length === 0) return <div className="p-4 text-center text-sm text-slate-500">No activity recorded yet.</div>;

  return (
    <div className="space-y-6 py-4">
      <div className="relative border-l border-slate-200 ml-3 space-y-6">
        {activities.map((activity, idx) => {
          const dateStr = new Date(activity.created_at).toLocaleString();
          return (
            <div key={idx} className="relative pl-6">
              <span className="absolute -left-1.5 top-1.5 w-3 h-3 rounded-full bg-slate-300 ring-4 ring-white"></span>
              <div className="bg-slate-50 rounded-xl p-3 text-sm shadow-sm border border-slate-100">
                <div className="flex justify-between items-start mb-1">
                  <span className="font-semibold text-slate-800">{activity.user_name || 'System'}</span>
                  <span className="text-xs text-slate-400">{dateStr}</span>
                </div>
                <div className="font-medium text-slate-700">{activity.action}</div>
                {activity.description && <div className="text-slate-500 mt-1 text-xs">{activity.description}</div>}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
