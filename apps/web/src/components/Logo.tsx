/**
 * Logo do Constela Edu — ponto ÚNICO da identidade visual no web/desktop.
 * A imagem vem de /logo.png (apps/web/public). Para trocar a marca em todo
 * o sistema, substitua identidade/logo-oficial.png e rode
 * `python tools/gerar_icones.py` — nenhum código precisa mudar.
 */
export function Logo({ tamanho = 32, className = "" }: { tamanho?: number; className?: string }) {
  return (
    <img
      src="/logo.png"
      alt="Constela Edu"
      width={tamanho}
      height={tamanho}
      className={`rounded-lg ${className}`}
    />
  );
}
