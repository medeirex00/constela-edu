/**
 * Marca oficial do Constela Edu (kit em identidade/kit).
 *
 * <Logo/>           símbolo "C" de constelação, com variante para modo escuro
 * <LogoHorizontal/> símbolo + wordmark (constela/EDU em Poppins), como no
 *                   lockup horizontal oficial — usado no topo e no login.
 *
 * Cores da marca: azul profundo #1B2A4A, âmbar-estrela #F5B942.
 */
export function Logo({ tamanho = 32, className = "" }: { tamanho?: number; className?: string }) {
  return (
    <>
      <img
        src="/simbolo.svg"
        alt="Constela Edu"
        width={tamanho}
        height={tamanho}
        className={`dark:hidden ${className}`}
      />
      <img
        src="/simbolo-escuro.svg"
        alt="Constela Edu"
        width={tamanho}
        height={tamanho}
        className={`hidden dark:block ${className}`}
      />
    </>
  );
}

export function LogoHorizontal({ altura = 40 }: { altura?: number }) {
  return (
    <div className="flex items-center gap-2.5">
      <Logo tamanho={altura} />
      <div className="leading-none" style={{ fontFamily: "Poppins, Inter, sans-serif" }}>
        <span
          className="block font-bold tracking-tight text-[#1B2A4A] dark:text-zinc-50"
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
