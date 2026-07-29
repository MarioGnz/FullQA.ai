# FullQA.ai Recorder — extensión privada de navegador

Captura lo que el sistema operativo no puede ver: el **selector CSS exacto**, el
**texto real** del elemento clicado, el **valor final** de cada campo, y las
**navegaciones** (incluidas SPAs). El agente de FullQA.ai fusiona estos eventos
con los nativos para que la documentación diga exactamente qué pasó.

Incluye un **popup** (clic en el icono azul "QA" de la barra) que muestra en
vivo: si el agente está conectado, si hay grabación activa, y cuántos eventos
se han enviado. El icono muestra un contador verde mientras graba.

## Cómo funciona (flujo completo)

```
Página web (content.js)          Service worker              Agente FullQA.ai
─ escucha clicks/inputs/nav  →   agrupa en lotes (400ms) →   127.0.0.1:8765
─ extrae selector/texto/valor                                 ↓ solo si grabas
                                                    events.jsonl de la sesión
                                                              ↓
                                              fusión con eventos nativos (UIA)
                                                              ↓
                                                     documentación generada
```

## Seguridad y privacidad (por diseño)

| Capa | Garantía |
|---|---|
| Red | El único host autorizado en el manifest es `http://127.0.0.1:8765` — Chrome **bloquea** cualquier otro destino. Nada sale de tu máquina. |
| Agente | Escucha solo en `127.0.0.1` (inaccesible desde la red) y **solo mientras grabas**; sin sesión activa, descarta todo. |
| Anti-inyección | El agente rechaza (403) cualquier POST cuyo `Origin` no sea una extensión — una página web maliciosa no puede meter eventos falsos en tu sesión. |
| Datos sensibles | `type=password` jamás se captura. Campos que parecen sensibles (tarjeta, CVV, token, PIN…) se redactan en la extensión Y en el agente (doble capa). |
| Permisos | Solo pide `storage` (contador del popup). Sin `tabs`, sin `history`, sin `cookies`, sin `<all_urls>` de lectura en segundo plano. |
| Distribución | Se instala **desde carpeta** (descomprimida). Nunca pasa por la Web Store; nadie más puede actualizarla ni verla. |
| Almacenamiento | La extensión no guarda nada en el navegador (solo el contador, que se borra al cerrarlo). Los eventos viven únicamente en tu `qa-sessions/`. |

## Instalación (una sola vez, ~1 minuto)

1. Abre `chrome://extensions` (o `edge://extensions`).
2. Activa **Modo de desarrollador** (interruptor arriba a la derecha).
3. Pulsa **Cargar descomprimida** y elige esta carpeta (`FullQA.ai/extension`).
4. (Opcional) Ancla el icono "QA" a la barra: puzzle 🧩 → pin.

> Chrome puede avisar "extensión en modo desarrollador" al reiniciar — es el
> comportamiento normal de cualquier extensión privada no publicada.

## Uso

Nada especial: pulsa **Iniciar Grabación** en FullQA.ai y navega como siempre.
El popup pasará a **verde "Grabando sesión"** y el contador subirá con cada
acción. Al detener la grabación, los eventos ya están fusionados en la sesión.

## Verificar que funciona

- Popup: verde = grabando · ámbar = agente conectado sin grabar · rojo = FullQA.ai cerrado.
- O abre `http://127.0.0.1:8765/ping` → `{"ok": true, "recording": true}`.

## Desinstalar

`chrome://extensions` → Quitar. (Sin grabación activa no envía nada de todos modos.)
