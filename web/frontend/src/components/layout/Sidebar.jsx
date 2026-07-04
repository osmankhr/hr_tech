import { Icons } from "../ui/Icon";

export function Sidebar({ view, setView }) {
  const navButton = (id, label, Icon) => (
    <button
      onClick={() => setView(id)}
      className={`flex w-full items-center gap-3 rounded-2xl px-4 py-3 text-left text-sm font-medium transition ${
        view === id
          ? "bg-slate-900 text-white shadow-sm"
          : "text-slate-600 hover:bg-slate-100"
      }`}
    >
      <Icon className="h-5 w-5" />
      {label}
    </button>
  );

  return (
    <aside className="hidden w-72 shrink-0 rounded-3xl bg-white p-5 shadow-sm ring-1 ring-slate-200 lg:block">
      <div className="mb-8 flex items-center gap-3">
        <div className="rounded-2xl bg-orange-600 p-3 text-white">
          <Icons.Users className="h-6 w-6" />
        </div>

        <div>
          <h1 className="text-lg font-bold">HR Search</h1>
          <p className="text-xs text-slate-500">Candidate campaign tool</p>
        </div>
      </div>

      <nav className="space-y-2">
        {navButton("dashboard", "Dashboard", Icons.Chart)}
        {navButton("pipeline", "Pipeline Integration", Icons.Filter)}
        {navButton("campaigns", "List All Campaigns", Icons.Briefcase)}
        {navButton("active", "Active Campaigns", Icons.Clock)}
        {navButton("past", "Past Campaigns", Icons.Archive)}
        {navButton("database", "All Candidates Database", Icons.Database)}
      </nav>
    </aside>
  );
}