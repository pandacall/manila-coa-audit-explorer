// Minimal page: ask a question, watch progress, read the cited answer and any follow-up timeline.
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

const slug = (status) => status.toLowerCase().replace(/\s+/g, "-");

function Chip({ text, title }) {
  return html`<span class="chip" title=${title}>${text}</span>`;
}

// One AAR's Status of Implementation for one recommendation. The status is COA's; what
// Management said it did is Management's own account and is shown apart, attributed.
function FollowUp({ item }) {
  const sharedNote = item.shared.length
    ? html`<p class="note">COA printed some of this text once for several recommendations.</p>`
    : null;
  return html`<div class="follow-up">
    <p>
      <span class=${"status status-" + slug(item.status)}>
        COA: ${item.status_text}
      </span>
      ${item.status_note && html`<span class="note"> ${item.status_note}</span>`}
    </p>
    <p class="recommendation">${item.recommendation}</p>
    ${(item.management_action || item.reason) &&
    html`<details>
      <summary>Management's action and the reason given</summary>
      ${item.management_action &&
      html`<p><strong>Management said:</strong> ${item.management_action}</p>`}
      ${item.reason && html`<p><strong>Reason for partial or non-implementation:</strong> ${item.reason}</p>`}
      ${sharedNote}
    </details>`}
    <p class="citations"><${Chip} text=${item.citation} /></p>
  </div>`;
}

function Timeline({ timeline }) {
  const label = `CY ${timeline.origin_year} AAR, Observation No. ${timeline.origin_observation}`;
  return html`<section class="timeline">
    <h2>${label}</h2>
    <p class="timeline-title">${timeline.title}</p>
    <ol>
      <li class="step raised">
        <h3>Raised</h3>
        ${timeline.raised
          ? html`<p class="citations"><${Chip} text=${timeline.raised.citation} title=${timeline.raised.title} /></p>`
          : html`<p>${label}: before the 2020–2024 reports, so not available here. COA tracks it
              in the reports below.</p>`}
      </li>
      ${timeline.steps.map(
        (step) => html`<li class="step" key=${step.aar_year}>
          <h3>CY ${step.aar_year} AAR, Part III</h3>
          ${step.follow_ups.map((item) => html`<${FollowUp} item=${item} key=${item.key} />`)}
        </li>`
      )}
      ${timeline.steps.length === 0 &&
      html`<li class="step"><p>No later report follows this observation up.</p></li>`}
    </ol>
  </section>`;
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
              (c) => html`<${Chip} key=${c.text} text=${c.text} title=${c.title} />`
            )}
          </p>
        </li>`
      )}
    </ul>
    ${(result.timelines || []).map(
      (timeline) => html`<${Timeline}
        timeline=${timeline}
        key=${timeline.origin_year + "-" + timeline.origin_observation}
      />`
    )}
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
      Ask about the Commission on Audit's Audit Observations on the City of Manila, 2020–2024,
      and whether the City acted on COA's recommendations. An Audit Observation is a deficiency COA
      found, not a finding of wrongdoing.
    </p>
    <form onSubmit=${submit}>
      <input
        value=${question}
        onInput=${(e) => setQuestion(e.target.value)}
        placeholder="e.g. Did Manila act on COA's recommendations about cash advances?"
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
