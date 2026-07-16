import React, { useState } from "react";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Modal } from "../../components/ui/Modal";
import { CandidateProgressBar } from "./CandidateProgressBar";
import { CandidateComments } from "./CandidateComments";
import { CandidateActivityLog } from "./CandidateActivityLog";

export function CandidateDetailModal({ candidate, onClose, onEdit }) {
  const [activeTab, setActiveTab] = useState("details");

  if (!candidate) return null;

  return (
    <Modal title="Candidate Details" onClose={onClose}>
      <div className="flex flex-col h-[75vh]">
        {/* Header & Progress Bar */}
        <div className="shrink-0 border-b border-slate-100 pb-4 mb-4">
          <div className="flex justify-between items-start mb-4">
            <div>
              <h4 className="text-2xl font-bold text-slate-800">{candidate.name || candidate.full_name}</h4>
              <p className="text-slate-500 font-medium">{candidate.role || candidate.current_title || "Unknown Role"}</p>
            </div>
            {candidate.profileUrl && (
              <a href={candidate.profileUrl} target="_blank" rel="noopener noreferrer">
                <Button variant="outline" size="sm" className="text-orange-600 border-orange-200 hover:bg-orange-50">
                  <svg className="w-4 h-4 mr-1 inline" fill="currentColor" viewBox="0 0 24 24"><path d="M19 0h-14c-2.761 0-5 2.239-5 5v14c0 2.761 2.239 5 5 5h14c2.762 0 5-2.239 5-5v-14c0-2.761-2.238-5-5-5zm-11 19h-3v-11h3v11zm-1.5-12.268c-.966 0-1.75-.79-1.75-1.764s.784-1.764 1.75-1.764 1.75.79 1.75 1.764-.783 1.764-1.75 1.764zm13.5 12.268h-3v-5.604c0-3.368-4-3.113-4 0v5.604h-3v-11h3v1.765c1.396-2.586 7-2.777 7 2.476v6.759z"/></svg>
                  LinkedIn
                </Button>
              </a>
            )}
          </div>
          <CandidateProgressBar currentStatus={candidate.status} />
        </div>

        {/* Tabs */}
        <div className="flex gap-4 border-b border-slate-200 shrink-0 mb-4 px-1">
          <TabButton active={activeTab === "details"} onClick={() => setActiveTab("details")}>Details</TabButton>
          <TabButton active={activeTab === "comments"} onClick={() => setActiveTab("comments")}>Comments</TabButton>
          <TabButton active={activeTab === "activity"} onClick={() => setActiveTab("activity")}>Activity Log</TabButton>
        </div>

        {/* Tab Content */}
        <div className="flex-1 overflow-y-auto pr-2">
          {activeTab === "details" && (
            <div className="space-y-6 pb-4">
              <div className="grid gap-4 md:grid-cols-2">
                <Info label="Candidate Code" value={candidate.candidateCode || candidate.candidate_code} />
                <Info label="Email" value={candidate.email} />
                <Info label="Location" value={candidate.location} />
                <Info label="Source" value={candidate.source} />
                <Info label="Status" value={candidate.status} />
                <Info label="Score" value={candidate.score} />
                <Info label="Experience" value={candidate.yearsExperience || candidate.years_experience} />
                <Info label="Last Updated" value={candidate.lastUpdated || candidate.last_updated} />
              </div>

              {candidate.ranking && (
                <div className="bg-slate-50 rounded-2xl p-4 border border-slate-100 shadow-sm">
                  <p className="mb-3 font-semibold text-slate-800">Explainable Score</p>
                  <div className="grid gap-3 md:grid-cols-3 mb-4">
                    <Info label="Manual Score" value={candidate.ranking.manual_score} />
                    <Info label="Rank" value={candidate.ranking.rank} />
                    <Info label="Category" value={candidate.ranking.category} />
                  </div>
                  <div>
                    <p className="mb-2 text-xs uppercase tracking-wider text-slate-500 font-semibold">
                      Feature Contributions
                    </p>
                    <div className="grid gap-2">
                      {Object.entries(candidate.ranking.feature_contributions || {}).map(([featureName, points]) => (
                        <div key={featureName} className="flex items-center justify-between rounded-xl border border-slate-200 bg-white px-3 py-2 shadow-sm">
                          <span className="text-sm font-medium text-slate-700">{featureName}</span>
                          <span className="text-sm font-bold text-orange-600">{points}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              <div>
                <p className="mb-2 font-semibold text-slate-800">Skills</p>
                <div className="flex flex-wrap gap-2">
                  {(candidate.skills || []).map((skill) => (
                    <Badge key={skill} tone="orange">{skill}</Badge>
                  ))}
                  {(!candidate.skills || candidate.skills.length === 0) && (
                    <span className="text-slate-400 text-sm italic">No skills listed.</span>
                  )}
                </div>
              </div>

              <div>
                <p className="mb-2 font-semibold text-slate-800">Notes</p>
                <div className="rounded-2xl bg-slate-50 p-4 border border-slate-100 text-slate-700 text-sm shadow-inner min-h-[80px]">
                  {candidate.notes || <span className="text-slate-400 italic">No notes available.</span>}
                </div>
              </div>

              <div className="flex justify-end pt-4 border-t border-slate-100">
                <Button onClick={() => onEdit(candidate)}>Edit Manually</Button>
              </div>
            </div>
          )}

          {activeTab === "comments" && (
            <CandidateComments candidateId={candidate.id} />
          )}

          {activeTab === "activity" && (
            <CandidateActivityLog candidateId={candidate.id} />
          )}
        </div>
      </div>
    </Modal>
  );
}

function TabButton({ active, onClick, children }) {
  return (
    <button
      onClick={onClick}
      className={`pb-3 px-2 text-sm font-semibold transition-all border-b-2 ${
        active 
          ? "border-orange-500 text-orange-600" 
          : "border-transparent text-slate-500 hover:text-slate-700 hover:border-slate-300"
      }`}
    >
      {children}
    </button>
  );
}

function Info({ label, value }) {
  return (
    <div className="rounded-2xl bg-slate-50 border border-slate-100 p-3 shadow-sm transition-all hover:shadow-md">
      <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1">{label}</p>
      <p className="font-medium text-slate-900">{value || "-"}</p>
    </div>
  );
}