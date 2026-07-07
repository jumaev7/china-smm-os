"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Mail, UserPlus, Users } from "lucide-react";
import toast from "react-hot-toast";
import { tenantAuthApi, type TenantUserRole } from "@/lib/api";
import { OnboardingStepShell } from "@/components/onboarding/OnboardingStepShell";
import { useOnboardingRefresh } from "@/lib/onboarding-hooks";
import { cn } from "@/lib/utils";

const ROLES: { value: TenantUserRole; label: string }[] = [
  { value: "manager", label: "Manager" },
  { value: "sales", label: "Sales" },
  { value: "operator", label: "Operator" },
];

export default function OnboardingTeamPage() {
  const qc = useQueryClient();
  const refresh = useOnboardingRefresh();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<TenantUserRole>("sales");

  const { data: usersData } = useQuery({
    queryKey: ["tenant-auth-users"],
    queryFn: () => tenantAuthApi.listUsers().then((r) => r.data),
  });

  const users = usersData?.items ?? [];
  const teamReady = users.length >= 2;

  const invite = useMutation({
    mutationFn: () => tenantAuthApi.createUser({ email: email.trim(), role, status: "invited" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tenant-auth-users"] });
      refresh.mutate();
      setEmail("");
      toast.success("Team member invited");
    },
    onError: () => toast.error("Could not invite team member — check email and permissions"),
  });

  return (
    <OnboardingStepShell
      stepId="team_members"
      title="Invite your team"
      subtitle="Sales and operations teammates collaborate on leads, content, and deals."
      illustration="business"
      nextHref="/onboarding/channels"
      nextLabel="Continue to channels"
    >
      <div className="space-y-6">
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-card">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2 text-navy-900">
              <Users size={18} className="text-brand-600" />
              <span className="font-semibold text-sm">Current team ({users.length})</span>
            </div>
            {teamReady ? (
              <span className="text-xs font-semibold text-emerald-700 bg-emerald-50 px-2 py-1 rounded-full">
                Collaboration ready
              </span>
            ) : null}
          </div>

          <ul className="space-y-2">
            {users.map((u, i) => (
              <li
                key={u.id}
                className="flex items-center justify-between rounded-xl bg-slate-50 px-4 py-3 animate-fade-in-up"
                style={{ animationDelay: `${i * 50}ms` }}
              >
                <div className="flex items-center gap-3 min-w-0">
                  <div className="w-8 h-8 rounded-full bg-brand-100 text-brand-700 flex items-center justify-center text-xs font-bold shrink-0">
                    {u.email[0]?.toUpperCase()}
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-navy-900 truncate">{u.email}</p>
                    <p className="text-xs text-gray-500 capitalize">{u.role} · {u.status}</p>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </div>

        <form
          className="rounded-2xl border border-brand-100 bg-gradient-to-br from-brand-50/40 to-white p-5 shadow-card space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (!email.trim()) {
              toast.error("Email is required");
              return;
            }
            invite.mutate();
          }}
        >
          <div className="flex items-center gap-2 text-brand-700">
            <UserPlus size={18} />
            <span className="font-semibold text-sm">Invite a colleague</span>
          </div>

          <div className="grid sm:grid-cols-[1fr_auto] gap-3">
            <div className="relative">
              <Mail size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="colleague@factory.com"
                className="w-full rounded-xl border border-slate-200 pl-10 pr-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500/30"
              />
            </div>
            <select
              value={role}
              onChange={(e) => setRole(e.target.value as TenantUserRole)}
              className="rounded-xl border border-slate-200 px-3 py-2.5 text-sm bg-white"
            >
              {ROLES.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </select>
          </div>

          <button
            type="submit"
            disabled={invite.isPending}
            className={cn(
              "w-full sm:w-auto inline-flex items-center justify-center gap-2 rounded-xl bg-brand-600 text-white text-sm font-semibold px-5 py-2.5 hover:bg-brand-700 disabled:opacity-50",
            )}
          >
            {invite.isPending ? <Loader2 size={16} className="animate-spin" /> : null}
            Send invitation
          </button>

          <p className="text-xs text-gray-500">
            Optional but recommended — invite at least one teammate for shared pipeline visibility.
          </p>
        </form>
      </div>
    </OnboardingStepShell>
  );
}
