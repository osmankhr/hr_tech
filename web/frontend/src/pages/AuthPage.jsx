import { useState } from "react";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { InputField } from "../components/ui/InputField";

export default function AuthPage({ onSignIn, authError }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const submit = async () => {
    await onSignIn(email, password);
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 p-6">
      <Card className="w-full max-w-md p-6">
        <div className="mb-6 text-center">
          <div className="mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-2xl bg-blue-600 text-2xl text-white">
            👥
          </div>
          <h1 className="text-2xl font-bold">HR Candidate Search</h1>
          <p className="mt-1 text-sm text-slate-500">
            Sign in to access campaign and candidate data.
          </p>
        </div>

        <div className="space-y-4">
          <InputField
            label="Email"
            value={email}
            onChange={setEmail}
            placeholder="admin@hr.local"
          />

          <InputField
            type="password"
            label="Password"
            value={password}
            onChange={setPassword}
            placeholder="Password"
          />

          {authError && (
            <div className="rounded-2xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">
              {authError}
            </div>
          )}

          <Button className="w-full" onClick={submit}>
            Sign In
          </Button>

          <p className="text-center text-xs text-slate-500">
            Accounts are created by an administrator. Contact your admin for access.
          </p>
        </div>
      </Card>
    </div>
  );
}