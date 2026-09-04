/**
 * Operational control-console palette.
 * Dark-mode compatible; avoids consumer-app flash.
 */

export const palette = {
  light: {
    bg: '#F4F6F8',
    surface: '#FFFFFF',
    surfaceMuted: '#EEF1F4',
    border: '#D5DCE3',
    text: '#0F172A',
    textSecondary: '#475569',
    textMuted: '#64748B',
    accent: '#0F766E',
    accentSoft: '#CCFBF1',
    danger: '#B91C1C',
    dangerSoft: '#FEE2E2',
    warning: '#B45309',
    warningSoft: '#FEF3C7',
    ok: '#15803D',
    okSoft: '#DCFCE7',
    critical: '#991B1B',
    high: '#C2410C',
    medium: '#A16207',
    low: '#475569',
    banner: '#1E293B',
    bannerText: '#F8FAFC',
    disabled: '#94A3B8',
    inputBg: '#FFFFFF',
    inputBorder: '#CBD5E1',
  },
  dark: {
    bg: '#0B1220',
    surface: '#111827',
    surfaceMuted: '#1F2937',
    border: '#334155',
    text: '#F1F5F9',
    textSecondary: '#CBD5E1',
    textMuted: '#94A3B8',
    accent: '#2DD4BF',
    accentSoft: '#134E4A',
    danger: '#F87171',
    dangerSoft: '#7F1D1D',
    warning: '#FBBF24',
    warningSoft: '#78350F',
    ok: '#4ADE80',
    okSoft: '#14532D',
    critical: '#FCA5A5',
    high: '#FDBA74',
    medium: '#FDE68A',
    low: '#94A3B8',
    banner: '#020617',
    bannerText: '#E2E8F0',
    disabled: '#64748B',
    inputBg: '#0F172A',
    inputBorder: '#334155',
  },
} as const;

export type ThemeColors = { [K in keyof typeof palette.light]: string };

export function priorityColor(colors: ThemeColors, priority: string): string {
  switch (priority) {
    case 'critical':
      return colors.critical;
    case 'high':
      return colors.high;
    case 'medium':
      return colors.medium;
    default:
      return colors.low;
  }
}

export function statusColor(colors: ThemeColors, status: string): string {
  switch (status) {
    case 'ok':
    case 'healthy':
    case 'running':
      return colors.ok;
    case 'degraded':
    case 'action_required':
    case 'error':
      return colors.danger;
    case 'disabled':
    case 'unconfigured':
    case 'demo':
      return colors.warning;
    default:
      return colors.textMuted;
  }
}
