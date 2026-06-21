const htmlEntityMap: Record<string, string> = {
  "&amp;": "&",
  "&lt;": "<",
  "&gt;": ">",
  "&quot;": '"',
  "&#39;": "'",
};

const mojibakeMap: Array<[RegExp, string]> = [
  [/Ã¡/g, "á"],
  [/Ã©/g, "é"],
  [/Ã­/g, "í"],
  [/Ã³/g, "ó"],
  [/Ãº/g, "ú"],
  [/Ã±/g, "ñ"],
  [/Ã¼/g, "ü"],
  [/Ã/g, "Á"],
  [/Ã‰/g, "É"],
  [/Ã/g, "Í"],
  [/Ã“/g, "Ó"],
  [/Ãš/g, "Ú"],
  [/Ã‘/g, "Ñ"],
  [/Â·/g, "·"],
];

export function decodeVisibleText(value: string | null | undefined, fallback = "Sin dato") {
  if (!value) return fallback;
  let text = value
    .replace(/&#(\d+);/g, (_, code) => String.fromCharCode(Number(code)))
    .replace(/&#x([0-9a-fA-F]+);/g, (_, code) => String.fromCharCode(Number.parseInt(code, 16)))
    .replace(/<[^>]*>/g, " ");

  for (const [pattern, replacement] of mojibakeMap) {
    text = text.replace(pattern, replacement);
  }
  for (const [entity, replacement] of Object.entries(htmlEntityMap)) {
    text = text.replaceAll(entity, replacement);
  }
  text = text.replace(/\s+/g, " ").trim();
  if (!text) return fallback;

  if (
    /color:\s*white|background-color:|\.box-address|\.caja|display:\s*flex|justify-content:\s*center|font-weight:\s*bold|text-decoration:\s*underline/i.test(
      text,
    )
  ) {
    return fallback;
  }

  const lastBrace = Math.max(text.lastIndexOf("}"), text.lastIndexOf(";"));
  if (lastBrace > 0 && lastBrace < text.length - 1) {
    const tail = text.slice(lastBrace + 1).trim();
    if (tail.length > 20) {
      text = tail;
    }
  }

  if (
    text.includes("color: white") ||
    text.includes("background-color:") ||
    text.includes(".caja") ||
    text.includes(".box-address") ||
    text.includes("display: flex") ||
    text.includes("justify-content: center")
  ) {
    const sentenceStart = text.search(/(?:\.\s|[A-ZÁÉÍÓÚÑ][^{}]{20,})/);
    if (sentenceStart > 0) {
      text = text.slice(sentenceStart).trim();
    }
  }

  return text || fallback;
}

export function isNoiseVisibleText(value: string | null | undefined) {
  const text = decodeVisibleText(value, "");
  return Boolean(text && (text.includes("@") || text.toLowerCase().startsWith("http://") || text.toLowerCase().startsWith("https://")));
}
