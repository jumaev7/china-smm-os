"use client";

import { FormEvent, Suspense, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, ShieldCheck, Zap } from "lucide-react";
import toast from "react-hot-toast";
import { authApi } from "@/lib/api";
import { useAuth } from "@/lib/auth-store";
import { usePostAuthNavigation } from "@/lib/usePostAuthNavigation";

const POST_LOGIN_PATH = "/dashboard";

function LoginForm() {
  const router = useRouter();
  const { login, isAuthenticated, loading } = useAuth();

  const [email, setEmail] = useState("demo@factory.local");
  const [password, setPassword] = useState("demo1234");
  const [submitting, setSubmitting] = useState(false);
  const [creatingDemo, setCreatingDemo] = useState(false);

  usePostAuthNavigation(isAuthenticated, loading, POST_LOGIN_PATH);

  if (!loading && isAuthenticated) {
    return (
      <div data-login-overlay className="flex min-h-screen items-center justify-center text-gray-500">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" />
        Redirecting…
      </div>
    );
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      await login(email.trim(), password);
      toast.success("Signed in");
      router.replace(POST_LOGIN_PATH);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Login failed");
    } finally {
      setSubmitting(false);
    }
  }

  async function onCreateDemo() {
    setCreatingDemo(true);
    try {
      const { data } = await authApi.createDemoUser();
      toast.success(data.message);
      setEmail(data.email);
      setPassword(data.password);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to create demo user");
    } finally {
      setCreatingDemo(false);
    }
  }

  return (
    <div data-login-overlay className="min-h-screen bg-gray-50 flex items-center justify-center p-4">
      <div className="w-full max-w-md rounded-2xl border border-gray-200 bg-white p-8 shadow-sm">
        <div className="mb-6 flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-600">
            <Zap size={18} className="text-white" />
          </div>
          <div>
            <h1 className="text-xl font-semibold text-gray-900">Tenant Sign In</h1>
            <p className="text-sm text-gray-500">China SMM OS — factory tenant portal</p>
          </div>
        </div>

        <form onSubmit={onSubmit} autoComplete="on" className="space-y-4">
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700" htmlFor="login-email">
              Email
            </label>
            <input
              id="login-email"
              name="email"
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700" htmlFor="login-password">
              Password
            </label>
            <input
              id="login-password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
            />
          </div>
          <button
            type="submit"
            disabled={submitting}
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-brand-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60"
          >
            {submitting ? <Loader2 size={16} className="animate-spin" /> : null}
            Sign in
          </button>
        </form>

        <div className="mt-6 border-t border-gray-100 pt-5">
          <button
            type="button"
            onClick={onCreateDemo}
            disabled={creatingDemo}
            className="flex w-full items-center justify-center gap-2 rounded-lg border border-dashed border-gray-300 px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-60"
          >
            {creatingDemo ? <Loader2 size={16} className="animate-spin" /> : <ShieldCheck size={16} />}
            Create demo user (development)
          </button>
          <p className="mt-2 text-center text-xs text-gray-400">
            Demo: demo@factory.local / demo1234
          </p>
        </div>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <div data-login-overlay className="flex min-h-screen items-center justify-center text-gray-500">
          <Loader2 className="h-5 w-5 animate-spin" />
        </div>
      }
    >
      <LoginForm />
    </Suspense>
  );
}
