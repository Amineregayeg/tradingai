import type { Config } from 'tailwindcss'

const config: Config = {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        'bg-primary': 'var(--bg-primary)',
        'bg-secondary': 'var(--bg-secondary)',
        'bg-card': 'var(--bg-card)',
        'bg-card-hover': 'var(--bg-card-hover)',
        'bg-accent': 'var(--bg-accent)',
        'border-default': 'var(--border)',
        'border-light': 'var(--border-light)',
        'text-primary': 'var(--text-primary)',
        'text-secondary': 'var(--text-secondary)',
        'text-muted': 'var(--text-muted)',
        'accent-blue': 'var(--accent-blue)',
        'accent-green': 'var(--accent-green)',
        'accent-amber': 'var(--accent-amber)',
        'accent-red': 'var(--accent-red)',
        'accent-purple': 'var(--accent-purple)',
        'accent-cyan': 'var(--accent-cyan)',
        'color-success': 'var(--color-success)',
        'color-warning': 'var(--color-warning)',
        'color-danger': 'var(--color-danger)',
        'color-info': 'var(--color-info)',
        'color-ai': 'var(--color-ai)',
      },
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'Roboto', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', '"SF Mono"', 'Menlo', 'Consolas', 'monospace'],
      },
      borderRadius: {
        sm: 'var(--radius-sm)',
        md: 'var(--radius-md)',
        lg: 'var(--radius-lg)',
        xl: 'var(--radius-xl)',
      },
      boxShadow: {
        sm: 'var(--shadow-sm)',
        md: 'var(--shadow-md)',
        lg: 'var(--shadow-lg)',
      },
      transitionDuration: {
        fast: 'var(--duration-fast)',
        normal: 'var(--duration-normal)',
        slow: 'var(--duration-slow)',
      },
      zIndex: {
        dropdown: '100',
        sticky: '200',
        banner: '300',
        modal: '1000',
        toast: '2000',
      },
    },
  },
  plugins: [],
}

export default config
