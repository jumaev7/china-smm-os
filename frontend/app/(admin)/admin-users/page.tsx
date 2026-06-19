"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Shield, UserPlus, Users } from "lucide-react";
import toast from "react-hot-toast";
import { adminAuthApi, AdminRole, AdminUser } from "@/lib/api";
import { useAdminAuth } from "@/lib/admin-auth-store";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";

const ROLE_LABELS: Record<AdminRole, string> = {
  super_admin: "Super Admin",
  platform_admin: "Platform Admin",
  support_admin: "Support Admin",
  auditor: "Auditor",
};

export default function AdminUsersPage() {
  const qc = useQueryClient();
  const { user: currentUser, hasPermission } = useAdminAuth();
  const [newEmail, setNewEmail] = useState("");
  const [newRole, setNewRole] = useState<AdminRole>("auditor");
  const [newPassword, setNewPassword] = useState("");

  const canManage = hasPermission("platform.full");

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["admin-auth-users"],
    queryFn: () => adminAuthApi.listUsers().then((r) => r.data),
    enabled: canManage,
  });

  const { data: rolesData } = useQuery({
    queryKey: ["admin-auth-roles"],
    queryFn: () => adminAuthApi.listRoles().then((r) => r.data),
  });

  const { data: sessionsData } = useQuery({
    queryKey: ["admin-auth-sessions"],
    queryFn: () => adminAuthApi.listSessions({ status: "active" }).then((r) => r.data),
  });

  const createMutation = useMutation({
    mutationFn: () =>
      adminAuthApi
        .createUser({ email: newEmail.trim(), role: newRole, password: newPassword || undefined })
        .then((r) => r.data),
    onSuccess: () => {
      toast.success("Admin user created");
      setNewEmail("");
      setNewPassword("");
      qc.invalidateQueries({ queryKey: ["admin-auth-users"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  if (!canManage) {
    return (
      <div className="mx-auto max-w-lg p-8 text-center text-slate-300">
        Super admin permission required to manage platform admin users.
      </div>
    );
  }

  if (isLoading) return <LoadingState label="Loading admin users…" />;
  if (isError) return <ErrorState message={(error as Error).message} onRetry={() => refetch()} />;

  const users = data?.items ?? [];
  const rolePermissions = data?.role_permissions ?? rolesData?.role_permissions ?? {};
  const sessions = sessionsData?.items ?? [];

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold text-white">Admin Users</h1>
        <p className="mt-1 text-sm text-slate-400">Platform admin accounts, roles, and permissions</p>
      </div>

      <section className="rounded-xl border border-slate-800 bg-slate-900 p-5">
        <div className="mb-4 flex items-center gap-2">
          <Users size={18} className="text-indigo-400" />
          <h2 className="text-lg font-medium text-white">Users</h2>
          <span className="text-sm text-slate-500">({users.length})</span>
        </div>
        {users.length === 0 ? (
          <EmptyState title="No admin users" description="Create a platform admin below or bootstrap from env." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-slate-800 text-slate-400">
                  <th className="pb-2 pr-4">Email</th>
                  <th className="pb-2 pr-4">Role</th>
                  <th className="pb-2 pr-4">Status</th>
                  <th className="pb-2">Last login</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u: AdminUser) => (
                  <tr key={u.id} className="border-b border-slate-800/60">
                    <td className="py-2 pr-4 text-white">{u.email}</td>
                    <td className="py-2 pr-4">{ROLE_LABELS[u.role]}</td>
                    <td className="py-2 pr-4">{u.status}</td>
                    <td className="py-2 text-slate-400">
                      {u.last_login_at ? new Date(u.last_login_at).toLocaleString() : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="rounded-xl border border-slate-800 bg-slate-900 p-5">
        <div className="mb-4 flex items-center gap-2">
          <Shield size={18} className="text-indigo-400" />
          <h2 className="text-lg font-medium text-white">Roles & Permissions</h2>
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          {Object.entries(rolePermissions).map(([role, perms]) => (
            <div key={role} className="rounded-lg border border-slate-800 p-3">
              <div className="font-medium text-white">{ROLE_LABELS[role as AdminRole] ?? role}</div>
              <div className="mt-1 flex flex-wrap gap-1">
                {(perms as string[]).map((p) => (
                  <span key={p} className="rounded bg-slate-800 px-1.5 py-0.5 text-xs text-slate-300">
                    {p}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="rounded-xl border border-slate-800 bg-slate-900 p-5">
        <div className="mb-4 flex items-center gap-2">
          <UserPlus size={18} className="text-indigo-400" />
          <h2 className="text-lg font-medium text-white">Add Admin User</h2>
        </div>
        <div className="grid gap-3 md:grid-cols-3">
          <input
            type="email"
            placeholder="email@company.com"
            value={newEmail}
            onChange={(e) => setNewEmail(e.target.value)}
            className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-white"
          />
          <select
            value={newRole}
            onChange={(e) => setNewRole(e.target.value as AdminRole)}
            className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-white"
          >
            {(data?.roles_available ?? ["auditor", "support_admin", "platform_admin"]).map((r) => (
              <option key={r} value={r}>
                {ROLE_LABELS[r as AdminRole] ?? r}
              </option>
            ))}
          </select>
          <input
            type="password"
            placeholder="Password (min 8 chars)"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-white"
          />
        </div>
        <button
          type="button"
          disabled={createMutation.isPending || !newEmail}
          onClick={() => createMutation.mutate()}
          className="mt-3 flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-60"
        >
          {createMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : null}
          Create admin user
        </button>
      </section>

      <section className="rounded-xl border border-slate-800 bg-slate-900 p-5">
        <h2 className="mb-3 text-lg font-medium text-white">Active Sessions ({sessions.length})</h2>
        {sessions.length === 0 ? (
          <p className="text-sm text-slate-500">No active admin sessions</p>
        ) : (
          <div className="space-y-2 text-sm">
            {sessions.slice(0, 10).map((s) => (
              <div key={s.id} className="rounded-lg border border-slate-800 px-3 py-2 text-slate-300">
                {s.admin_email} · {s.admin_role} · last active{" "}
                {new Date(s.last_activity).toLocaleString()}
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
