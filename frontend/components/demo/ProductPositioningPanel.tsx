"use client";

import { CheckCircle2, Sparkles, Target, Zap } from "lucide-react";
import type { ProductPositioningResponse } from "@/lib/commercial-demo-api";

export function ProductPositioningPanel({ data }: { data: ProductPositioningResponse }) {
  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-brand-200 bg-gradient-to-br from-brand-50 to-white p-6">
        <div className="flex items-start gap-3">
          <div className="rounded-lg bg-brand-100 p-2">
            <Target size={20} className="text-brand-600" />
          </div>
          <div>
            <p className="text-xs font-medium text-brand-600 uppercase tracking-wide">Our Mission</p>
            <p className="text-sm text-gray-800 mt-1 leading-relaxed">{data.mission}</p>
            <p className="text-base font-semibold text-navy-900 mt-3">{data.tagline}</p>
          </div>
        </div>
      </div>

      <div>
        <h3 className="text-sm font-semibold text-navy-900 mb-3 flex items-center gap-2">
          <Sparkles size={16} className="text-brand-500" />
          Why This Platform Exists
        </h3>
        <ul className="grid gap-2 sm:grid-cols-2">
          {data.differentiators.map((item) => (
            <li key={item} className="flex items-start gap-2 text-sm text-gray-700">
              <CheckCircle2 size={14} className="text-emerald-500 shrink-0 mt-0.5" />
              {item}
            </li>
          ))}
        </ul>
      </div>

      <div>
        <h3 className="text-sm font-semibold text-navy-900 mb-3 flex items-center gap-2">
          <Zap size={16} className="text-amber-500" />
          How We Differ
        </h3>
        <div className="overflow-x-auto">
          <table className="w-full text-sm border rounded-xl overflow-hidden">
            <thead className="bg-gray-50 text-xs text-gray-500 uppercase">
              <tr>
                <th className="text-left px-4 py-2">Category</th>
                <th className="text-left px-4 py-2">Traditional Approach</th>
                <th className="text-left px-4 py-2">This Platform</th>
              </tr>
            </thead>
            <tbody>
              {data.comparisons.map((row) => (
                <tr key={row.category} className="border-t border-gray-100">
                  <td className="px-4 py-3 font-medium text-navy-900">{row.category}</td>
                  <td className="px-4 py-3 text-gray-500">{row.traditional}</td>
                  <td className="px-4 py-3 text-brand-800">{row.this_platform}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div>
        <h3 className="text-sm font-semibold text-navy-900 mb-2">Key Capabilities</h3>
        <div className="flex flex-wrap gap-2">
          {data.key_capabilities.map((cap) => (
            <span
              key={cap}
              className="rounded-full border border-gray-200 bg-white px-3 py-1 text-xs text-gray-700"
            >
              {cap}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
