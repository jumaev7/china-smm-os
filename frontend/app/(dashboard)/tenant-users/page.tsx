"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Shield, UserPlus, Users } from "lucide-react";
import toast from "react-hot-toast";
import {
  tenantAuthApi,
  TenantUserRole,
  AuthUser,
} from "@/lib/api";
import { useAuth } from "@/lib/auth-store";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";

const ROLE_LABELS: Record<TenantUserRole, string> = {
  owner: "Owner",
  manager: "Manager",
  sales: "Sales",
  operator: "Operator",
  viewer: "Viewer",
};

const STATUS_STYLES: Record<string, string> = {
  active: "bg-emerald-100 text-emerald-800",
  invited: "bg-blue-100 text-blue-800",
  suspended: "bg-red-100 text-red-800",
  removed: "bg-gray-100 text-gray-700",
};

export default function TenantUsersPage() {
  const qc = useQueryClient();
  const { user: currentUser, tenantName } = useAuth();
  const [newEmail, setNewEmail] = useState("");
  const [newRole, setNewRole] = useState<TenantUserRole>("viewer");
  const [newPassword, setNewPassword] = useState("");

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["tenant-auth-users"],
    queryFn: () => tenantAuthApi.listUsers().then((r) => r.data),
  });

  const createMutation = useMutation({
    mutationFn: () =>
      tenantAuthApi
        .createUser({
          email: newEmail.trim(),
          role: newRole,
          password: newPassword || undefined,
        })
        .then((r) => r.data),
    onSuccess: () => {
      toast.success("User created");
      setNewEmail("");
      setNewPassword("");
      qc.invalidateQueries({ queryKey: ["tenant-auth-users"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const disableMutation = useMutation({
    mutationFn: (id: string) => tenantAuthApi.disableUser(id).then((r) => r.data),
    onSuccess: () => {
      toast.success("User disabled");
      qc.invalidateQueries({ queryKey: ["tenant-auth-users"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const enableMutation = useMutation({
    mutationFn: (id: string) => tenantAuthApi.enableUser(id).then((r) => r.data),
    onSuccess: () => {
      toast.success("User enabled");
      qc.invalidateQueries({ queryKey: ["tenant-auth-users"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  if (isLoading) return <LoadingState label="Loading tenant users…" />;
  if (isError) return <ErrorState message={(error as Error).message} onRetry={() => refetch()} />;

  const users = data?.items ?? [];
  const rolePermissions = data?.role_permissions ?? {};

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold text-gray-900">Tenant Users</h1>
        <p className="mt-1 text-sm text-gray-500">
          {tenantName ?? "Your tenant"} — manage users, roles, and permissions
        </p>
      </div>

      <section className="rounded-xl border border-gray-200 bg-white p-5">
        <div className="mb-4 flex items-center gap-2">
          <Users size={18} className="text-brand-600" />
          <h2 className="text-lg font-medium text-gray-900">Users</h2>
          <span className="text-sm text-gray-400">({users.length})</span>
        </div>
        {users.length === 0 ? (
          <EmptyState title="No users" description="Add a tenant user below." />
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 text-left text-gray-500">
                  <th className="py-2 pr-4 font-medium">Email</th>
                  <th className="py-2 pr-4 font-medium">Role</th>
                  <th className="py-2 pr-4 font-medium">Status</th>
                  <th className="py-2 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u: AuthUser) => (
                  <tr key={u.id} className="border-b border-gray-50">
                    <td className="py-3 pr-4">{u.email}</td>
                    <td className="py-3 pr-4">{ROLE_LABELS[u.role]}</td>
                    <td className="py-3 pr-4">
                      <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[u.status] ?? ""}`}>
                        {u.status}
                      </span>
                    </td>
                    <td className="py-3">
                      {u.role !== "owner" && u.id !== currentUser?.id ? (
                        u.status === "active" ? (
                          <button
                            type="button"
                            onClick={() => disableMutation.mutate(u.id)}
                            className="text-xs font-medium text-red-600 hover:text-red-700"
                          >
                            Disable
                          </button>
                        ) : (
                          <button
                            type="button"
                            onClick={() => enableMutation.mutate(u.id)}
                            className="text-xs font-medium text-emerald-600 hover:text-emerald-700"
                          >
                            Enable
                          </button>
                        )
                      ) : (
                        <span className="text-xs text-gray-400">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="rounded-xl border border-gray-200 bg-white p-5">
        <div className="mb-4 flex items-center gap-2">
          <UserPlus size={18} className="text-brand-600" />
          <h2 className="text-lg font-medium text-gray-900">Add User</h2>
        </div>
        <div className="grid gap-3 sm:grid-cols-4">
          <input
            type="email"
            placeholder="Email"
            value={newEmail}
            onChange={(e) => setNewEmail(e.target.value)}
            className="rounded-lg border border-gray-300 px-3 py-2 text-sm sm:col-span-2"
          />
          <select
            value={newRole}
            onChange={(e) => setNewRole(e.target.value as TenantUserRole)}
            className="rounded-lg border border-gray-300 px-3 py-2 text-sm"
          >
            {(data?.roles_available ?? ["viewer"]).filter((r) => r !== "owner").map((role) => (
              <option key={role} value={role}>
                {ROLE_LABELS[role as TenantUserRole]}
              </option>
            ))}
          </select>
          <input
            type="password"
            placeholder="Password (optional)"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            className="rounded-lg border border-gray-300 px-3 py-2 text-sm"
          />
        </div>
        <button
          type="button"
          disabled={!newEmail.trim() || createMutation.isPending}
          onClick={() => createMutation.mutate()}
          className="mt-3 inline-flex items-center gap-2 rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60"
        >
          {createMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : null}
          Create user
        </button>
      </section>

      <section className="rounded-xl border border-gray-200 bg-white p-5">
        <div className="mb-4 flex items-center gap-2">
          <Shield size={18} className="text-brand-600" />
          <h2 className="text-lg font-medium text-gray-900">Roles & Permissions</h2>
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          {Object.entries(rolePermissions).map(([role, perms]) => (
            <div key={role} className="rounded-lg border border-gray-100 p-4">
              <h3 className="font-medium text-gray-900">{ROLE_LABELS[role as TenantUserRole] ?? role}</h3>
              <ul className="mt-2 space-y-1 text-xs text-gray-600">
                {(perms as string[]).map((p) => (
                  <li key={p}>• {p}</li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
