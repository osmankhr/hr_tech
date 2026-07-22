import { useEffect, useMemo, useRef, useState } from "react";
import { campaignApi } from "../api/campaignApi";
import { candidateApi } from "../api/candidateApi";
import { AppHeader } from "../components/layout/AppHeader";
import { Sidebar } from "../components/layout/Sidebar";
import { Card } from "../components/ui/Card";
import { Icons } from "../components/ui/Icon";
import { KPI } from "../components/ui/KPI";
import { API_BASE_URL } from "../config/api";
import { EMPTY_CAMPAIGN_FORM } from "../constants/defaults";
import { CampaignDetailModal } from "../features/campaigns/CampaignDetailModal";
import { CampaignDeleteModal } from "../features/campaigns/CampaignDeleteModal";
import { CampaignEditModal } from "../features/campaigns/CampaignEditModal";
import { CampaignPanel } from "../features/campaigns/CampaignPanel";
import { PipelineCampaignCreateForm } from "../features/campaigns/PipelineCampaignCreateForm";
import { CandidateDetailModal } from "../features/candidates/CandidateDetailModal";
import { CandidateEditModal } from "../features/candidates/CandidateEditModal";
import { CandidatePanel } from "../features/candidates/CandidatePanel";
import { useCampaignForm } from "../hooks/useCampaignForm";
import { useHrData } from "../hooks/useHrData";
import {
  campaignToEditForm,
  campaignToFormData,
  mapCampaignFromApi,
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

  const [selectedCampaign, setSelectedCampaign] = useState(null);
  const [editingCampaign, setEditingCampaign] = useState(null);
  const [campaignToDelete, setCampaignToDelete] = useState(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const [selectedCandidate, setSelectedCandidate] = useState(null);
  const [editingCandidate, setEditingCandidate] = useState(null);

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
  const [campaignArtifactStatus, setCampaignArtifactStatus] = useState({});
  const [campaignExportBusy, setCampaignExportBusy] = useState({});
  const autoImportedRunIdsRef = useRef(new Set());

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
          10
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
  }, [dashboardCampaignId, dashboardPage, setApiError]);

  useEffect(() => {
    if (!pipelineCampaignId) {
      return;
    }

    const load = async () => {
      try {
        const [runs, rankingItems] = await Promise.all([
          campaignApi.getPipelineRuns(pipelineCampaignId),
          campaignApi.getRankings(pipelineCampaignId),
        ]);
        setPipelineRuns(Array.isArray(runs) ? runs : []);
        setRankings(Array.isArray(rankingItems) ? rankingItems : []);
      } catch (error) {
        setPipelineError(error.message || "Could not load pipeline state.");
      }
    };

    load();
  }, [pipelineCampaignId]);

  useEffect(() => {
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
          await campaignApi.importRankedResults(pipelineCampaignId, "");
        } catch (error) {
          setPipelineError(
            error?.message ||
              "Pipeline finished but ranked results import failed. You can import manually."
          );
        }
      }

      if (run.status === "Completed") {
        campaignApi
          .getRankings(pipelineCampaignId)
          .then((items) => setRankings(Array.isArray(items) ? items : []))
          .catch(() => {});

        loadCandidates().catch(() => {});
        loadCampaigns().catch(() => {});
        refreshArtifactStatuses([pipelineCampaignId]).catch(() => {});
      }
    };

    eventSource.addEventListener("pipeline_run_update", async (event) => {
      try {
        const payload = JSON.parse(event.data || "{}");
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
      baseFormData.append("desired_skills", "NLP, LLM, Python");
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

      await Promise.all([loadCampaigns(), loadSkills()]);

      setDashboardCampaignId(String(campaignId));
      setPipelineCampaignId(String(campaignId));
      setPipelineMessage("Campaign config saved. You can now run the pipeline.");
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
          className="rounded-2xl border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 disabled:opacity-60"
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
          className="rounded-2xl border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 disabled:opacity-60"
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

          <div className="mb-6 flex flex-wrap gap-2 rounded-2xl bg-white p-3 shadow-sm ring-1 ring-slate-200 lg:hidden">
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
            <div className="mb-6 rounded-3xl border border-red-200 bg-red-50 p-5 text-sm text-red-700">
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

                <div>
                  {dashboardLoadingCandidates ? (
                    <Card className="p-5">
                      <p className="text-sm text-slate-500">Loading candidates...</p>
                    </Card>
                  ) : (
                    <CandidatePanel
                      title={`Candidates for ${selectedDashboardCampaign?.campaignName || "Selected Campaign"}`}
                      subtitle="Campaign-scoped ranked candidates"
                      candidates={dashboardCandidates}
                      onOpenCandidate={setSelectedCandidate}
                      onEditCandidate={setEditingCandidate}
                      page={dashboardPage}
                      totalPages={dashboardTotalPages}
                      onPageChange={setDashboardPage}
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
                  <h3 className="text-lg font-semibold">Pipeline Run Control</h3>
                  <p className="text-sm text-slate-500">
                    Campaign inputs are saved in create form. Run and monitor pipeline from here.
                  </p>
                </div>

                <label className="block text-sm">
                  <span className="mb-1 block font-medium text-slate-700">Campaign</span>
                  <select
                    value={pipelineCampaignId}
                    onChange={(event) => setPipelineCampaignId(event.target.value)}
                    className="w-full rounded-2xl border border-slate-300 px-3 py-2.5 outline-none focus:border-orange-500"
                  >
                    <option value="">Select campaign</option>
                    {campaigns.map((campaign) => (
                      <option key={campaign.id} value={campaign.id}>
                        {campaign.campaignCode} - {campaign.campaignName}
                      </option>
                    ))}
                  </select>
                </label>

                {pipelineRunning && (
                  <div className="mt-4 rounded-2xl border border-amber-200 bg-gradient-to-r from-amber-50 to-orange-50 px-4 py-4">
                    <div className="flex items-center gap-3">
                      <div className="h-5 w-5 animate-spin rounded-full border-2 border-amber-700 border-t-transparent" />
                      <div>
                        <p className="text-sm font-semibold text-amber-900">Pipeline is running</p>
                        <p className="text-xs text-amber-800">
                          This can take a few minutes. Timeline updates automatically while processing.
                        </p>
                      </div>
                    </div>
                  </div>
                )}

                {pipelineError && (
                  <div className="mt-4 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                    {pipelineError}
                  </div>
                )}

                {pipelineMessage && (
                  <div className="mt-4 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
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
                    className="w-full rounded-2xl border border-slate-300 px-3 py-2.5 outline-none focus:border-orange-500"
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
                    className="rounded-2xl bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
                  >
                    {pipelineBusy ? "Working..." : "Run Campaign"}
                  </button>

                  <button
                    type="button"
                    onClick={() => runPipeline("rank")}
                    disabled={pipelineBusy || !pipelineCampaignId || pipelineRunning}
                    className="rounded-2xl border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 disabled:opacity-60"
                  >
                    Run Rank Only
                  </button>
                </div>
              </Card>

              <Card className="p-5">
                <h3 className="text-lg font-semibold">Run Timeline</h3>
                <p className="mb-4 text-sm text-slate-500">Latest pipeline operations for selected campaign.</p>
                <div className="space-y-2">
                  {pipelineRuns.map((run) => (
                    <div key={run.id} className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
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
            <section className="rounded-3xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
              <div className="mb-5 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                <div>
                  <h3 className="text-lg font-semibold">All Candidates Database</h3>
                  <p className="text-sm text-slate-500">Search, filter, and review candidate profiles.</p>
                </div>

                <div className="flex flex-col gap-2 sm:flex-row">
                  <input
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder="Search candidates..."
                    className="w-full rounded-2xl border border-slate-300 py-2.5 px-4 text-sm outline-none focus:border-orange-500 sm:w-64"
                  />

                  <select
                    value={statusFilter}
                    onChange={(event) => setStatusFilter(event.target.value)}
                    className="rounded-2xl border border-slate-300 py-2.5 px-4 text-sm outline-none focus:border-orange-500"
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
    </div>
  );
}
