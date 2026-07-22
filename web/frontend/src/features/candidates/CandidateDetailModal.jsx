import React, { useMemo, useState } from "react";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Modal } from "../../components/ui/Modal";
import { CandidateProgressBar } from "./CandidateProgressBar";
import { CandidateComments } from "./CandidateComments";
import { CandidateActivityLog } from "./CandidateActivityLog";

export function CandidateDetailModal({ candidate, onClose, onEdit }) {
  const [activeTab, setActiveTab] = useState("details");
  const [selectedFeatureId, setSelectedFeatureId] = useState(null);

  const featureAssessments = useMemo(() => {
    const assessments = candidate?.ranking?.agent?.feature_assessments;
    return Array.isArray(assessments) ? assessments : [];
  }, [candidate]);

  const assessmentsByFeatureId = useMemo(() => {
    const byId = new Map();
    featureAssessments.forEach((assessment) => {
      if (assessment?.feature_id) {
        byId.set(assessment.feature_id, assessment);
      }
    });
    return byId;
  }, [featureAssessments]);

  const selectedFeatureAssessment = selectedFeatureId
    ? assessmentsByFeatureId.get(selectedFeatureId) || null
    : null;

  if (!candidate) return null;

  return (
    <>
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
                      {Object.entries(candidate.ranking.feature_contributions || {}).map(([featureName, weightedPoints]) => {
                        const assessment = assessmentsByFeatureId.get(featureName);
                        const weightedMax = getWeightedMaxPoints(
                          candidate?.ranking?.manual,
                          featureName,
                          weightedPoints,
                          assessment
                        );
                        const weightedScore = formatFeatureScore(weightedPoints, weightedMax);

                        return (
                          <button
                            key={featureName}
                            type="button"
                            onClick={() => setSelectedFeatureId(featureName)}
                            className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 shadow-sm transition-all hover:-translate-y-0.5 hover:border-orange-200 hover:shadow"
                          >
                            <div className="flex items-center justify-between gap-3">
                              <span className="text-left text-sm font-medium text-slate-700">
                                {humanizeFeatureName(featureName)}
                              </span>
                              <span className="rounded-full bg-orange-50 px-2.5 py-1 text-xs font-semibold text-orange-700">
                                {weightedScore}
                              </span>
                            </div>
                            <div className="mt-1 text-left text-xs text-slate-500">
                              Weighted score out of max contribution
                            </div>
                          </button>
                        );
                      })}
                    </div>
                    <p className="mt-2 text-xs text-slate-500">
                      Click any feature to view evidence and notes.
                    </p>
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

      {selectedFeatureId && (
        <Modal
          title={`Feature Assessment: ${humanizeFeatureName(selectedFeatureId)}`}
          onClose={() => setSelectedFeatureId(null)}
          size="max-w-2xl"
        >
          <FeatureAssessmentContent
            featureId={selectedFeatureId}
            assessment={selectedFeatureAssessment}
          />
        </Modal>
      )}
    </>
  );
}

function FeatureAssessmentContent({ featureId, assessment }) {
  if (!assessment) {
    return (
      <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
        No assessment details found for {humanizeFeatureName(featureId)}.
      </div>
    );
  }

  const evidences = Array.isArray(assessment.evidence) ? assessment.evidence : [];

  return (
    <div className="space-y-4">
      <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
        <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">Score</p>
        <p className="mt-1 text-base font-semibold text-slate-900">
          {formatNumber(assessment.raw_points)} / {formatNumber(assessment.max_points)}
        </p>
      </div>

      <div>
        <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">Evidence</p>
        <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3">
          {evidences.length > 0 ? (
            <ul className="list-disc space-y-2 pl-5 text-sm text-slate-700">
              {evidences.map((item, index) => (
                <li key={`${featureId}-evidence-${index}`}>{item}</li>
              ))}
            </ul>
          ) : (
            <p className="text-sm italic text-slate-400">No evidence provided.</p>
          )}
        </div>
      </div>

      <div>
        <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">Notes</p>
        <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700">
          {assessment.notes || <span className="italic text-slate-400">No notes provided.</span>}
        </div>
      </div>
    </div>
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

function humanizeFeatureName(featureName = "") {
  return String(featureName)
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatNumber(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return "-";
  }

  if (Number.isInteger(numeric)) {
    return String(numeric);
  }

  return numeric.toFixed(2).replace(/\.00$/, "");
}

function formatFeatureScore(points, maxPoints) {
  const current = formatNumber(points);
  const max = formatNumber(maxPoints);

  if (max === "-") {
    return current;
  }

  return `${current}/${max}`;
}

function getWeightedMaxPoints(manualRanking, featureId, weightedPoints, assessment) {
  const directWeight = Number(manualRanking?.feature_weights?.[featureId]);
  if (Number.isFinite(directWeight) && directWeight > 0) {
    return directWeight;
  }

  const rawPoints = Number(assessment?.raw_points);
  const rawMax = Number(assessment?.max_points);
  const contribution = Number(weightedPoints);

  if (
    Number.isFinite(rawPoints) &&
    Number.isFinite(rawMax) &&
    rawMax > 0 &&
    Number.isFinite(contribution)
  ) {
    const ratio = rawPoints / rawMax;
    if (ratio > 0) {
      return roundToTwo(contribution / ratio);
    }
  }

  return null;
}

function roundToTwo(value) {
  return Math.round(value * 100) / 100;
}