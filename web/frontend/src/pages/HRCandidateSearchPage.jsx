import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle } from "lucide-react";
import { campaignApi } from "../api/campaignApi";
import { candidateApi } from "../api/candidateApi";
import { AppHeader } from "../components/layout/AppHeader";
import { Sidebar } from "../components/layout/Sidebar";
import { Card } from "../components/ui/Card";
import { Icons } from "../components/ui/Icon";
import { KPI } from "../components/ui/KPI";
import { API_BASE_URL } from "../config/api";
import { EMPTY_CAMPAIGN_FORM, PIPELINE_PHASE_LABELS } from "../constants/defaults";

// Config-version list + selection, tagged with the campaign they belong to.
const EMPTY_VERSION_STATE = { campaignId: "", rows: [], selectedId: "" };
import { CampaignDetailModal } from "../features/campaigns/CampaignDetailModal";
import { CampaignDeleteModal } from "../features/campaigns/CampaignDeleteModal";
import { CampaignEditModal } from "../features/campaigns/CampaignEditModal";
import { CampaignPanel } from "../features/campaigns/CampaignPanel";
import { PipelineCampaignCreateForm } from "../features/campaigns/PipelineCampaignCreateForm";
import { PipelineConfigEditModal } from "../features/campaigns/PipelineConfigEditModal";
import { PipelineConfigVersionList } from "../features/campaigns/PipelineConfigVersionList";
import { CandidateDetailModal } from "../features/candidates/CandidateDetailModal";
import { CandidateEditModal } from "../features/candidates/CandidateEditModal";
import { CandidatePanel } from "../features/candidates/CandidatePanel";
import { useCampaignForm } from "../hooks/useCampaignForm";
import { useHrData } from "../hooks/useHrData";
import {
  campaignToEditForm,
  campaignToFormData,
  mapCampaignFromApi,
  mapCampaignTemplateFromApi,
  mapConfigVersionFromApi,
} from "../mappers/campaignMapper";
import { candidateToFormData, mapCandidateFromApi } from "../mappers/candidateMapper";

const DEFAULT_JOB_DESCRIPTION = `# Senior ML Engineer - NLP / Large Language Models

## About the Role

We are looking for a Senior Machine Learning Engineer with deep expertise in
Natural Language Processing (NLP) and Large Language Models (LLMs). You will
design and deploy production-grade NLP systems and help shape our AI strategy.
`;

const DEFAULT_FILTER_CRITERIA = `# Candidate Filtering Criteria

## Accept (ALL must be met)

1. Seniority: 7+ years of experience, OR Senior / Staff / Principal / Lead title
2. NLP Depth: Must have meaningful NLP experience
3. ML Foundation: Strong background in ML
4. Turkey Connection: Currently based in Turkey, OR has a Turkish background
`;

function buildInitialLocations(locationText = "") {
  const parsed = locationText
    .split(/[\/,]/)
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean)
    .map((name) => ({ name, hint: `Focus on ${name}-based professionals` }));

  if (parsed.length > 0) {
    return parsed;
  }

  return [
    {
      name: "turkey",
      hint: "Focus on Turkey-based professionals (Istanbul, Ankara, Izmir)",
    },
    {
      name: "us",
      hint: "Focus on Turkish diaspora professionals",
    },
  ];
}

function mapCampaignCandidate(item) {
  const base = mapCandidateFromApi(item);
  return {
    ...base,
    ranking: item.ranking || null,
  };
}

export default function HRCandidateSearchPage({ currentUser, onSignOut }) {
  const {
    campaigns,
    candidates,
    skillSuggestions,
    loading,
    apiError,
    setApiError,
    loadCampaigns,
    loadCandidates,
    loadSkills,
  } = useHrData();

  const editFormHook = useCampaignForm(EMPTY_CAMPAIGN_FORM);

  const [view, setView] = useState("dashboard");
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("All");
  const [refreshing, setRefreshing] = useState(false);

  const [showCreate, setShowCreate] = useState(false);
  const [createBusy, setCreateBusy] = useState(false);
  const [createError, setCreateError] = useState("");
  const [createForm, setCreateForm] = useState({
    name: "",
    description: "",
    locations: buildInitialLocations(""),
    jobDescription: DEFAULT_JOB_DESCRIPTION,
    filterCriteria: DEFAULT_FILTER_CRITERIA,
  });
  const [campaignTemplates, setCampaignTemplates] = useState([]);

  const [selectedCampaign, setSelectedCampaign] = useState(null);
  const [editingCampaign, setEditingCampaign] = useState(null);
  const [campaignToDelete, setCampaignToDelete] = useState(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const [selectedCandidate, setSelectedCandidate] = useState(null);
  const [editingCandidate, setEditingCandidate] = useState(null);
  const [scoringExplainer, setScoringExplainer] = useState(null);
  const [usageSummary, setUsageSummary] = useState(null);

  const [dashboardCampaignId, setDashboardCampaignId] = useState("");
  const [dashboardCandidates, setDashboardCandidates] = useState([]);
  const [dashboardPage, setDashboardPage] = useState(1);
  const [dashboardTotalPages, setDashboardTotalPages] = useState(0);
  const [dashboardLoadingCandidates, setDashboardLoadingCandidates] = useState(false);

  const [pipelineCampaignId, setPipelineCampaignId] = useState("");
  const [pipelineRuns, setPipelineRuns] = useState([]);
  const [rankings, setRankings] = useState([]);
  const [pipelineBusy, setPipelineBusy] = useState(false);
  const [pipelineError, setPipelineError] = useState("");
  const [pipelineMessage, setPipelineMessage] = useState("");
  const [pipelineMaxCandidates, setPipelineMaxCandidates] = useState("100");
  // Which phase the running subprocess is in (from SSE), so the progress box names the stage
  // instead of only saying "this can take a few minutes".
  const [pipelineProgress, setPipelineProgress] = useState(null);
  const [campaignArtifactStatus, setCampaignArtifactStatus] = useState({});
  const [campaignExportBusy, setCampaignExportBusy] = useState({});
  const [configVersionsLoading, setConfigVersionsLoading] = useState(false);
  const [configEditOpen, setConfigEditOpen] = useState(false);
  const [configEditBusy, setConfigEditBusy] = useState(false);
  const [configEditError, setConfigEditError] = useState("");
  // Which config version's results are being viewed, per tab. Defaults to the current version;
  // picking an older one shows the candidate list that config produced.
  //
  // Both the list and the selection are stored with the campaign they were loaded for, and read
  // back through the derived values below. Version ids are unique across all campaigns, so a
  // selection left over from the previously viewed campaign is a *valid-looking* id that
  // belongs to someone else — sending it with the new campaign's requests is what produced the
  // "Config version not found" banner. Clearing it in an effect would be too late: the fetch
  // effects run in the same commit as the campaign switch and would fire once on the stale
  // pair. Deriving it during render means the mismatch never reaches a request.
  const [pipelineVersionState, setPipelineVersionState] = useState(EMPTY_VERSION_STATE);
  const [dashboardVersionState, setDashboardVersionState] = useState(EMPTY_VERSION_STATE);
  const autoImportedRunIdsRef = useRef(new Set());

  const configVersions =
    pipelineVersionState.campaignId === pipelineCampaignId ? pipelineVersionState.rows : [];
  const pipelineVersionId =
    pipelineVersionState.campaignId === pipelineCampaignId ? pipelineVersionState.selectedId : "";
  const dashboardConfigVersions =
    dashboardVersionState.campaignId === dashboardCampaignId ? dashboardVersionState.rows : [];
  const dashboardVersionId =
    dashboardVersionState.campaignId === dashboardCampaignId
      ? dashboardVersionState.selectedId
      : "";

  const setPipelineVersionId = (versionId) => {
    setPipelineVersionState((previous) => ({
      ...previous,
      campaignId: pipelineCampaignId,
      selectedId: String(versionId || ""),
    }));
  };

  const setDashboardVersionId = (versionId) => {
    setDashboardVersionState((previous) => ({
      ...previous,
      campaignId: dashboardCampaignId,
      selectedId: String(versionId || ""),
    }));
  };

  const activeCampaigns = useMemo(
    () => campaigns.filter((campaign) => campaign.status === "Active"),
    [campaigns]
  );

  const pastCampaigns = useMemo(
    () => campaigns.filter((campaign) => campaign.status === "Past"),
    [campaigns]
  );

  const selectedDashboardCampaign = useMemo(
    () =>
      campaigns.find((campaign) => String(campaign.id) === String(dashboardCampaignId)) ||
      null,
    [campaigns, dashboardCampaignId]
  );

  const selectedPipelineCampaign = useMemo(
    () =>
      campaigns.find((campaign) => String(campaign.id) === String(pipelineCampaignId)) ||
      null,
    [campaigns, pipelineCampaignId]
  );

  const rankingsByCandidateId = useMemo(() => {
    const lookup = new Map();
    rankings.forEach((ranking) => {
      lookup.set(Number(ranking.candidate_id), ranking);
    });
    return lookup;
  }, [rankings]);

  const candidatesWithRanking = useMemo(
    () =>
      candidates.map((candidate) => ({
        ...candidate,
        ranking: rankingsByCandidateId.get(Number(candidate.id)) || null,
      })),
    [candidates, rankingsByCandidateId]
  );

  const filteredCandidates = useMemo(() => {
    return candidatesWithRanking.filter((candidate) => {
      const searchText = `
        ${candidate.name || ""}
        ${candidate.role || ""}
        ${candidate.location || ""}
        ${candidate.email || ""}
        ${(candidate.skills || []).join(" ")}
      `.toLowerCase();

      const matchesQuery = searchText.includes(query.toLowerCase());
      const matchesStatus =
        statusFilter === "All" || candidate.status === statusFilter;

      return matchesQuery && matchesStatus;
    });
  }, [candidatesWithRanking, query, statusFilter]);

  const pipelineRunning = useMemo(
    () => pipelineRuns.some((run) => run.status === "Running"),
    [pipelineRuns]
  );

  // The backend sends the phase list the run will actually visit, so a partial run
  // (--filter-only and friends) doesn't display stages it will never reach.
  const pipelinePhaseSteps = useMemo(() => {
    const phases = pipelineProgress?.phases;
    if (!Array.isArray(phases) || phases.length === 0) {
      return [];
    }

    const activeIndex = phases.indexOf(pipelineProgress.phase);
    return phases.map((phase, index) => ({
      phase,
      label: PIPELINE_PHASE_LABELS[phase] || phase,
      state:
        activeIndex === -1 || index > activeIndex
          ? "pending"
          : index === activeIndex
            ? "active"
            : "done",
    }));
  }, [pipelineProgress]);

  const pipelineStepLabel = useMemo(() => {
    const phases = pipelineProgress?.phases;
    if (!Array.isArray(phases)) {
      return "";
    }
    const position = phases.indexOf(pipelineProgress.phase);
    return position === -1 ? "" : `Step ${position + 1} of ${phases.length}`;
  }, [pipelineProgress]);

  const pipelineProgressPercent = useMemo(() => {
    const { current, total } = pipelineProgress || {};
    if (typeof current !== "number" || typeof total !== "number" || total <= 0) {
      return null;
    }
    return Math.min(100, Math.round((current / total) * 100));
  }, [pipelineProgress]);

  const currentConfigVersion = useMemo(
    () => configVersions.find((version) => version.isCurrent) || null,
    [configVersions]
  );

  const viewedConfigVersion = useMemo(
    () =>
      configVersions.find((version) => String(version.id) === String(pipelineVersionId)) || null,
    [configVersions, pipelineVersionId]
  );

  const selectedDashboardVersion = useMemo(
    () =>
      dashboardConfigVersions.find(
        (version) => String(version.id) === String(dashboardVersionId)
      ) || null,
    [dashboardConfigVersions, dashboardVersionId]
  );

  const getArtifactStatus = (campaignId) => {
    const key = String(campaignId || "");
    return (
      campaignArtifactStatus[key] || {
        checking: false,
        searchResultsExists: false,
        searchResultsFileCount: 0,
        searchResultsTotalCandidates: 0,
        rankedResultsExists: false,
      }
    );
  };

  const refreshArtifactStatuses = async (campaignIds) => {
    const normalizedIds = [...new Set((campaignIds || []).map((id) => String(id)).filter(Boolean))];
    if (normalizedIds.length === 0) {
      return;
    }

    setCampaignArtifactStatus((prev) => {
      const next = { ...prev };
      normalizedIds.forEach((id) => {
        next[id] = {
          ...(next[id] || {}),
          checking: true,
        };
      });
      return next;
    });

    const updates = await Promise.all(
      normalizedIds.map(async (id) => {
        try {
          const [rankedStatus, searchStatus] = await Promise.all([
            campaignApi.getRankedResultsStatus(id),
            campaignApi.getSearchResultsStatus(id),
          ]);

          return [
            id,
            {
              checking: false,
              rankedResultsExists: Boolean(rankedStatus?.exists),
              searchResultsExists: Boolean(searchStatus?.exists),
              searchResultsFileCount: Number(searchStatus?.file_count || 0),
              searchResultsTotalCandidates: Number(searchStatus?.total_candidates || 0),
            },
          ];
        } catch {
          return [
            id,
            {
              checking: false,
              rankedResultsExists: false,
              searchResultsExists: false,
              searchResultsFileCount: 0,
              searchResultsTotalCandidates: 0,
            },
          ];
        }
      })
    );

    setCampaignArtifactStatus((prev) => {
      const next = { ...prev };
      updates.forEach(([id, status]) => {
        next[id] = {
          ...(next[id] || {}),
          ...status,
        };
      });
      return next;
    });
  };

  useEffect(() => {
    if (!dashboardCampaignId && activeCampaigns.length > 0) {
      setDashboardCampaignId(String(activeCampaigns[0].id));
    }
  }, [dashboardCampaignId, activeCampaigns]);

  useEffect(() => {
    if (!pipelineCampaignId && activeCampaigns.length > 0) {
      setPipelineCampaignId(String(activeCampaigns[0].id));
    }
  }, [pipelineCampaignId, activeCampaigns]);

  // The dashboard browses one campaign's candidates; config versions let it show the list from
  // any config that's been run, not only the newest.
  useEffect(() => {
    if (!dashboardCampaignId) {
      setDashboardVersionState(EMPTY_VERSION_STATE);
      return;
    }

    const campaignId = String(dashboardCampaignId);
    let cancelled = false;
    campaignApi
      .getConfigVersions(campaignId)
      .then((rows) => {
        if (cancelled) return;
        const versions = Array.isArray(rows) ? rows.map(mapConfigVersionFromApi) : [];
        setDashboardVersionState((previous) => ({
          campaignId,
          rows: versions,
          selectedId: pickVersionId(
            previous.campaignId === campaignId ? previous.selectedId : "",
            versions
          ),
        }));
      })
      .catch(() => {
        if (!cancelled) setDashboardVersionState(EMPTY_VERSION_STATE);
      });

    return () => {
      cancelled = true;
    };
  }, [dashboardCampaignId, campaigns]);

  useEffect(() => {
    setDashboardPage(1);
  }, [dashboardVersionId]);

  useEffect(() => {
    if (!dashboardCampaignId) {
      setDashboardCandidates([]);
      setDashboardPage(1);
      setDashboardTotalPages(0);
      return;
    }

    const load = async () => {
      setDashboardLoadingCandidates(true);
      try {
        const data = await campaignApi.getCandidatesByCampaign(
          dashboardCampaignId,
          dashboardPage,
          10,
          dashboardVersionId || null
        );

        const mapped = (data.items || []).map(mapCampaignCandidate);
        setDashboardCandidates(mapped);
        setDashboardTotalPages(data.pagination?.total_pages || 0);
      } catch (error) {
        setApiError(error.message || "Could not load campaign candidates.");
      } finally {
        setDashboardLoadingCandidates(false);
      }
    };

    load();
  }, [dashboardCampaignId, dashboardPage, dashboardVersionId, setApiError]);

  useEffect(() => {
    if (!dashboardCampaignId) {
      setScoringExplainer(null);
      return;
    }

    let cancelled = false;
    campaignApi
      // Each version designs its own scoring features, so the breakdown has to come from the
      // version that actually scored the candidates on screen.
      .getScoringExplainer(dashboardCampaignId, dashboardVersionId || null)
      .then((data) => {
        if (!cancelled) setScoringExplainer(data);
      })
      .catch(() => {
        if (!cancelled) setScoringExplainer(null);
      });

    return () => {
      cancelled = true;
    };
  }, [dashboardCampaignId, dashboardVersionId]);

  // Keeps an explicit selection if it still exists (so a background refresh doesn't yank the
  // recruiter off the version they're reading), otherwise follows the current version.
  const pickVersionId = (previous, versions) => {
    if (previous && versions.some((version) => String(version.id) === String(previous))) {
      return previous;
    }
    const fallback = versions.find((version) => version.isCurrent) || versions[0];
    return fallback ? String(fallback.id) : "";
  };

  const loadConfigVersions = async (campaignId) => {
    if (!campaignId) {
      setPipelineVersionState(EMPTY_VERSION_STATE);
      return [];
    }

    setConfigVersionsLoading(true);
    try {
      const rows = await campaignApi.getConfigVersions(campaignId);
      const versions = Array.isArray(rows) ? rows.map(mapConfigVersionFromApi) : [];
      // Stamped with the campaign it was fetched for: this resolves after an await, by which
      // point the user may have switched campaigns, and the derived values above discard it.
      setPipelineVersionState((previous) => ({
        campaignId: String(campaignId),
        rows: versions,
        selectedId: pickVersionId(
          previous.campaignId === String(campaignId) ? previous.selectedId : "",
          versions
        ),
      }));
      return versions;
    } catch (error) {
      setPipelineError(error.message || "Could not load config version history.");
      return [];
    } finally {
      setConfigVersionsLoading(false);
    }
  };

  const openConfigEdit = () => {
    setConfigEditError("");
    setConfigEditOpen(true);
  };

  const closeConfigEdit = () => {
    setConfigEditOpen(false);
    setConfigEditError("");
  };

  const saveConfigEdit = async (payload) => {
    if (!pipelineCampaignId) {
      return;
    }

    if (!payload.pipelineName) {
      setConfigEditError("Campaign name is required.");
      return;
    }
    if (payload.locations.length === 0) {
      setConfigEditError("At least one location is required.");
      return;
    }
    if (!payload.jobDescription.trim() || !payload.filterCriteria.trim()) {
      setConfigEditError("Job description and filter criteria are required.");
      return;
    }

    setConfigEditBusy(true);
    setConfigEditError("");
    try {
      const result = await campaignApi.updateConfig(pipelineCampaignId, payload);
      setConfigEditOpen(false);
      setPipelineMessage(
        result?.new_version_created
          ? `Saved as config version ${result.version_number}. Earlier versions keep their ` +
              "candidate lists — run the pipeline to populate this one."
          : "Config updated."
      );
      // Jump to the version that was just saved rather than whatever was being viewed.
      if (result?.config_version_id) {
        setPipelineVersionId(String(result.config_version_id));
      }
      await loadConfigVersions(pipelineCampaignId);
      await loadCampaigns().catch(() => {});
      refreshArtifactStatuses([pipelineCampaignId]).catch(() => {});
    } catch (error) {
      setConfigEditError(error.message || "Could not save config changes.");
    } finally {
      setConfigEditBusy(false);
    }
  };

  useEffect(() => {
    // Banners describe the campaign that was on screen when they were raised; carrying them
    // across a switch makes an old failure look like it came from whatever the user just did.
    setPipelineError("");
    setPipelineMessage("");

    if (!pipelineCampaignId) {
      return;
    }

    const load = async () => {
      try {
        const runs = await campaignApi.getPipelineRuns(pipelineCampaignId);
        setPipelineRuns(Array.isArray(runs) ? runs : []);
        await loadConfigVersions(pipelineCampaignId);
      } catch (error) {
        setPipelineError(error.message || "Could not load pipeline state.");
      }
    };

    load();
  }, [pipelineCampaignId]);

  // Rankings are per config version, so they reload whenever the viewed version changes.
  useEffect(() => {
    if (!pipelineCampaignId || !pipelineVersionId) {
      setRankings([]);
      return;
    }

    let cancelled = false;
    campaignApi
      .getRankings(pipelineCampaignId, pipelineVersionId)
      .then((items) => {
        if (!cancelled) setRankings(Array.isArray(items) ? items : []);
      })
      .catch((error) => {
        if (!cancelled) setPipelineError(error.message || "Could not load rankings.");
      });

    return () => {
      cancelled = true;
    };
  }, [pipelineCampaignId, pipelineVersionId]);

  useEffect(() => {
    if (!pipelineCampaignId || !pipelineVersionId) {
      setUsageSummary(null);
      return;
    }

    campaignApi
      .getUsageSummary(pipelineCampaignId, pipelineVersionId)
      .then((data) => setUsageSummary(data))
      .catch(() => setUsageSummary(null));
  }, [pipelineCampaignId, pipelineVersionId, pipelineRuns.length]);

  useEffect(() => {
    // Progress belongs to one campaign's run; switching campaigns must not carry it over.
    setPipelineProgress(null);

    if (!pipelineCampaignId) {
      return;
    }

    const token = localStorage.getItem("hr_auth_token");
    if (!token) {
      return;
    }

    const url = `${API_BASE_URL}/campaigns/${pipelineCampaignId}/pipeline/events?token=${encodeURIComponent(token)}`;
    const eventSource = new EventSource(url);

    const upsertRun = async (run) => {
      if (!run || !run.id) {
        return;
      }

      setPipelineRuns((previousRuns) => {
        const existingIndex = previousRuns.findIndex((item) => item.id === run.id);

        if (existingIndex === -1) {
          return [run, ...previousRuns];
        }

        const nextRuns = [...previousRuns];
        nextRuns[existingIndex] = {
          ...nextRuns[existingIndex],
          ...run,
        };
        return nextRuns;
      });

      if (
        run.status === "Completed" &&
        (run.run_type === "full" || run.run_type === "rank") &&
        !autoImportedRunIdsRef.current.has(run.id)
      ) {
        autoImportedRunIdsRef.current.add(run.id);

        try {
          setPipelineMessage("Pipeline completed. Importing ranked results...");
          // Attribute the import to the version this run used, so results land on the right
          // version even if the config has since moved on.
          await campaignApi.importRankedResults(
            pipelineCampaignId,
            "",
            run.config_version_id ?? null
          );
        } catch (error) {
          setPipelineError(
            error?.message ||
              "Pipeline finished but ranked results import failed. You can import manually."
          );
        }
      }

      if (run.status === "Completed") {
        if (run.config_version_id) {
          setPipelineVersionId(String(run.config_version_id));
        }

        campaignApi
          .getRankings(pipelineCampaignId, run.config_version_id ?? null)
          .then((items) => setRankings(Array.isArray(items) ? items : []))
          .catch(() => {});

        loadCandidates().catch(() => {});
        loadCampaigns().catch(() => {});
        refreshArtifactStatuses([pipelineCampaignId]).catch(() => {});
        loadConfigVersions(pipelineCampaignId).catch(() => {});
      }
    };

    eventSource.addEventListener("pipeline_run_update", async (event) => {
      try {
        const payload = JSON.parse(event.data || "{}");
        setPipelineProgress(payload.progress || null);
        await upsertRun(payload.run);
      } catch {
        // Ignore malformed SSE payloads.
      }
    });

    eventSource.onerror = () => {
      eventSource.close();
    };

    return () => {
      eventSource.close();
    };
  }, [pipelineCampaignId, loadCampaigns, loadCandidates]);

  useEffect(() => {
    if (campaigns.length === 0) {
      setCampaignArtifactStatus({});
      return;
    }

    refreshArtifactStatuses(campaigns.map((campaign) => campaign.id)).catch(() => {});
  }, [campaigns]);

  const loadCampaignTemplates = async () => {
    try {
      const rows = await campaignApi.getTemplates();
      setCampaignTemplates(rows.map(mapCampaignTemplateFromApi));
    } catch (error) {
      // Non-fatal — saved configs are a convenience, not required to create a campaign.
      console.error("Failed to load saved campaign configs:", error);
    }
  };

  const openCreateCampaign = () => {
    setCreateError("");
    setCreateForm({
      name: "",
      description: "",
      locations: buildInitialLocations(""),
      jobDescription: DEFAULT_JOB_DESCRIPTION,
      filterCriteria: DEFAULT_FILTER_CRITERIA,
    });
    setShowCreate(true);
    loadCampaignTemplates();
  };

  const applyCampaignTemplate = (templateId) => {
    const template = campaignTemplates.find((item) => item.id === templateId);
    if (!template) {
      return;
    }
    setCreateError("");
    setCreateForm({
      name: template.templateName || "",
      description: template.pipelineDescription || "",
      locations:
        template.locations.length > 0 ? template.locations : buildInitialLocations(""),
      jobDescription: template.jobDescription || DEFAULT_JOB_DESCRIPTION,
      filterCriteria: template.filterCriteria || DEFAULT_FILTER_CRITERIA,
    });
  };

  const updateCreateForm = (field, value) => {
    setCreateForm((prev) => ({
      ...prev,
      [field]: value,
    }));
    setCreateError("");
  };

  const updateCreateLocation = (index, key, value) => {
    setCreateForm((prev) => ({
      ...prev,
      locations: prev.locations.map((item, idx) =>
        idx === index ? { ...item, [key]: value } : item
      ),
    }));
  };

  const addCreateLocation = () => {
    setCreateForm((prev) => ({
      ...prev,
      locations: [...prev.locations, { name: "", hint: "" }],
    }));
  };

  const removeCreateLocation = (index) => {
    setCreateForm((prev) => ({
      ...prev,
      locations: prev.locations.filter((_, idx) => idx !== index),
    }));
  };

  const createCampaign = async () => {
    setCreateError("");

    const cleanedLocations = (createForm.locations || [])
      .map((item) => ({
        name: (item.name || "").trim(),
        hint: (item.hint || "").trim(),
      }))
      .filter((item) => item.name);
    console.log(createForm);

    if (!createForm.name.trim()) {
      setCreateError("Campaign name is required.");
      return;
    }

    if (!createForm.description.trim()) {
      setCreateError("Campaign description is required.");
      return;
    }

    if (cleanedLocations.length === 0) {
      setCreateError("At least one location is required.");
      return;
    }

    if (!createForm.jobDescription.trim() || !createForm.filterCriteria.trim()) {
      setCreateError("Job description and filter criteria are required.");
      return;
    }

    setCreateBusy(true);
    try {
      const baseFormData = new FormData();
      baseFormData.append("campaign_name", createForm.name.trim());
      baseFormData.append("location", cleanedLocations.map((item) => item.name).join(", "));
      baseFormData.append("position_name", createForm.name.trim());
      baseFormData.append("experience", "3-5");
      // No default tags here on purpose -- a hardcoded "NLP, LLM, Python" used to apply to every
      // new campaign regardless of role. Real tags come from a completed pipeline run's
      // AI-designed capabilities, or a recruiter can add their own via Edit Manually.
      baseFormData.append("desired_skills", "skills");
      baseFormData.append("target_profiles", "25");

      const created = await campaignApi.create(baseFormData);
      const campaignId = created.campaign_id;

      await campaignApi.setupPipeline(campaignId, {
        pipelineName: createForm.name.trim(),
        pipelineDescription: createForm.description.trim(),
        locations: cleanedLocations,
        jobDescription: createForm.jobDescription,
        filterCriteria: createForm.filterCriteria,
      });

      try {
        await campaignApi.saveTemplate({
          templateName: createForm.name.trim(),
          pipelineDescription: createForm.description.trim(),
          locations: cleanedLocations,
          jobDescription: createForm.jobDescription,
          filterCriteria: createForm.filterCriteria,
          sourceCampaignId: campaignId,
        });
        loadCampaignTemplates();
      } catch (templateError) {
        // Non-fatal — the campaign itself was created successfully either way.
        console.error("Failed to save campaign config for reuse:", templateError);
      }

      await Promise.all([loadCampaigns(), loadSkills()]);

      setDashboardCampaignId(String(campaignId));
      setPipelineCampaignId(String(campaignId));
      setPipelineMessage(
        'Campaign config saved. Nothing is searched yet — click "Run Pipeline" below to find candidates.'
      );
      setShowCreate(false);
      setView("pipeline");
    } catch (error) {
      setCreateError(error.message);
    } finally {
      setCreateBusy(false);
    }
  };

  const openEditCampaign = (campaign) => {
    setSelectedCampaign(null);
    setEditingCampaign(campaign);
    editFormHook.resetForm(campaignToEditForm(campaign));
  };

  const updateCampaign = async () => {
    try {
      await campaignApi.update(
        editingCampaign.id,
        campaignToFormData(
          editFormHook.campaignForm,
          editFormHook.selectedSkills
        )
      );

      setEditingCampaign(null);
      await Promise.all([loadCampaigns(), loadSkills()]);
    } catch (error) {
      editFormHook.setFormError(error.message);
    }
  };

  const updateCandidate = async (candidate) => {
    try {
      await candidateApi.update(candidate.id, candidateToFormData(candidate));
      setEditingCandidate(null);
      await loadCandidates();
    } catch (error) {
      setApiError(error.message);
    }
  };

  const refreshCandidates = async () => {
    setRefreshing(true);
    setApiError("");

    try {
      await candidateApi.refresh();
      await loadCandidates();
    } catch {
      setApiError("Could not refresh candidates.");
    } finally {
      setRefreshing(false);
    }
  };

  const runPipeline = async (runType = "full") => {
    if (!pipelineCampaignId) {
      setPipelineError("Select a campaign first.");
      return;
    }

    const parsedMax = Number.parseInt(pipelineMaxCandidates, 10);
    if (!Number.isFinite(parsedMax) || parsedMax < 1 || parsedMax > 100) {
      setPipelineError("Max candidates must be between 1 and 100.");
      return;
    }

    setPipelineError("");
    setPipelineMessage("");
    setPipelineBusy(true);
    try {
      const response = await campaignApi.runPipeline(
        pipelineCampaignId,
        runType,
        parsedMax
      );
      setPipelineMessage(
        `Pipeline started (run #${response.run_id}) with max_candidates=${parsedMax}. Please wait while it is running.`
      );
      const runs = await campaignApi.getPipelineRuns(pipelineCampaignId);
      setPipelineRuns(Array.isArray(runs) ? runs : []);
    } catch (error) {
      setPipelineError(error.message);
    } finally {
      setPipelineBusy(false);
    }
  };

  const exportSearchCsv = async (campaignId) => {
    if (!campaignId) {
      setApiError("Select a campaign first.");
      return;
    }

    const artifactStatus = getArtifactStatus(campaignId);
    if (!artifactStatus.searchResultsExists) {
      setApiError("No search results found for export yet.");
      return;
    }

    const exportKey = `${campaignId}:search`;

    setApiError("");
    setCampaignExportBusy((prev) => ({
      ...prev,
      [exportKey]: true,
    }));
    try {
      await campaignApi.exportSearchCsv(campaignId);
    } catch (error) {
      setApiError(error.message || "Search CSV export failed.");
    } finally {
      setCampaignExportBusy((prev) => ({
        ...prev,
        [exportKey]: false,
      }));
    }
  };

  const exportRankedCsv = async (campaignId) => {
    if (!campaignId) {
      setApiError("Select a campaign first.");
      return;
    }

    const artifactStatus = getArtifactStatus(campaignId);
    if (!artifactStatus.rankedResultsExists) {
      setApiError("No ranked results file found for export yet.");
      return;
    }

    const exportKey = `${campaignId}:ranked`;

    setApiError("");
    setCampaignExportBusy((prev) => ({
      ...prev,
      [exportKey]: true,
    }));
    try {
      await campaignApi.exportRankedCsv(campaignId);
    } catch (error) {
      setApiError(error.message || "Ranked CSV export failed.");
    } finally {
      setCampaignExportBusy((prev) => ({
        ...prev,
        [exportKey]: false,
      }));
    }
  };

  const renderCampaignExportActions = (campaign) => {
    const campaignId = campaign?.id;
    const artifactStatus = getArtifactStatus(campaignId);
    const searchBusy = Boolean(campaignExportBusy[`${campaignId}:search`]);
    const rankedBusy = Boolean(campaignExportBusy[`${campaignId}:ranked`]);

    return (
      <>
        <button
          type="button"
          onClick={() => exportSearchCsv(campaignId)}
          disabled={
            pipelineRunning ||
            artifactStatus.checking ||
            searchBusy ||
            !artifactStatus.searchResultsExists
          }
          className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 disabled:opacity-60"
        >
          {artifactStatus.checking
            ? "Checking search..."
            : searchBusy
            ? "Exporting search CSV..."
            : `Export Search CSV (${artifactStatus.searchResultsTotalCandidates})`}
        </button>
        <button
          type="button"
          onClick={() => exportRankedCsv(campaignId)}
          disabled={
            pipelineRunning ||
            artifactStatus.checking ||
            rankedBusy ||
            !artifactStatus.rankedResultsExists
          }
          className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 disabled:opacity-60"
        >
          {artifactStatus.checking
            ? "Checking ranked..."
            : rankedBusy
            ? "Exporting ranked CSV..."
            : "Export Ranked CSV"}
        </button>
      </>
    );
  };

  const changeDashboardCampaign = (campaign) => {
    setDashboardCampaignId(String(campaign.id));
    setDashboardPage(1);
  };

  const openCampaignExplorer = (campaign) => {
    setDashboardCampaignId(String(campaign.id));
    setDashboardPage(1);
    setView("dashboard");
  };

  const openDeleteCampaignModal = (campaign) => {
    setDeleteError("");
    setCampaignToDelete(campaign);
  };

  const closeDeleteCampaignModal = () => {
    if (deleteBusy) {
      return;
    }

    setDeleteError("");
    setCampaignToDelete(null);
  };

  const confirmDeleteCampaign = async () => {
    if (!campaignToDelete) {
      return;
    }

    const campaign = campaignToDelete;
    const campaignName = campaign?.campaignName || "this campaign";
    setApiError("");
    setDeleteError("");
    setDeleteBusy(true);

    try {
      await campaignApi.remove(campaign.id);

      if (String(dashboardCampaignId) === String(campaign.id)) {
        setDashboardCampaignId("");
        setDashboardCandidates([]);
      }

      if (String(pipelineCampaignId) === String(campaign.id)) {
        setPipelineCampaignId("");
        setPipelineRuns([]);
        setRankings([]);
      }

      if (selectedCampaign?.id === campaign.id) {
        setSelectedCampaign(null);
      }

      if (editingCampaign?.id === campaign.id) {
        setEditingCampaign(null);
      }

      await Promise.all([loadCampaigns(), loadCandidates(), loadSkills()]);
      setPipelineMessage(`Campaign ${campaignName} deleted successfully.`);
      setCampaignToDelete(null);
      setView("campaigns");
    } catch (error) {
      setDeleteError(error.message || "Could not delete campaign.");
      setApiError(error.message || "Could not delete campaign.");
    } finally {
      setDeleteBusy(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <div className="mx-auto flex gap-6 p-6">
        <Sidebar view={view} setView={setView} />

        <main className="flex-1">
          <AppHeader
            onCreateCampaign={openCreateCampaign}
            onRefreshCandidates={refreshCandidates}
            refreshing={refreshing}
            currentUser={currentUser}
            onSignOut={onSignOut}
          />

          <div className="mb-6 flex flex-wrap gap-2 rounded-lg bg-white p-3 shadow-sm ring-1 ring-slate-200 lg:hidden">
            {[
              ["dashboard", "Dashboard"],
              ["pipeline", "Pipeline"],
              ["campaigns", "Campaigns"],
              ["active", "Active"],
              ["past", "Past"],
              ["database", "Candidates"],
            ].map(([id, label]) => (
              <button
                key={id}
                type="button"
                onClick={() => setView(id)}
                className={`rounded-xl px-3 py-2 text-xs font-medium ${
                  view === id ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-700"
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          {loading && (
            <Card className="mb-6 p-5">
              <p className="text-sm text-slate-500">Loading data from backend...</p>
            </Card>
          )}

          {apiError && (
            <div className="mb-6 rounded-xl border border-red-200 bg-red-50 p-5 text-sm text-red-700">
              {apiError}
            </div>
          )}

          {showCreate && (
            <PipelineCampaignCreateForm
              form={createForm}
              onChange={updateCreateForm}
              onLocationChange={updateCreateLocation}
              onAddLocation={addCreateLocation}
              onRemoveLocation={removeCreateLocation}
              onSave={createCampaign}
              onClose={() => setShowCreate(false)}
              error={createError}
              saving={createBusy}
              templates={campaignTemplates}
              onUseTemplate={applyCampaignTemplate}
            />
          )}

          {view === "dashboard" && (
            <section className="space-y-6">
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                <KPI icon={Icons.Briefcase} label="Total Campaigns" value={campaigns.length} sub="Active, past and draft" />
                <KPI icon={Icons.Clock} label="Active Campaigns" value={activeCampaigns.length} sub="Currently sourcing" />
                <KPI icon={Icons.Users} label="Candidates" value={candidates.length} sub="Database-wide" />
                <KPI
                  icon={Icons.Check}
                  label="Shortlisted"
                  value={candidates.filter((candidate) => candidate.status === "Shortlisted").length}
                  sub="Ready for review"
                />
              </div>

              <div className="grid gap-6 xl:grid-cols-2">
                <CampaignPanel
                  title="Active Campaigns"
                  campaigns={activeCampaigns}
                  onOpenCampaign={changeDashboardCampaign}
                  onEditCampaign={openEditCampaign}
                  onDeleteCampaign={openDeleteCampaignModal}
                  renderExtraActions={renderCampaignExportActions}
                />

                <div className="space-y-4">
                  {dashboardConfigVersions.length > 1 && (
                    <Card className="p-4">
                      <label className="block text-sm">
                        <span className="mb-1 block font-medium text-slate-700">
                          Config version
                        </span>
                        <select
                          value={dashboardVersionId}
                          onChange={(event) => setDashboardVersionId(event.target.value)}
                          className="w-full rounded-lg border border-slate-300 px-3 py-2.5 outline-none focus:border-indigo-600"
                        >
                          {dashboardConfigVersions.map((version) => (
                            <option key={version.id} value={version.id}>
                              v{version.versionNumber}
                              {version.isCurrent ? " (current)" : ""} — {version.importedCandidates}{" "}
                              candidates · {version.createdAt}
                            </option>
                          ))}
                        </select>
                      </label>
                      <p className="mt-2 text-xs text-slate-500">
                        Each config version keeps the candidate list its own run produced, so
                        earlier results stay available after you edit and re-run a campaign.
                      </p>
                    </Card>
                  )}

                  {dashboardLoadingCandidates ? (
                    <Card className="p-5">
                      <p className="text-sm text-slate-500">Loading candidates...</p>
                    </Card>
                  ) : (
                    <CandidatePanel
                      title={`Candidates for ${selectedDashboardCampaign?.campaignName || "Selected Campaign"}`}
                      subtitle={
                        selectedDashboardVersion
                          ? `Config v${selectedDashboardVersion.versionNumber}${
                              selectedDashboardVersion.isCurrent ? " (current)" : ""
                            } — ranked candidates from that run`
                          : "Campaign-scoped ranked candidates"
                      }
                      candidates={dashboardCandidates}
                      onOpenCandidate={setSelectedCandidate}
                      onEditCandidate={setEditingCandidate}
                      page={dashboardPage}
                      totalPages={dashboardTotalPages}
                      onPageChange={setDashboardPage}
                      headerAction={
                        selectedDashboardCampaign && dashboardCandidates.length > 0 ? (
                          <a
                            href={`${API_BASE_URL}/campaigns/${selectedDashboardCampaign.id}/export/excel?token=${encodeURIComponent(
                              localStorage.getItem("hr_auth_token") || ""
                            )}${dashboardVersionId ? `&config_version_id=${dashboardVersionId}` : ""}`}
                            className="rounded-xl border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                          >
                            Download Excel
                          </a>
                        ) : null
                      }
                    />
                  )}
                </div>
              </div>
            </section>
          )}

          {view === "pipeline" && (
            <section className="space-y-6">
              <Card className="p-5">
                <div className="mb-4">
                  <h3 className="text-base font-semibold text-slate-900">Pipeline Run Control</h3>
                  <p className="text-sm text-slate-500">
                    Campaign inputs are saved in create form. Run and monitor pipeline from here.
                  </p>
                </div>

                <label className="block text-sm">
                  <span className="mb-1 block font-medium text-slate-700">Campaign</span>
                  <select
                    value={pipelineCampaignId}
                    onChange={(event) => setPipelineCampaignId(event.target.value)}
                    className="w-full rounded-lg border border-slate-300 px-3 py-2.5 outline-none focus:border-indigo-600"
                  >
                    <option value="">Select campaign</option>
                    {campaigns.map((campaign) => (
                      <option key={campaign.id} value={campaign.id}>
                        {campaign.campaignCode} - {campaign.campaignName}
                      </option>
                    ))}
                  </select>
                </label>

                {pipelineCampaignId && (
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      onClick={openConfigEdit}
                      disabled={pipelineRunning || !currentConfigVersion}
                      className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                    >
                      Edit Config{currentConfigVersion ? ` (v${currentConfigVersion.versionNumber})` : ""}
                    </button>
                    {pipelineRunning && (
                      <span className="text-xs text-amber-700">
                        Config is locked while a pipeline run is in progress.
                      </span>
                    )}
                    {!pipelineRunning &&
                      viewedConfigVersion &&
                      !viewedConfigVersion.isCurrent && (
                        <span className="text-xs text-slate-500">
                          Viewing v{viewedConfigVersion.versionNumber}'s results. Runs and edits
                          always apply to the current version.
                        </span>
                      )}
                  </div>
                )}

                {pipelineCampaignId && !pipelineRunning && pipelineRuns.length === 0 && (
                  <div className="mt-4 flex items-start gap-2 rounded-lg border-2 border-amber-400 bg-amber-50 px-4 py-3 text-sm font-medium text-amber-900">
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                    <span>
                      This campaign hasn't been searched yet — saving the config does not start
                      the search. Click <strong>"Run Pipeline"</strong> below to find candidates.
                    </span>
                  </div>
                )}

                {pipelineRunning && (
                  <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-4">
                    <div className="flex items-start gap-3">
                      <div className="mt-0.5 h-5 w-5 shrink-0 animate-spin rounded-full border-2 border-amber-700 border-t-transparent" />
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-semibold text-amber-900">
                          {pipelineProgress?.label
                            ? `${pipelineProgress.label}${
                                pipelineProgress.detail ? ` (${pipelineProgress.detail})` : ""
                              }`
                            : "Pipeline is running"}
                          {pipelineStepLabel && (
                            <span className="ml-2 font-normal text-amber-700">
                              {pipelineStepLabel}
                            </span>
                          )}
                        </p>
                        <p className="text-xs text-amber-800">
                          This can take a few minutes. Timeline updates automatically while processing.
                        </p>

                        {pipelinePhaseSteps.length > 0 && (
                          <div className="mt-3 flex flex-wrap gap-1.5">
                            {pipelinePhaseSteps.map((step) => (
                              <span
                                key={step.phase}
                                className={`rounded-full px-2 py-0.5 text-xs ${
                                  step.state === "active"
                                    ? "bg-amber-200 font-medium text-amber-900"
                                    : step.state === "done"
                                      ? "bg-emerald-100 text-emerald-800"
                                      : "bg-white text-slate-500 ring-1 ring-slate-200"
                                }`}
                              >
                                {step.state === "done" ? "✓ " : ""}
                                {step.label}
                              </span>
                            ))}
                          </div>
                        )}

                        {pipelineProgressPercent !== null && (
                          <div className="mt-3">
                            <div className="h-1.5 w-full overflow-hidden rounded-full bg-amber-200">
                              <div
                                className="h-full rounded-full bg-amber-600 transition-all"
                                style={{ width: `${pipelineProgressPercent}%` }}
                              />
                            </div>
                            <p className="mt-1 text-xs text-amber-800">
                              {pipelineProgress.current} of {pipelineProgress.total} processed
                            </p>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                )}

                {pipelineError && (
                  <div className="mt-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                    {pipelineError}
                  </div>
                )}

                {pipelineMessage && (
                  <div className="mt-4 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
                    {pipelineMessage}
                  </div>
                )}

                <label className="mt-4 block text-sm">
                  <span className="mb-1 block font-medium text-slate-700">Max candidates for filter + rank (1-100)</span>
                  <input
                    type="number"
                    min={1}
                    max={100}
                    value={pipelineMaxCandidates}
                    placeholder="100"
                    onChange={(event) => setPipelineMaxCandidates(event.target.value)}
                    className="w-full rounded-lg border border-slate-300 px-3 py-2.5 outline-none focus:border-indigo-600"
                  />
                  <p className="mt-1 text-xs text-slate-500">
                    This value is for the number of candidates to be shortlisted and ranked by the AI pipeline. The default is 100, but you can reduce it for faster runs.
                  </p>
                </label>

                <div className="mt-4 flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => runPipeline("full")}
                    disabled={pipelineBusy || !pipelineCampaignId || pipelineRunning}
                    className={`rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-60 ${
                      pipelineCampaignId && !pipelineRunning && pipelineRuns.length === 0
                        ? "ring-4 ring-indigo-300 animate-pulse"
                        : ""
                    }`}
                  >
                    {pipelineBusy ? "Working..." : "Run Campaign"}
                  </button>

                  <button
                    type="button"
                    onClick={() => runPipeline("rank")}
                    disabled={pipelineBusy || !pipelineCampaignId || pipelineRunning}
                    className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 disabled:opacity-60"
                  >
                    Run Rank Only
                  </button>
                </div>
              </Card>

              {usageSummary?.exists && (
                <Card className="p-5">
                  <h3 className="text-base font-semibold text-slate-900">LLM Usage (Most Recent Run)</h3>
                  <p className="mb-4 text-sm text-slate-500">
                    Cost and token usage for the last pipeline run of this campaign.
                  </p>
                  <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                    <div className="rounded-lg bg-slate-50 p-3">
                      <p className="text-xs text-slate-500">Cost</p>
                      <p className="text-lg font-semibold text-slate-900">
                        ${(usageSummary.cost_usd || 0).toFixed(2)}
                      </p>
                    </div>
                    <div className="rounded-lg bg-slate-50 p-3">
                      <p className="text-xs text-slate-500">Model Calls</p>
                      <p className="text-lg font-semibold text-slate-900">{usageSummary.calls || 0}</p>
                    </div>
                    <div className="rounded-lg bg-slate-50 p-3">
                      <p className="text-xs text-slate-500">Tokens (in/out)</p>
                      <p className="text-lg font-semibold text-slate-900">
                        {(usageSummary.input_tokens || 0).toLocaleString()} / {(usageSummary.output_tokens || 0).toLocaleString()}
                      </p>
                    </div>
                    <div className="rounded-lg bg-slate-50 p-3">
                      <p className="text-xs text-slate-500">Errors</p>
                      <p className="text-lg font-semibold text-slate-900">{usageSummary.errors || 0}</p>
                    </div>
                  </div>
                </Card>
              )}

              <PipelineConfigVersionList
                versions={configVersions}
                loading={configVersionsLoading}
                selectedVersionId={pipelineVersionId}
                onSelectVersion={(versionId) => setPipelineVersionId(String(versionId))}
              />

              <Card className="p-5">
                <h3 className="text-base font-semibold text-slate-900">Run Timeline</h3>
                <p className="mb-4 text-sm text-slate-500">Latest pipeline operations for selected campaign.</p>
                <div className="space-y-2">
                  {pipelineRuns.map((run) => (
                    <div key={run.id} className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
                      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
                        <p className="font-medium text-slate-800">#{run.id} {run.run_type} - {run.status}</p>
                        <p className="text-slate-500">{run.started_at}</p>
                      </div>
                      <p className="mt-1 text-xs text-slate-500">Command: {run.command || "-"}</p>
                      {run.accepted_candidates !== null && run.accepted_candidates !== undefined && (
                        <p className="mt-1 text-xs text-slate-600">
                          Accepted after AI review: {run.accepted_candidates}
                        </p>
                      )}
                      {run.ranked_candidates !== null && run.ranked_candidates !== undefined && (
                        <p className="mt-1 text-xs text-slate-600">
                          Ranked candidates: {run.ranked_candidates}
                        </p>
                      )}
                      {run.error_message && <p className="mt-1 text-xs text-red-600">Error: {run.error_message}</p>}
                    </div>
                  ))}
                  {pipelineRuns.length === 0 && <p className="text-sm text-slate-500">No runs yet.</p>}
                </div>
              </Card>
            </section>
          )}

          {view === "campaigns" && (
            <CampaignPanel
              title="All Campaigns"
              campaigns={campaigns}
              full
              onOpenCampaign={openCampaignExplorer}
              onViewDetails={setSelectedCampaign}
              onEditCampaign={openEditCampaign}
              onDeleteCampaign={openDeleteCampaignModal}
              renderExtraActions={renderCampaignExportActions}
            />
          )}

          {view === "active" && (
            <CampaignPanel
              title="Active Campaigns"
              campaigns={activeCampaigns}
              full
              onOpenCampaign={openCampaignExplorer}
              onViewDetails={setSelectedCampaign}
              onEditCampaign={openEditCampaign}
              onDeleteCampaign={openDeleteCampaignModal}
              renderExtraActions={renderCampaignExportActions}
            />
          )}

          {view === "past" && (
            <CampaignPanel
              title="Past Campaigns"
              campaigns={pastCampaigns}
              full
              onOpenCampaign={openCampaignExplorer}
              onViewDetails={setSelectedCampaign}
              onEditCampaign={openEditCampaign}
              onDeleteCampaign={openDeleteCampaignModal}
              renderExtraActions={renderCampaignExportActions}
            />
          )}

          {view === "database" && (
            <section className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
              <div className="mb-5 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                <div>
                  <h3 className="text-base font-semibold text-slate-900">All Candidates Database</h3>
                  <p className="text-sm text-slate-500">Search, filter, and review candidate profiles.</p>
                </div>

                <div className="flex flex-col gap-2 sm:flex-row">
                  <input
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder="Search candidates..."
                    className="w-full rounded-lg border border-slate-300 py-2.5 px-4 text-sm outline-none focus:border-indigo-600 sm:w-64"
                  />

                  <select
                    value={statusFilter}
                    onChange={(event) => setStatusFilter(event.target.value)}
                    className="rounded-lg border border-slate-300 py-2.5 px-4 text-sm outline-none focus:border-indigo-600"
                  >
                    {["All", "New", "Reviewed", "Contacted", "Shortlisted", "Rejected"].map((status) => (
                      <option key={status}>{status}</option>
                    ))}
                  </select>
                </div>
              </div>

              <CandidatePanel
                candidates={filteredCandidates}
                full
                onOpenCandidate={setSelectedCandidate}
                onEditCandidate={setEditingCandidate}
              />
            </section>
          )}
        </main>
      </div>

      <CampaignDetailModal
        campaign={selectedCampaign}
        onClose={() => setSelectedCampaign(null)}
        onEdit={openEditCampaign}
      />

      <CampaignEditModal
        campaign={editingCampaign}
        formHook={editFormHook}
        skillSuggestions={skillSuggestions}
        onClose={() => setEditingCampaign(null)}
        onSave={updateCampaign}
      />

      <CampaignDeleteModal
        campaign={campaignToDelete}
        deleting={deleteBusy}
        error={deleteError}
        onCancel={closeDeleteCampaignModal}
        onConfirm={confirmDeleteCampaign}
      />

      <CandidateDetailModal
        candidate={selectedCandidate}
        scoringExplainer={scoringExplainer}
        onClose={() => setSelectedCandidate(null)}
        onEdit={(candidate) => {
          setSelectedCandidate(null);
          setEditingCandidate(candidate);
        }}
      />

      <CandidateEditModal
        candidate={editingCandidate}
        onClose={() => setEditingCandidate(null)}
        onSave={updateCandidate}
      />

      <PipelineConfigEditModal
        initialConfig={configEditOpen ? currentConfigVersion : null}
        willCreateNewVersion={Boolean(currentConfigVersion?.hasResults)}
        onClose={closeConfigEdit}
        onSave={saveConfigEdit}
        saving={configEditBusy}
        error={configEditError}
      />
    </div>
  );
}
