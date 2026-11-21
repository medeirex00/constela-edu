/**
 * Dublês mínimos de `react-native` para renderizar telas do app no jsdom, nos
 * testes `aud*` (os componentes nativos não existem fora do aparelho). Cada
 * componente vira um elemento HTML com o mesmo texto; `onPress` vira `onClick`.
 *
 * Quem usa precisa, no próprio arquivo de teste:
 *   - `// @vitest-environment jsdom`;
 *   - `vi.mock("react", ...)` devolvendo o React que o `react-dom` da raiz do
 *     monorepo usa (o app tem só o React 19, sem renderizador web): o mesmo
 *     objeto do renderizador, senão os hooks quebram;
 *   - `globalThis.React = React`: o Vitest compila o JSX das telas no modo
 *     clássico (`React.createElement`).
 */
import { createElement, type ReactNode } from "react";

type Props = { children?: ReactNode; onPress?: () => void; [chave: string]: unknown };

const elemento = (tag: string) => ({ children, onPress, accessibilityRole, disabled }: Props) =>
  createElement(
    tag,
    {
      // Desabilitado, o toque não chega (como no TouchableOpacity de verdade).
      ...(onPress && !disabled ? { onClick: onPress } : {}),
      ...(disabled ? { "aria-disabled": true } : {}),
      ...(accessibilityRole ? { role: accessibilityRole } : {}),
    },
    children,
  );

function FlatList({ data, renderItem, keyExtractor, ListEmptyComponent }: {
  data: unknown[];
  renderItem: (a: { item: unknown; index: number }) => ReactNode;
  keyExtractor: (item: unknown) => string;
  ListEmptyComponent?: ReactNode;
}) {
  if (!data || data.length === 0) return createElement("div", null, ListEmptyComponent ?? null);
  return createElement(
    "div",
    null,
    data.map((item, index) =>
      createElement("div", { key: keyExtractor(item) }, renderItem({ item, index }))),
  );
}

type BotaoAlerta = { text?: string; style?: string; onPress?: () => void };

/** Cada `Alert.alert` chamado pela tela (o diálogo nativo não existe no jsdom). */
export const alertas: {
  titulo: string;
  mensagem?: string;
  botoes: BotaoAlerta[];
  opcoes?: { cancelable?: boolean; onDismiss?: () => void };
}[] = [];

export const reactNativeFalso = {
  View: elemento("div"),
  Text: elemento("span"),
  ScrollView: elemento("div"),
  TouchableOpacity: elemento("button"),
  KeyboardAvoidingView: elemento("div"),
  Image: () => null,
  TextInput: () => null,
  ActivityIndicator: () => null,
  RefreshControl: () => null,
  FlatList,
  StyleSheet: { create: <T,>(estilos: T) => estilos, hairlineWidth: 1 },
  Platform: { OS: "android", select: (opcoes: Record<string, unknown>) => opcoes.android },
  AppState: { addEventListener: () => ({ remove: () => undefined }) },
  Alert: {
    alert: (
      titulo: string,
      mensagem?: string,
      botoes: BotaoAlerta[] = [],
      opcoes?: { cancelable?: boolean; onDismiss?: () => void },
    ) => {
      alertas.push({ titulo, mensagem, botoes, opcoes });
    },
  },
};
