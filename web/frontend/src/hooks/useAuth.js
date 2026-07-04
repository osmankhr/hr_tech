import { useEffect, useState } from "react";
import { authApi } from "../api/authApi";

export function useAuth() {
  const [user, setUser] = useState(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [authError, setAuthError] = useState("");

  const signIn = async (email, password) => {
    setAuthError("");

    try {
      const result = await authApi.signIn(email, password);
      localStorage.setItem("hr_auth_token", result.token);
      setUser(result.user);
      return true;
    } catch (error) {
      setAuthError(error.message);
      return false;
    }
  };

  const signOut = async () => {
    try {
      await authApi.signOut();
    } catch {
      // Ignore signout errors.
    }

    localStorage.removeItem("hr_auth_token");
    setUser(null);
  };

  const loadCurrentUser = async () => {
    const token = localStorage.getItem("hr_auth_token");

    if (!token) {
      setAuthLoading(false);
      return;
    }

    try {
      const currentUser = await authApi.me();
      setUser(currentUser);
    } catch {
      localStorage.removeItem("hr_auth_token");
      setUser(null);
    } finally {
      setAuthLoading(false);
    }
  };

  useEffect(() => {
    loadCurrentUser();
  }, []);

  return {
    user,
    authLoading,
    authError,
    signIn,
    signOut,
  };
}