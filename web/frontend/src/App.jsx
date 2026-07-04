import AuthPage from "./pages/AuthPage";
import HRCandidateSearchPage from "./pages/HRCandidateSearchPage";
import { useAuth } from "./hooks/useAuth";

function App() {
  const { user, authLoading, authError, signIn, signOut } = useAuth();

  if (authLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50 text-sm text-slate-500">
        Checking authentication...
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

  return <HRCandidateSearchPage currentUser={user} onSignOut={signOut} />;
}

export default App;