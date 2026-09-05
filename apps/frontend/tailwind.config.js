/** @type {import('tailwindcss').Config} */
import { tokenVar } from './src/theme'

export default {
  content: ['./index.html', './src/**/*.{vue,js,ts,jsx,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        apple: ['-apple-system', 'BlinkMacSystemFont', '"SF Pro Display"', '"SF Pro Text"', '"Helvetica Neue"', 'Helvetica', 'Arial', 'sans-serif'],
      },
      colors: {
        ink: tokenVar('ink'),
        muted: tokenVar('muted'),
        hairline: tokenVar('hairline'),
        surface: tokenVar('surface'),
        border: tokenVar('border'),
        accent: tokenVar('accent'),
        success: tokenVar('success'),
        warning: tokenVar('warning'),
        danger: tokenVar('danger'),
      },
      borderRadius: {
        apple: 'var(--c-radius-card, 16px)',
      },
    },
  },
  plugins: [],
}
