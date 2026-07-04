import { useCallback, useEffect, useState } from "react";
import { campaignApi } from "../api/campaignApi";
import { candidateApi } from "../api/candidateApi";
import { skillApi } from "../api/skillApi";
import { DEFAULT_SKILL_SUGGESTIONS } from "../constants/defaults";
import { mapCampaignFromApi } from "../mappers/campaignMapper";
import { mapCandidateFromApi } from "../mappers/candidateMapper";

export function useHrData() {
  const [campaigns, setCampaigns] = useState([]);
  const [candidates, setCandidates] = useState([]);
  const [skillSuggestions, setSkillSuggestions] = useState(
    DEFAULT_SKILL_SUGGESTIONS
  );
  const [loading, setLoading] = useState(true);
  const [apiError, setApiError] = useState("");

  const loadCampaigns = useCallback(async () => {
    const data = await campaignApi.getAll();
    setCampaigns(data.map(mapCampaignFromApi));
  }, []);

  const loadCandidates = useCallback(async () => {
    const data = await candidateApi.getAll();
    setCandidates(data.map(mapCandidateFromApi));
  }, []);

  const loadSkills = useCallback(async () => {
    const data = await skillApi.getAll();

    if (Array.isArray(data) && data.length > 0) {
      setSkillSuggestions(data);
    }
  }, []);

  const loadInitialData = useCallback(async () => {
    setLoading(true);
    setApiError("");

    try {
      await Promise.all([loadCampaigns(), loadCandidates(), loadSkills()]);
    } catch (error) {
      console.error(error);
      setApiError(
        "Could not load data from backend. Please check FastAPI server."
      );
    } finally {
      setLoading(false);
    }
  }, [loadCampaigns, loadCandidates, loadSkills]);

  useEffect(() => {
    loadInitialData();
  }, [loadInitialData]);

  return {
    campaigns,
    candidates,
    skillSuggestions,
    loading,
    apiError,
    setApiError,
    loadCampaigns,
    loadCandidates,
    loadSkills,
  };
}