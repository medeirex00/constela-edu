/**
 * Scanner de QR Code: lê o QR do Painel Público impresso pela escola e abre
 * o painel no navegador. Nunca executamos o que vier no QR:
 *   - o endereço do Painel Público do produto (`https://<host do painel>/p/<código>`,
 *     o mesmo que o servidor põe no QR) abre direto;
 *   - qualquer outro endereço http(s) NÃO abre sozinho: o app mostra o endereço e
 *     só abre se a pessoa confirmar (um adesivo com outro QR por cima do cartaz da
 *     escola não leva ninguém, em nome do app, a uma página de terceiros; o QR de
 *     uma instalação local, com http e o IP da máquina, continua abrindo com um
 *     toque a mais);
 *   - o resto é ignorado com aviso.
 */
import { CameraView, useCameraPermissions } from "expo-camera";
import * as Linking from "expo-linking";
import { useRef, useState } from "react";
import { Alert, StyleSheet, Text, View } from "react-native";

import { Botao, Cartao, TextoSuave, Titulo } from "../componentes/basicos";
import { cores, espacos } from "../tema";

/** Hosts do Painel Público do produto (a base do link é o PUBLIC_BASE_URL do
 *  servidor). Outro ambiente define EXPO_PUBLIC_PAINEL_HOSTS no build (lista
 *  separada por vírgula). */
const LISTA_DE_HOSTS: string =
  process.env.EXPO_PUBLIC_PAINEL_HOSTS ?? "www.constelaedu.com,constelaedu.com";
const HOSTS_DO_PAINEL = LISTA_DE_HOSTS.split(",")
  .map((host) => host.trim().toLowerCase())
  .filter(Boolean);

export type DestinoQr = "painel" | "outro" | "invalido";

/** Classifica o texto lido. Comparação de TEXTO, sem `new URL` (o URL do React
 *  Native interpreta endereços diferente do navegador que vai abri-los): só é
 *  "painel" o que é exatamente https, um host da lista (sem usuário nem porta) e o
 *  caminho /p/<código>. */
export function destinoDoQr(texto: string, hosts: string[] = HOSTS_DO_PAINEL): DestinoQr {
  if (!/^https?:\/\//i.test(texto)) return "invalido";
  const painel = /^https:\/\/([^/?#]+)\/p\/[A-Za-z0-9_-]+\/?$/i.exec(texto);
  return painel && hosts.includes(painel[1].toLowerCase()) ? "painel" : "outro";
}

export default function Scanner() {
  const [permissao, pedirPermissao] = useCameraPermissions();
  const [mensagem, setMensagem] = useState("Aponte para o QR code do painel da escola.");
  const processando = useRef(false);

  function liberarLeitura() {
    setTimeout(() => {
      processando.current = false;
    }, 2500);
  }

  async function aoLer({ data }: { data: string }) {
    if (processando.current) return;
    processando.current = true;
    let aguardaEscolha = false;
    try {
      const destino = destinoDoQr(data);
      if (destino === "painel") {
        setMensagem("Abrindo painel...");
        await Linking.openURL(data);
        setMensagem("Painel aberto no navegador. Aponte novamente para reler.");
      } else if (destino === "outro") {
        // A leitura fica parada até a pessoa escolher (a câmera continua vendo o
        // mesmo QR; sem isso, o aviso se repetiria a cada leitura).
        aguardaEscolha = true;
        // O app só sabe que não reconhece o endereço: pode ser o painel de uma
        // instalação própria do Constela (o QR leva o PUBLIC_BASE_URL do servidor).
        setMensagem("O app não reconhece este endereço como o painel do Constela Edu.");
        Alert.alert(
          "Endereço não reconhecido",
          `Ele leva para:\n\n${data}\n\nSó abra se você confia neste endereço.`,
          [
            { text: "Cancelar", style: "cancel", onPress: liberarLeitura },
            {
              text: "Abrir mesmo assim",
              onPress: () => {
                Linking.openURL(data).catch(() => undefined);
                setMensagem("Endereço aberto no navegador. Aponte novamente para reler.");
                liberarLeitura();
              },
            },
          ],
          { cancelable: true, onDismiss: liberarLeitura },
        );
      } else {
        setMensagem("QR code não reconhecido — esperava um endereço do painel.");
      }
    } finally {
      if (!aguardaEscolha) liberarLeitura();
    }
  }

  if (!permissao) return null;

  if (!permissao.granted) {
    return (
      <View style={estilos.centro}>
        <Cartao>
          <Titulo>Scanner de QR Code</Titulo>
          <TextoSuave>
            O Constela Edu usa a câmera apenas para ler o QR code do Painel Público da escola.
          </TextoSuave>
          <View style={{ height: espacos.l }} />
          <Botao titulo="Permitir câmera" onPress={() => pedirPermissao()} />
        </Cartao>
      </View>
    );
  }

  return (
    <View style={estilos.tela}>
      <CameraView
        style={estilos.camera}
        barcodeScannerSettings={{ barcodeTypes: ["qr"] }}
        onBarcodeScanned={aoLer}
      />
      <View style={estilos.rodape}>
        <Text style={estilos.rodapeTexto}>{mensagem}</Text>
      </View>
    </View>
  );
}

const estilos = StyleSheet.create({
  tela: { flex: 1, backgroundColor: "#000" },
  camera: { flex: 1 },
  centro: { flex: 1, justifyContent: "center", padding: espacos.xl, backgroundColor: cores.fundo },
  rodape: { padding: espacos.l, backgroundColor: "#111" },
  rodapeTexto: { color: "#fff", textAlign: "center", fontSize: 13 },
});
