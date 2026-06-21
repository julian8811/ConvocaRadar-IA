const htmlEntityMap: Record<string, string> = {
  "&amp;": "&",
  "&lt;": "<",
  "&gt;": ">",
  "&quot;": '"',
  "&#39;": "'",
};

function repairMojibake(value: string) {
  if (!/[ÃÂ�]/.test(value)) return value;
  try {
    const bytes = Uint8Array.from(value, (char) => char.charCodeAt(0));
    const repaired = new TextDecoder("utf-8", { fatal: false }).decode(bytes);
    return repaired || value;
  } catch {
    return value;
  }
}

function normalizeWhitespace(value: string) {
  return value.replace(/\s+/g, " ").trim();
}

function looksLikeNoise(value: string) {
  return (
    /<style[\s\S]*?<\/style>|<script[\s\S]*?<\/script>|color:\s*white|background-color:|\.box-address|\.caja|display:\s*flex|justify-content:\s*center|font-weight:\s*bold|text-decoration:\s*underline|font-size:|padding:|margin:|border:/i.test(
      value,
    ) || value.includes("{") || value.includes("}") || value.includes("budgetYearsColumns")
  );
}

export function decodeVisibleText(value: string | null | undefined, fallback = "Sin dato") {
  if (!value) return fallback;

  let text = value
    .replace(/&#(\d+);/g, (_, code) => String.fromCharCode(Number(code)))
    .replace(/&#x([0-9a-fA-F]+);/g, (_, code) => String.fromCharCode(Number.parseInt(code, 16)))
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<[^>]*>/g, " ");

  for (const [entity, replacement] of Object.entries(htmlEntityMap)) {
    text = text.replaceAll(entity, replacement);
  }

  text = normalizeWhitespace(repairMojibake(text));
  if (!text) return fallback;
  if (looksLikeNoise(text)) return fallback;

  const tail = text.slice(Math.max(text.lastIndexOf("}"), text.lastIndexOf(";")) + 1).trim();
  if (tail.length > 20 && !looksLikeNoise(tail)) {
    text = tail;
  }

  if (looksLikeNoise(text)) return fallback;
  return text || fallback;
}

export function isNoiseVisibleText(value: string | null | undefined) {
  const text = decodeVisibleText(value, "");
  return Boolean(text && (text.includes("@") || text.toLowerCase().startsWith("http://") || text.toLowerCase().startsWith("https://")));
}
