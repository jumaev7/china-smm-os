"use client";

import Link from "next/link";
import { ArrowRight, FileText, Link2 } from "lucide-react";
import { OnboardingLayout } from "@/components/onboarding/OnboardingLayout";

export default function OnboardingProposalPage() {
  return (
    <OnboardingLayout
      title="First commercial proposal"
      subtitle="Send structured quotes linked to buyers and active deals."
      contextStep="proposal"
    >
      <div className="space-y-5 max-w-xl">
        <div className="rounded-xl border border-slate-200 p-5 bg-white space-y-3">
          <div className="flex items-center gap-2">
            <FileText className="text-brand-600" size={20} />
            <h3 className="font-semibold text-gray-900">Create a proposal</h3>
          </div>
          <p className="text-sm text-gray-600">
            Open Sales CRM proposals, add line items with MOQ and pricing, then link the proposal to an
            existing buyer or deal.
          </p>
          <Link href="/proposals" className="text-sm font-medium text-brand-600 hover:underline">
            Open proposals →
          </Link>
        </div>

        <div className="rounded-xl border border-slate-200 p-5 bg-white space-y-3">
          <div className="flex items-center gap-2">
            <Link2 className="text-gray-500" size={20} />
            <h3 className="font-semibold text-gray-900">Link to buyer / deal</h3>
          </div>
          <p className="text-sm text-gray-600">
            Select customer and deal when creating the proposal so Growth Center and deal room stay in sync.
          </p>
          <Link href="/deals" className="text-sm font-medium text-brand-600 hover:underline">
            View deals →
          </Link>
        </div>

        <Link
          href="/onboarding/growth-center"
          className="inline-flex items-center gap-2 rounded-lg bg-brand-600 text-white font-medium px-5 py-2.5 hover:bg-brand-700"
        >
          Continue to Growth Center
          <ArrowRight size={18} />
        </Link>
      </div>
    </OnboardingLayout>
  );
}
