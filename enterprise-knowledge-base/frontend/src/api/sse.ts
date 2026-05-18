export type CitationItem = {
  chunk_id: string;
  content: string;
  score: number;
  metadata: Record<string, unknown>;
};

export async function streamChat(
  body: {
    knowledge_base_id: string;
    session_id?: string | null;
    message: string;
    stream: boolean;
    top_k: number;
  },
  token: string,
  onCitation: (items: CitationItem[]) => void,
  onDelta: (text: string) => void,
  onDone: (sessionId: string) => void,
  onError: (msg: string) => void
) {
  const base = import.meta.env.VITE_API_BASE || "";
  const res = await fetch(`${base}/api/v1/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
  });
  if (!res.ok || !res.body) {
    const t = await res.text();
    onError(t || `HTTP ${res.status}`);
    return;
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  const processBlock = (block: string) => {
    const lines = block.split("\n");
    let event = "";
    let dataLine = "";
    for (const line of lines) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) dataLine = line.slice(5).trim();
    }
    if (!dataLine) return;
    try {
      const data = JSON.parse(dataLine);
      if (event === "citation") onCitation(data.items || []);
      else if (event === "answer_delta") onDelta(data.text || "");
      else if (event === "done") onDone(data.session_id || "");
      else if (event === "error") onError(data.message || "error");
    } catch {
      /* ignore */
    }
  };
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const parts = buf.split("\n\n");
    buf = parts.pop() || "";
    for (const p of parts) {
      if (p.trim()) processBlock(p);
    }
  }
  if (buf.trim()) processBlock(buf);
}
