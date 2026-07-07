"use client";

import { cn } from "@/lib/utils";

type Variant = "platform" | "business" | "success" | "executive";

export function OnboardingIllustration({
  variant,
  className,
}: {
  variant: Variant;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "relative flex items-center justify-center rounded-2xl overflow-hidden",
        className,
      )}
      aria-hidden
    >
      {variant === "platform" && <PlatformArt />}
      {variant === "business" && <BusinessArt />}
      {variant === "success" && <SuccessArt />}
      {variant === "executive" && <ExecutiveArt />}
    </div>
  );
}

function PlatformArt() {
  return (
    <svg viewBox="0 0 200 160" className="w-full h-full animate-float" fill="none">
      <defs>
        <linearGradient id="plat-bg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#eef4ff" />
          <stop offset="100%" stopColor="#dbeafe" />
        </linearGradient>
      </defs>
      <rect width="200" height="160" rx="16" fill="url(#plat-bg)" />
      <rect x="28" y="36" width="64" height="48" rx="8" fill="#fff" stroke="#93c5fd" strokeWidth="2" />
      <rect x="36" y="44" width="32" height="4" rx="2" fill="#bfdbfe" />
      <rect x="36" y="52" width="48" height="3" rx="1.5" fill="#dbeafe" />
      <rect x="36" y="60" width="40" height="3" rx="1.5" fill="#dbeafe" />
      <circle cx="148" cy="52" r="28" fill="#2563eb" opacity="0.12" />
      <path
        d="M132 52h32M148 36v32"
        stroke="#2563eb"
        strokeWidth="3"
        strokeLinecap="round"
        opacity="0.5"
      />
      <rect x="108" y="96" width="64" height="40" rx="8" fill="#fff" stroke="#60a5fa" strokeWidth="2" />
      <path d="M120 112h40M120 120h28" stroke="#93c5fd" strokeWidth="3" strokeLinecap="round" />
      <circle cx="52" cy="108" r="16" fill="#1d4ed8" opacity="0.15" />
      <path
        d="M44 108l6 6 14-14"
        stroke="#1d4ed8"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function BusinessArt() {
  return (
    <svg viewBox="0 0 200 160" className="w-full h-full animate-float" fill="none">
      <defs>
        <linearGradient id="biz-bg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#ecfdf5" />
          <stop offset="100%" stopColor="#d1fae5" />
        </linearGradient>
      </defs>
      <rect width="200" height="160" rx="16" fill="url(#biz-bg)" />
      <path
        d="M32 120 L56 88 L80 96 L104 64 L128 72 L152 48 L168 56"
        stroke="#10b981"
        strokeWidth="3"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
      <circle cx="56" cy="88" r="5" fill="#10b981" />
      <circle cx="104" cy="64" r="5" fill="#10b981" />
      <circle cx="152" cy="48" r="5" fill="#059669" />
      <rect x="32" y="32" width="48" height="32" rx="6" fill="#fff" stroke="#6ee7b7" strokeWidth="2" />
      <text x="40" y="52" fill="#047857" fontSize="11" fontWeight="600">
        +24%
      </text>
      <rect x="120" y="100" width="56" height="36" rx="6" fill="#fff" stroke="#34d399" strokeWidth="2" />
      <rect x="128" y="112" width="20" height="16" rx="2" fill="#a7f3d0" />
      <rect x="152" y="104" width="16" height="24" rx="2" fill="#6ee7b7" />
    </svg>
  );
}

function SuccessArt() {
  return (
    <svg viewBox="0 0 200 160" className="w-full h-full" fill="none">
      <defs>
        <linearGradient id="succ-bg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#f5f3ff" />
          <stop offset="100%" stopColor="#ede9fe" />
        </linearGradient>
      </defs>
      <rect width="200" height="160" rx="16" fill="url(#succ-bg)" />
      <circle cx="100" cy="72" r="40" fill="#7c3aed" opacity="0.12" />
      <path
        d="M100 44l8 16h18l-14 11 5 17-17-12-17 12 5-17-14-11h18z"
        fill="#7c3aed"
        opacity="0.85"
      />
      <circle cx="44" cy="48" r="4" fill="#a78bfa" className="animate-float" />
      <circle cx="160" cy="56" r="3" fill="#c4b5fd" style={{ animationDelay: "0.5s" }} className="animate-float" />
      <circle cx="152" cy="120" r="5" fill="#8b5cf6" opacity="0.6" className="animate-float" />
      <rect x="48" y="112" width="104" height="28" rx="14" fill="#fff" stroke="#c4b5fd" strokeWidth="2" />
      <text x="68" y="130" fill="#6d28d9" fontSize="11" fontWeight="600">
        First success!
      </text>
    </svg>
  );
}

function ExecutiveArt() {
  return (
    <svg viewBox="0 0 200 160" className="w-full h-full animate-float" fill="none">
      <defs>
        <linearGradient id="exec-bg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#fffbeb" />
          <stop offset="100%" stopColor="#fef3c7" />
        </linearGradient>
      </defs>
      <rect width="200" height="160" rx="16" fill="url(#exec-bg)" />
      <rect x="24" y="28" width="152" height="88" rx="10" fill="#fff" stroke="#fcd34d" strokeWidth="2" />
      <rect x="36" y="40" width="48" height="28" rx="4" fill="#fef3c7" />
      <rect x="92" y="40" width="72" height="8" rx="4" fill="#fde68a" />
      <rect x="92" y="54" width="56" height="6" rx="3" fill="#fef9c3" />
      <rect x="36" y="76" width="128" height="28" rx="4" fill="#fffbeb" stroke="#fde68a" strokeWidth="1" />
      <path d="M44 90h24M44 96h40" stroke="#f59e0b" strokeWidth="2" strokeLinecap="round" opacity="0.5" />
      <circle cx="156" cy="44" r="10" fill="#f59e0b" opacity="0.2" />
      <path d="M152 44h8M156 40v8" stroke="#d97706" strokeWidth="2" strokeLinecap="round" />
      <rect x="56" y="124" width="88" height="20" rx="10" fill="#f59e0b" opacity="0.15" />
    </svg>
  );
}
