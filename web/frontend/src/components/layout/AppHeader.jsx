import { Button } from "../ui/Button";
import { Icons } from "../ui/Icon";

export function AppHeader({
  onCreateCampaign,
  onRefreshCandidates,
  refreshing,
  currentUser,
  onSignOut,
}) {
  return (
    <header className="mb-6 flex flex-col gap-4 rounded-3xl bg-white p-5 shadow-sm ring-1 ring-slate-200 md:flex-row md:items-center md:justify-between">
      <div>
        <p className="text-sm font-medium text-blue-600">
          Recruitment Intelligence
        </p>
        <h2 className="text-2xl font-bold">Candidate Search Workspace</h2>
        <p className="mt-1 text-sm text-slate-500">
          Signed in as {currentUser?.full_name} ({currentUser?.role})
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        <Button onClick={onCreateCampaign}>
          <Icons.Plus className="h-4 w-4" />
          Create New Campaign
        </Button>

        <Button
          onClick={onRefreshCandidates}
          variant="outline"
          disabled={refreshing}
        >
          <Icons.Refresh
            className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`}
          />
          {refreshing ? "Refreshing..." : "Refresh Candidates"}
        </Button>

        <Button onClick={onSignOut} variant="outline">
          Sign Out
        </Button>
      </div>
    </header>
  );
}