// Minimal page: ask a question, watch progress, read the cited answer.
// React and htm come from a CDN so the page needs no build step.
const { useState } = React;
const html = htm.bind(React.createElement);

async function* events(question) {
  const response = await fetch("/api/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    const lines = buffer.split("\n");
    buffer = lines.pop();
    for (const line of lines) if (line.trim()) yield JSON.parse(line);
  }
}

function Answer({ result }) {
  if (result.type === "not_covered") {
    return html`<section class="answer not-covered">
      <p>${result.message}</p>
    </section>`;
  }
  return html`<section class="answer">
    <p class="summary">${result.summary}</p>
    <ul class="key-points">
      ${result.key_points.map(
        (point, i) => html`<li key=${i}>
          <p>${point.text}</p>
          <p class="citations">
            ${point.citations.map(
              (c) => html`<span class="chip" key=${c.text} title=${c.title}>${c.text}</span>`
            )}
          </p>
        </li>`
      )}
    </ul>
  </section>`;
}

function App() {
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState([]);
  const [result, setResult] = useState(null);

  async function submit(e) {
    e.preventDefault();
    if (!question.trim() || busy) return;
    setBusy(true);
    setProgress([]);
    setResult(null);
    try {
      for await (const event of events(question)) {
        if (event.type === "status") setProgress((p) => [...p, event.message]);
        else setResult(event);
      }
    } catch (err) {
      setResult({ type: "error", message: "Could not reach the server. Please try again." });
    } finally {
      setBusy(false);
    }
  }

  return html`<main>
    <h1>COA Audit Explorer</h1>
    <p class="lede">
      Ask about the Commission on Audit's Audit Observations on the City of Manila, 2020–2024.
      An Audit Observation is a deficiency COA found, not a finding of wrongdoing.
    </p>
    <form onSubmit=${submit}>
      <input
        value=${question}
        onInput=${(e) => setQuestion(e.target.value)}
        placeholder="e.g. What did COA say about cash advances?"
        maxLength="1000"
        aria-label="Your question"
      />
      <button disabled=${busy}>${busy ? "Working…" : "Ask"}</button>
    </form>
    ${busy && html`<ul class="progress">${progress.map((m, i) => html`<li key=${i}>${m}</li>`)}</ul>`}
    ${result && result.type === "error" && html`<p class="error">${result.message}</p>`}
    ${result && result.type !== "error" && html`<${Answer} result=${result} />`}
    <footer>
      Independent project, not affiliated with COA. Answers are AI-generated from the 2020–2024
      Annual Audit Reports and may be wrong; check the cited source.
    </footer>
  </main>`;
}

ReactDOM.createRoot(document.getElementById("root")).render(html`<${App} />`);
