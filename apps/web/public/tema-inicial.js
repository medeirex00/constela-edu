// Tema ANTES do primeiro desenho (o app ainda não carregou): login, redefinição de senha,
// telão (/p/…) e vitrine (/rede/p/…) sempre escuros; nas páginas internas, a preferência
// guardada, só com um token que ainda vale (JWT com o exp no futuro). A mesma regra de
// src/lib/tema.ts (o teste tema.test.ts confere as duas). Arquivo à parte porque a CSP do
// site não aceita script inline. Qualquer erro: escuro.
(function () {
  var html = document.documentElement;
  try {
    var caminho = location.pathname.toLowerCase();
    var sempreEscura = /^\/(login|redefinir-senha)\/?$/.test(caminho) ||
      caminho.indexOf("/p/") === 0 || caminho.indexOf("/rede/p/") === 0;
    var token = localStorage.getItem("sgpe_token");
    var dados = token ? JSON.parse(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/"))) : null;
    var comSessao = !!dados && typeof dados.exp === "number" && dados.exp * 1000 > Date.now();
    var salvo = localStorage.getItem("sgpe_tema");
    var preferencia = salvo === "claro" || salvo === "escuro" ? salvo
      : (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "escuro" : "claro");
    html.classList.toggle("dark", sempreEscura || !comSessao || preferencia === "escuro");
  } catch (e) {
    html.classList.add("dark");
  }
})();
