/**
 * Scanner de QR Code: lê o QR do Painel Público impresso pela escola e abre
 * o painel no navegador. Só URLs http(s) são aceitas — qualquer outro
 * conteúdo é ignorado com aviso (nunca executamos o que vier no QR).
 */
import { CameraView, useCameraPermissions } from "expo-camera";
import * as Linking from "expo-linking";
import { useRef, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { Botao, Cartao, TextoSuave, Titulo } from "../componentes/basicos";
import { cores, espacos } from "../tema";

export default function Scanner() {
  const [permissao, pedirPermissao] = useCameraPermissions();
  const [mensagem, setMensagem] = useState("Aponte para o QR code do painel da escola.");
  const processando = useRef(false);

  async function aoLer({ data }: { data: string }) {
    if (processando.current) return;
    processando.current = true;
    try {
      if (/^https?:\/\//i.test(data)) {
        setMensagem("Abrindo painel...");
        await Linking.openURL(data);
        setMensagem("Painel aberto no navegador. Aponte novamente para reler.");
      } else {
        setMensagem("QR code não reconhecido — esperava um endereço do painel.");
      }
    } finally {
      setTimeout(() => {
        processando.current = false;
      }, 2500);
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
