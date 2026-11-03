const defaultTheme = require("tailwindcss/defaultTheme");

/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      // Identidade visual v2 (docs/design/IDENTIDADE-VISUAL-V2.md): Poppins em toda a
      // interface, como nas telas de referência aprovadas pelo dono (31/10/2026).
      // Inter fica de reserva (carregada) para glifos que faltarem.
      fontFamily: {
        sans: ["Poppins", "Inter", ...defaultTheme.fontFamily.sans],
        marca: ["Poppins", "Inter", ...defaultTheme.fontFamily.sans],
      },
      // As escalas "indigo" e "zinc" são REMAPEADAS (mesmo precedente da v1, que já
      // remapeava o indigo): todas as telas herdam a identidade sem trocar classe.
      //   indigo = violeta da marca v2 (600 #6C5CE7: botões, item ativo, Leitura),
      //            com 900/950 no azul-marinho da barra lateral (#17193B), que é o
      //            papel que esses dois tons já tinham (azul profundo da marca).
      //   zinc   = neutros levemente arroxeados (50 #F5F6FB é o fundo lavanda).
      // Contraste (WCAG): branco sobre indigo-600 = 4,86:1; zinc-500 sobre branco = 4,9:1
      // e sobre o fundo lavanda = 4,54:1; zinc-400 fica para ícone e realce não essencial.
      colors: {
        indigo: {
          50: "#F3F1FE",
          100: "#E8E4FD",
          200: "#D3CBFB",
          300: "#B5AAF7",
          400: "#9688F2",
          500: "#7F6FEC",
          600: "#6C5CE7",
          700: "#5A4AD4",
          800: "#4637AE",
          900: "#1F2250",
          950: "#17193B",
        },
        zinc: {
          50: "#F5F6FB",
          100: "#EEEFF6",
          200: "#E5E7F0",
          300: "#D3D6E4",
          400: "#8A8EA9",
          500: "#6B6F8E",
          600: "#545876",
          700: "#3E415E",
          800: "#2A2D4D",
          900: "#1A1C38",
          950: "#10122A",
        },
        // Azul-marinho da barra lateral e dos cartões escuros (ex.: Fim do bimestre).
        marinho: {
          200: "#C9CBE3",
          300: "#9A9EC6",
          400: "#8B8FB5",
          600: "#3A3E7A",
          700: "#2B2F66",
          800: "#1F2250",
          900: "#17193B",
          950: "#121331",
        },
        // Âmbar-estrela da marca: premiação e certificados. Texto SEMPRE marinho sobre
        // ele (9,6:1); branco sobre o âmbar reprova (1,8:1).
        ouro: {
          50: "#FFF8E7",
          100: "#FFEFC7",
          200: "#F8DC95",
          300: "#F5CB6A",
          400: "#F5B942",
          500: "#F0A92B",
          600: "#D18A12",
          700: "#9A6408",
        },
        medalha: {
          ouro: "#F5B942",
          prata: "#CBD5E9",
          bronze: "#E0955A",
        },
      },
      borderRadius: {
        cartao: "1.25rem",
      },
      boxShadow: {
        cartao: "0 1px 2px rgba(23, 25, 59, 0.04), 0 6px 24px -8px rgba(23, 25, 59, 0.08)",
        flutuante: "0 12px 32px -8px rgba(23, 25, 59, 0.18)",
        pilula: "0 8px 18px -6px rgba(108, 92, 231, 0.55)",
        ambar: "0 8px 18px -8px rgba(240, 169, 43, 0.6)",
      },
    },
  },
  plugins: [],
};
