const defaultTheme = require("tailwindcss/defaultTheme");

/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", ...defaultTheme.fontFamily.sans],
        marca: ["Poppins", "Inter", ...defaultTheme.fontFamily.sans],
      },
      // Paleta oficial do Constela Edu (identidade/kit — Estudo de Marca §8):
      // a escala "indigo" inteira é remapeada para os tons da marca, então
      // todas as telas herdam a identidade sem trocar nenhuma classe.
      //   600 #5B6EE1 índigo suave (botões/CTAs) · 800 #3A4C8C azul-violeta
      //   900 #1B2A4A azul profundo (marca)     · 950 #0F1626 azul-carvão
      colors: {
        indigo: {
          50: "#F0F3FD",
          100: "#E3E8FB",
          200: "#C7D0F5",
          300: "#A3B1EE",
          400: "#7E90E8",
          500: "#6B7DE4",
          600: "#5B6EE1",
          700: "#4757B8",
          800: "#3A4C8C",
          900: "#1B2A4A",
          950: "#0F1626",
        },
      },
    },
  },
  plugins: [],
};
