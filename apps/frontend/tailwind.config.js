/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,js,ts,jsx,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        apple: ['-apple-system', 'BlinkMacSystemFont', '"SF Pro Display"', '"SF Pro Text"', '"Helvetica Neue"', 'Helvetica', 'Arial', 'sans-serif'],
      },
      colors: {
        ink: '#1d1d1f',
        muted: '#86868b',
        hairline: '#f5f5f7',
        surface: '#f5f5f7',
        border: '#e8e8ed',
        accent: '#0071e3',
        success: '#10b981',
        warning: '#f59e0b',
        danger: '#ef4444',
      },
      borderRadius: {
        apple: '16px',
      },
    },
  },
  plugins: [],
}
