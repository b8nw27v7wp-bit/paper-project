export const tokens = {
  ink: '#1d1d1f',
  inkHover: '#2c2c2e',
  muted: '#86868b',
  mutedLight: '#a1a1a6',
  hairline: '#f5f5f7',
  surface: '#f5f5f7',
  border: '#e8e8ed',
  accent: '#0071e3',
  success: '#10b981',
  warning: '#f59e0b',
  danger: '#ef4444',
  bg: '#ffffff',
  radius: '12px',
  radiusCard: '16px',
  radiusButton: '20px',
  fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Helvetica Neue", Helvetica, Arial, sans-serif',
} as const

export const cssVarTokens: Record<keyof typeof tokens, string> = {
  ink: '--c-ink',
  inkHover: '--c-ink-hover',
  muted: '--c-muted',
  mutedLight: '--c-muted-light',
  hairline: '--c-hairline',
  surface: '--c-surface',
  border: '--c-border',
  accent: '--c-accent',
  success: '--c-success',
  warning: '--c-warning',
  danger: '--c-danger',
  bg: '--c-bg',
  radius: '--c-radius',
  radiusCard: '--c-radius-card',
  radiusButton: '--c-radius-button',
  fontFamily: '--apple-font',
}

export function tokenVar(key: keyof typeof tokens): string {
  return `var(${cssVarTokens[key]}, ${tokens[key]})`
}

export const themeOverrides = {
  common: {
    primaryColor: tokens.ink,
    primaryColorHover: tokens.inkHover,
    borderRadius: tokens.radius,
    fontFamily: tokens.fontFamily,
    textColorBase: tokens.ink,
  },
  Card: {
    borderRadius: tokens.radiusCard,
    color: tokens.bg,
    borderColor: 'transparent',
  },
  Button: {
    borderRadiusMedium: tokens.radiusButton,
  },
}

export type AppTheme = 'light' | 'dark'

export const THEME_KEY = 'app:theme'
export const THEME_STORAGE_KEY = THEME_KEY

// 暗色 tokens：与浅色 tokens 一一对应（背景/surface/文字/边框/主色等）
export const darkTokens = {
  ink: '#f5f5f7',
  inkHover: '#ffffff',
  muted: '#a1a1a6',
  mutedLight: '#86868b',
  hairline: '#2c2c2e',
  surface: '#1d1d1f',
  border: '#38383a',
  accent: '#0a84ff',
  success: '#10b981',
  warning: '#f59e0b',
  danger: '#ef4444',
  bg: '#000000',
  radius: '12px',
  radiusCard: '16px',
  radiusButton: '20px',
  fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Helvetica Neue", Helvetica, Arial, sans-serif',
} as const

export function getTheme(): AppTheme {
  try {
    const saved = localStorage.getItem(THEME_KEY)
    if (saved === 'dark' || saved === 'light') return saved
  } catch {}
  return 'light'
}

export function setTheme(theme: AppTheme): AppTheme {
  const next: AppTheme = theme === 'dark' ? 'dark' : 'light'
  try { localStorage.setItem(THEME_KEY, next) } catch {}
  try {
    if (typeof document !== 'undefined' && document.documentElement) {
      document.documentElement.dataset.theme = next
    }
  } catch {}
  return next
}

export function toggleTheme(): AppTheme {
  return setTheme(getTheme() === 'dark' ? 'light' : 'dark')
}

export const toggle = toggleTheme
