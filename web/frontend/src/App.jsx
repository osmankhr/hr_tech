import AuthPage from "./pages/AuthPage";
import HRCandidateSearchPage from "./pages/HRCandidateSearchPage";
import { useAuth } from "./hooks/useAuth";
import { ErrorBoundary } from "./components/ui/ErrorBoundary";

function App() {
  const { user, authLoading, authError, signIn, signOut } = useAuth();

  if (authLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50 text-sm text-slate-500">
        Signing in…
      </div>
    );
  }

  if (!user) {
    return (
      <AuthPage
        onSignIn={signIn}
        authError={authError}
      />
    );
  }

  return (
    <ErrorBoundary title="Application Error">
      <HRCandidateSearchPage currentUser={user} onSignOut={signOut} />
    </ErrorBoundary>
  );
}

export default App;