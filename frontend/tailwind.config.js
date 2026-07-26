/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        primary: '#1B5E20',
        secondary: '#FF9800',
        surface: '#FAFAFA',
        sidebar: '#0D3B1E',
        ink: '#212121',
      },
    },
  },
  plugins: [],
}
