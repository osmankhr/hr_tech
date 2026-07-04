export function mapCampaignFromApi(campaign) {
  return {
    id: campaign.id,
    createdByName: campaign.created_by_name,
    updatedByName: campaign.updated_by_name,
    campaignCode: campaign.campaign_code,
    campaignName: campaign.campaign_name,
    location: campaign.location,
    positionName: campaign.position_name,
    experience: campaign.experience,
    sampleCvName: campaign.sample_cv_filename,
    desiredSkills: (campaign.desired_skills || "")
      .split(",")
      .map((skill) => skill.trim())
      .filter(Boolean),
    targetProfiles: campaign.target_profiles || 0,
    status: campaign.status,
    owner: campaign.owner,
    createdAt: campaign.created_at?.slice(0, 10),
    updatedAt: campaign.updated_at,
    candidates: campaign.candidate_count || 0,
    shortlisted: campaign.shortlisted_count || 0,
  };
}

export function campaignToFormData(campaignForm, selectedSkills) {
  const formData = new FormData();

  formData.append("campaign_name", campaignForm.campaignName);
  formData.append("location", campaignForm.location);
  formData.append("position_name", campaignForm.positionName);
  formData.append("experience", campaignForm.experience);
  formData.append("desired_skills", selectedSkills.join(", "));
  formData.append("target_profiles", campaignForm.targetProfiles);
  formData.append("status", campaignForm.status || "Active");

  if (campaignForm.sampleCvFile) {
    formData.append("sample_cv", campaignForm.sampleCvFile);
  }

  return formData;
}

export function campaignToEditForm(campaign) {
  return {
    campaignName: campaign.campaignName || "",
    location: campaign.location || "",
    positionName: campaign.positionName || "",
    desiredSkillsText: (campaign.desiredSkills || []).join(", "),
    experience: campaign.experience || "3-5",
    sampleCvFile: null,
    targetProfiles: campaign.targetProfiles || 25,
    status: campaign.status || "Active",
  };
}