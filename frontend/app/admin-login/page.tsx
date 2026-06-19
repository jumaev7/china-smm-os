"use client";

import { FormEvent, Suspense, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Shield } from "lucide-react";
import toast from "react-hot-toast";
import { adminAuthApi } from "@/lib/api";
import { useAdminAuth } from "@/lib/admin-auth-store";
import { usePostAuthNavigation } from "@/lib/usePostAuthNavigation";

const POST_LOGIN_PATH = "/dashboard";

function AdminLoginForm() {
  const router = useRouter();
  const { login, isAuthenticated, loading } = useAdminAuth();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [bootstrapping, setBootstrapping] = useState(false);

  usePostAuthNavigation(isAuthenticated, loading, POST_LOGIN_PATH);

  if (!loading && isAuthenticated) {
    return (
      <div className="flex min-h-screen items-center justify-center text-gray-500">
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
      toast.success("Admin signed in");
      router.replace(POST_LOGIN_PATH);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Admin login failed");
    } finally {
      setSubmitting(false);
    }
  }

  async function onBootstrap() {
    setBootstrapping(true);
    try {
      const { data } = await adminAuthApi.bootstrap();
      toast.success(data.message);
      setEmail(data.email);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Bootstrap unavailable — set ADMIN_BOOTSTRAP_* in backend .env");
    } finally {
      setBootstrapping(false);
    }
  }

  return (
    <div className="min-h-screen bg-slate-950 flex items-center justify-center p-4">
      <div className="w-full max-w-md rounded-2xl border border-slate-700 bg-slate-900 p-8 shadow-xl">
        <div className="mb-6 flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-600">
            <Shield size={18} className="text-white" />
          </div>
          <div>
            <h1 className="text-xl font-semibold text-white">Platform Admin</h1>
            <p className="text-sm text-slate-400">China SMM OS — admin console</p>
          </div>
        </div>

        <form onSubmit={onSubmit} autoComplete="on" className="space-y-4">
          <div>
            <label className="mb-1 block text-sm font-medium text-slate-300" htmlFor="admin-login-email">
              Email
            </label>
            <input
              id="admin-login-email"
              name="email"
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-lg border border-slate-600 bg-slate-800 px-3 py-2 text-sm text-white focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-slate-300" htmlFor="admin-login-password">
              Password
            </label>
            <input
              id="admin-login-password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-lg border border-slate-600 bg-slate-800 px-3 py-2 text-sm text-white focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
          </div>
          <button
            type="submit"
            disabled={submitting}
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-60"
          >
            {submitting ? <Loader2 size={16} className="animate-spin" /> : null}
            Sign in
          </button>
        </form>

        <div className="mt-6 border-t border-slate-700 pt-5">
          <button
            type="button"
            onClick={onBootstrap}
            disabled={bootstrapping}
            className="flex w-full items-center justify-center gap-2 rounded-lg border border-dashed border-slate-600 px-4 py-2.5 text-sm font-medium text-slate-300 hover:bg-slate-800 disabled:opacity-60"
          >
            {bootstrapping ? <Loader2 size={16} className="animate-spin" /> : <Shield size={16} />}
            Bootstrap admin from env (development)
          </button>
          <p className="mt-2 text-center text-xs text-slate-500">
            Configure ADMIN_BOOTSTRAP_EMAIL and ADMIN_BOOTSTRAP_PASSWORD in backend/.env
          </p>
        </div>
      </div>
    </div>
  );
}

export default function AdminLoginPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center text-gray-500">
          <Loader2 className="h-5 w-5 animate-spin" />
        </div>
      }
    >
      <AdminLoginForm />
    </Suspense>
  );
}
