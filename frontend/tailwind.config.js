/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        predix: {
          bg:       '#080c14',
          surface:  '#0d1524',
          card:     '#111d2e',
          border:   '#1a2d44',
          cyan:     '#00e5ff',
          emerald:  '#00ffa3',
          amber:    '#ffb300',
          red:      '#ff4444',
          muted:    '#4a6080',
          text:     '#c8d8e8',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
      boxShadow: {
        cyan:    '0 0 20px rgba(0, 229, 255, 0.15)',
        emerald: '0 0 20px rgba(0, 255, 163, 0.15)',
        card:    '0 4px 24px rgba(0, 0, 0, 0.4)',
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'fade-in':    'fadeIn 0.4s ease-out',
        'slide-up':   'slideUp 0.4s ease-out',
      },
      keyframes: {
        fadeIn:  { '0%': { opacity: '0' },                            '100%': { opacity: '1' } },
        slideUp: { '0%': { opacity: '0', transform: 'translateY(12px)' }, '100%': { opacity: '1', transform: 'translateY(0)' } },
      },
    },
  },
  plugins: [],
}
