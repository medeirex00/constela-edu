/**
 * Marca oficial do Constela Edu (kit em identidade/kit).
 *
 * <Logo/>           símbolo "C" de constelação, com variante para modo escuro
 * <LogoHorizontal/> símbolo + wordmark (constela/EDU em Poppins), como no
 *                   lockup horizontal oficial — usado no topo e no login.
 *
 * Cores da marca: azul profundo #1B2A4A, âmbar-estrela #F5B942.
 *
 * `sobreEscuro` (identidade v2): força a versão para FUNDO ESCURO do lockup oficial
 * (`lockup-horizontal-dark`: traços claros, "constela" branco, "EDU" âmbar),
 * independente do tema do app — é o que a barra lateral marinho e o painel do login
 * usam. Sem ela, a troca continua só pelo tema (`dark:`), como antes. O logotipo é o
 * oficial; nada de wordmark novo (decisão D3).
 */
export function Logo({
  tamanho = 32,
  className = "",
  sobreEscuro = false,
  alt = "Constela Edu",
}: {
  tamanho?: number;
  className?: string;
  sobreEscuro?: boolean;
  /** Texto alternativo. Vazio quando o wordmark já está escrito ao lado. */
  alt?: string;
}) {
  if (sobreEscuro) {
    return (
      <img src="/simbolo-escuro.svg" alt={alt} width={tamanho} height={tamanho} className={className} />
    );
  }
  return (
    <>
      <img
        src="/simbolo.svg"
        alt={alt}
        width={tamanho}
        height={tamanho}
        className={`dark:hidden ${className}`}
      />
      <img
        src="/simbolo-escuro.svg"
        alt={alt}
        width={tamanho}
        height={tamanho}
        className={`hidden dark:block ${className}`}
      />
    </>
  );
}

export function LogoHorizontal({ altura = 40, sobreEscuro = false }: { altura?: number; sobreEscuro?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      {/* O nome já está escrito ao lado: o símbolo é decorativo (sem alt duplicado). */}
      <Logo tamanho={altura} sobreEscuro={sobreEscuro} alt="" />
      <div className="leading-none" style={{ fontFamily: "Poppins, Inter, sans-serif" }}>
        <span
          className={`block font-bold tracking-tight ${sobreEscuro ? "text-white" : "text-[#1B2A4A] dark:text-zinc-50"}`}
          style={{ fontSize: altura * 0.48 }}
        >
          constela
        </span>
        <span
          className="mt-0.5 block font-medium text-[#F5B942]"
          style={{ fontSize: altura * 0.26, letterSpacing: "0.32em" }}
        >
          EDU
        </span>
      </div>
    </div>
  );
}
