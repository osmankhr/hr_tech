export function mapCandidateFromApi(candidate) {
  return {
    id: candidate.id,
    createdByName: candidate.created_by_name,
    updatedByName: candidate.updated_by_name,
    firstContactedByName: candidate.first_contacted_by_name,
    firstContactedAt: candidate.first_contacted_at,
    candidateCode: candidate.candidate_code,
    name: candidate.full_name,
    email: candidate.email,
    role: candidate.current_title,
    location: candidate.location,
    source: candidate.source,
    profileUrl: candidate.profile_url,
    score: candidate.score || 0,
    status: candidate.status,
    yearsExperience: candidate.years_experience,
    lastUpdated: candidate.last_updated,
    notes: candidate.notes,
    skills: (candidate.skills || "")
      .split(",")
      .map((skill) => skill.trim())
      .filter(Boolean),
  };
}

export function candidateToFormData(candidate) {
  const formData = new FormData();

  formData.append("full_name", candidate.name || "");
  formData.append("email", candidate.email || "");
  formData.append("current_title", candidate.role || "");
  formData.append("location", candidate.location || "");
  formData.append("source", candidate.source || "Manual");
  formData.append("profile_url", candidate.profileUrl || "");
  formData.append("score", candidate.score || 0);
  formData.append("status", candidate.status || "New");
  formData.append("years_experience", candidate.yearsExperience || 0);
  formData.append("skills", (candidate.skills || []).join(", "));
  formData.append("notes", candidate.notes || "");

  return formData;
}