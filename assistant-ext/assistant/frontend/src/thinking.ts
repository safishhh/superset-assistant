/** 从正文中抽出思考内容（MiniCPM 会把思考直接拼在文本里并带 </think>）。 */
export function extractThinking(text: string): string {
  const chunks: string[] = [];
  let rest = text;
  rest = rest.replace(
    /<think\b[^>]*>([\s\S]*?)<\/think>/gi,
    (_match, inner: string) => {
      chunks.push(inner);
      return "";
    },
  );
  const open = rest.match(/<think\b[^>]*>([\s\S]*)$/i);
  if (open) {
    chunks.push(open[1]);
    rest = rest.slice(0, open.index ?? 0);
  }
  const lead = rest.match(/^([\s\S]*?)<\/think>/i);
  if (lead) {
    chunks.push(lead[1]);
  }
  return chunks.join("\n").trim();
}

export function stripThinking(text: string): string {
  let value = text.replace(/<think\b[^>]*>[\s\S]*?<\/think>/gi, "");
  value = value.replace(/<think\b[^>]*>[\s\S]*$/gi, "");
  value = value.replace(/^[\s\S]*<\/think>/i, "");
  return value.trim();
}
