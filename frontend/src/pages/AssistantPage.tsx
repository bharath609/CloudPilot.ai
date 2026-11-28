import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { useCurrency } from "../CurrencyContext";
import { Badge, Card, ErrorBox } from "../components/Card";
import type { AssistantAnswer } from "../types";

interface Message {
  role: "user" | "assistant";
  text: string;
  result?: AssistantAnswer;
}

const confidenceTone = (confidence: string) =>
  confidence === "high" ? "ok" : confidence === "medium" ? "warn" : "muted";

export function AssistantPage() {
  const { currency } = useCurrency();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, busy]);

  const send = async (question: string) => {
    const trimmed = question.trim();
    if (!trimmed || busy) return;
    setError(null);
    setInput("");
    setMessages((prev) => [...prev, { role: "user", text: trimmed }]);
    setBusy(true);
    try {
      const result = await api.ask(trimmed, currency);
      setMessages((prev) => [...prev, { role: "assistant", text: result.answer, result }]);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const suggestions =
    messages.length > 0 && messages[messages.length - 1].result
      ? messages[messages.length - 1].result!.suggestions
      : [
          `What did we spend in ${currency}?`,
          "What are the top services by cost?",
          "Show me the findings and their baseline cost.",
          "Is the data stale, and when was it last imported?",
          "Are there any anomalies right now?",
          "How do I import my own billing data?",
        ];

  return (
    <div className="stack">
      <Card
        title="AI Assistant"
        subtitle="Ask about your costs, resources, findings, policy, and data quality"
        right={<Badge tone="info">Local data only</Badge>}
      >
        <div className="assistant-note">
          This assistant answers by querying the database inside this app — no external AI service
          and no data leaves your machine. Every number is computed from stored rows and the answer
          lists its sources. If the stored data cannot answer a question, it says so instead of
          guessing.
        </div>

        <div className="chat">
          {messages.length === 0 && (
            <div className="chat-empty">
              <div className="chat-empty-mark">◆</div>
              <p>
                Try asking about spend, a specific resource, a policy verdict, or how to load your
                own CSV.
              </p>
            </div>
          )}

          {messages.map((message, index) => (
            <div className={`msg msg-${message.role}`} key={index}>
              <div className="msg-bubble">
                <p className="msg-text">{message.text}</p>

                {message.result && message.result.facts.length > 0 && (
                  <div className="msg-facts">
                    {message.result.facts.map((fact, factIndex) => (
                      <div className="msg-fact" key={factIndex}>
                        <span>{fact.label}</span>
                        <b>{fact.value}</b>
                      </div>
                    ))}
                  </div>
                )}

                {message.result && (
                  <div className="msg-meta">
                    <Badge tone={confidenceTone(message.result.confidence)}>
                      confidence: {message.result.confidence}
                    </Badge>
                    <span className="chip">{message.result.intent.replace(/_/g, " ")}</span>
                    <span className="chip">{message.result.currency}</span>
                    {message.result.sources.map((source, sourceIndex) => (
                      <span className="chip chip-muted" key={sourceIndex}>
                        {source}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}

          {busy && (
            <div className="msg msg-assistant">
              <div className="msg-bubble">
                <p className="msg-text muted">Querying the local dataset…</p>
              </div>
            </div>
          )}
          <div ref={endRef} />
        </div>

        {error && <ErrorBox message={error} />}

        <div className="chip-row suggestions">
          {suggestions.slice(0, 5).map((suggestion) => (
            <button
              className="chip chip-button"
              key={suggestion}
              disabled={busy}
              onClick={() => send(suggestion)}
            >
              {suggestion}
            </button>
          ))}
        </div>

        <form
          className="chat-input"
          onSubmit={(e) => {
            e.preventDefault();
            send(input);
          }}
        >
          <input
            type="text"
            value={input}
            placeholder={`Ask about ${currency} spend, a resource_id, policy, or your data…`}
            onChange={(e) => setInput(e.target.value)}
            disabled={busy}
          />
          <button className="btn primary" type="submit" disabled={busy || !input.trim()}>
            Ask
          </button>
        </form>
      </Card>
    </div>
  );
}
