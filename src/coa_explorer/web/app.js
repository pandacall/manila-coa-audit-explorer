// Minimal page: a conversation of questions, each with its progress, cited answer and any
// follow-up timeline. React and htm come from a CDN so the page needs no build step.
// The conversation lives only here, in the page: each question is sent with the last few
// exchanges so that a follow-up ("What about 2022?") makes sense, and the server keeps none of it.
const { useEffect, useRef, useState } = React;
const html = htm.bind(React.createElement);

const HISTORY_EXCHANGES = 3; // the server accepts at most this many
const HISTORY_ANSWER_CHARS = 3000; // and answers at most this long

async function* events(question, history) {
  const response = await fetch("/api/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, history }),
  });
  // A refusal (rate limit 429, store down 503) still arrives as one event line.
  if (!response.ok && response.status !== 429 && response.status !== 503) {
    throw new Error(`HTTP ${response.status}`);
  }
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

// One AAPSI row: Management's own account of its Action Plan. Its Reported Status is a claim by
// Management, shown with Management's name on it and never styled as COA's Status of Implementation.
function ActionPlan({ item }) {
  const target = [item.target_from, item.target_to].filter(Boolean).join(" to ");
  return html`<div class="plan">
    <p class="attribution">Management's Action Plan (AAPSI)</p>
    <p class="recommendation">${item.recommendation}</p>
    ${item.action_plan && html`<p><strong>Action Plan:</strong> ${item.action_plan}</p>`}
    ${item.person_responsible && html`<p><strong>Responsible:</strong> ${item.person_responsible}</p>`}
    ${target && html`<p><strong>Target dates:</strong> ${target}</p>`}
    ${item.reported_status_text &&
    html`<p><strong>Management reported:</strong> <span class="reported">${item.reported_status_text}</span></p>`}
    ${item.reason && html`<p><strong>Reason given:</strong> ${item.reason}</p>`}
    ${item.action_taken && html`<p><strong>Action taken or to be taken:</strong> ${item.action_taken}</p>`}
    <p class="citations"><${Chip} text=${item.citation} /></p>
  </div>`;
}

// One APMT row: COA's validation. The status is COA's; where Management's Reported Status in the
// same row differs, the disagreement is said outright.
function Validation({ item }) {
  return html`<div class="follow-up">
    <p class="attribution">COA's validation (APMT)</p>
    <p>
      ${item.status_text &&
      html`<span class=${"status status-" + slug(item.status || "none")}>COA: ${item.status || item.status_text}</span>`}
      ${item.follow_up_date && html`<span class="note"> followed up ${item.follow_up_date}</span>`}
    </p>
    <p class="recommendation">${item.recommendation}</p>
    ${item.disagreement && html`<p class="disagreement">${item.disagreement}.</p>`}
    ${item.reported_status_text &&
    html`<p class="note">Management reported: ${item.reported_status_text}</p>`}
    ${item.remarks && html`<p><strong>COA's remarks:</strong> ${item.remarks}</p>`}
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
          : html`<p>${timeline.origin_year < 2020
              ? `${label}: raised before the 2020–2024 reports, so not available here. COA tracks it in the reports below.`
              : `${label}: its Part II entry was not found among the 2020–2024 reports.`}</p>`}
      </li>
      ${timeline.steps.map(
        (step) => html`<li class="step" key=${step.aar_year}>
          <h3>CY ${step.aar_year} AAR</h3>
          ${step.follow_ups.map((item) => html`<${FollowUp} item=${item} key=${item.key} />`)}
          ${(step.action_plans || []).map((item) => html`<${ActionPlan} item=${item} key=${item.key} />`)}
          ${(step.validations || []).map((item) => html`<${Validation} item=${item} key=${item.key} />`)}
        </li>`
      )}
      ${timeline.steps.length === 0 &&
      html`<li class="step"><p>No later report follows this observation up.</p></li>`}
    </ol>
  </section>`;
}

// An earlier answer as plain text, citations included, for the model to read a follow-up by.
function answerText(result) {
  if (result.type === "not_covered") return result.message;
  const points = (label, list) =>
    (list || []).map((p) => `- ${label}${p.text} (${p.citations.map((c) => c.text).join("; ")})`);
  return [result.summary, ...points("", result.key_points), ...points("What the City said: ", result.city_said)]
    .join("\n")
    .slice(0, HISTORY_ANSWER_CHARS);
}

function Answer({ result, onAsk }) {
  if (result.type === "not_covered") {
    const suggestions = onAsk ? result.suggestions || [] : [];
    return html`<section class="answer not-covered">
      <p>${result.message}</p>
      ${suggestions.length > 0 &&
      html`<div class="suggestions">
        <p class="note">You could ask instead:</p>
        ${suggestions.map(
          (s) => html`<button type="button" class="question-chip" key=${s} onClick=${() => onAsk(s)}>${s}</button>`
        )}
      </div>`}
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
    ${result.city_said &&
    result.city_said.length > 0 &&
    html`<section class="city-said">
      <h2>What the City said</h2>
      <ul class="key-points">
        ${result.city_said.map(
          (point, i) => html`<li key=${i}>
            <p>${point.text}</p>
            <p class="citations">
              ${point.citations.map((c) => html`<${Chip} key=${c.text} text=${c.text} title=${c.title} />`)}
            </p>
          </li>`
        )}
      </ul>
    </section>`}
    ${(result.timelines || []).map(
      (timeline) => html`<${Timeline}
        timeline=${timeline}
        key=${timeline.origin_year + "-" + timeline.origin_observation}
      />`
    )}
  </section>`;
}

// 👍/👎 on a logged answer; the rating is stored against the logged question.
function Feedback({ questionId }) {
  const [rating, setRating] = useState(null);
  const [failed, setFailed] = useState(false);

  async function rate(value) {
    setFailed(false);
    try {
      const response = await fetch("/api/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question_id: questionId, rating: value }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      setRating(value);
    } catch (err) {
      setFailed(true);
    }
  }

  return html`<p class="feedback">
    Was this answer helpful?
    <button type="button" aria-pressed=${rating === "up"} aria-label="Helpful" onClick=${() => rate("up")}>👍</button>
    <button type="button" aria-pressed=${rating === "down"} aria-label="Not helpful" onClick=${() => rate("down")}>👎</button>
    ${rating && html`<span class="note"> Thanks for the feedback.</span>`}
    ${failed && html`<span class="error"> Could not save your feedback.</span>`}
  </p>`;
}

// Shown when the day's question cap is used up: example questions with the answers saved earlier.
function DemoLimit({ result }) {
  return html`<section class="demo-limit">
    <h2>${result.message}</h2>
    <p>
      The demo only answers a limited number of questions a day to keep it free to run. Please come
      back tomorrow. In the meantime, here are some example questions with their saved answers.
    </p>
    ${result.examples.map(
      (example) => html`<details key=${example.question}>
        <summary>${example.question}</summary>
        ${example.answer
          ? html`<${Answer} result=${example.answer} />`
          : html`<p class="note">No saved answer for this one yet.</p>`}
      </details>`
    )}
  </section>`;
}

// One question of the conversation: its progress while it is being answered, then its result.
function Exchange({ exchange, onAsk }) {
  const { question, progress, result } = exchange;
  return html`<article class="exchange">
    <p class="question">${question}</p>
    ${!result && html`<ul class="progress">${progress.map((m, i) => html`<li key=${i}>${m}</li>`)}</ul>`}
    ${result && (result.type === "error" || result.type === "rate_limited") &&
    html`<p class="error">${result.message}</p>`}
    ${result && result.type === "demo_limit" && html`<${DemoLimit} result=${result} />`}
    ${result && (result.type === "answer" || result.type === "not_covered") &&
    html`<${Answer} result=${result} onAsk=${onAsk} />`}
    ${result && result.question_id && html`<${Feedback} questionId=${result.question_id} key=${result.question_id} />`}
  </article>`;
}

function App() {
  const [question, setQuestion] = useState("");
  const [conversation, setConversation] = useState([]);
  const [examples, setExamples] = useState([]);
  const busy = conversation.length > 0 && !conversation[conversation.length - 1].result;
  const latest = useRef(null);

  useEffect(() => {
    fetch("/api/examples")
      .then((r) => (r.ok ? r.json() : { questions: [] }))
      .then((data) => setExamples(data.questions))
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (latest.current) latest.current.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [conversation.length]);

  // Change the exchange being answered, which is always the last one.
  const update = (change) =>
    setConversation((c) => [...c.slice(0, -1), { ...c[c.length - 1], ...change(c[c.length - 1]) }]);

  async function ask(text) {
    text = text.trim();
    if (!text || busy) return;
    // Only answered exchanges give a follow-up its context; errors and limits are left out.
    const history = conversation
      .filter((e) => e.result && (e.result.type === "answer" || e.result.type === "not_covered"))
      .slice(-HISTORY_EXCHANGES)
      .map((e) => ({ question: e.question, answer: answerText(e.result) }));
    setQuestion("");
    setConversation((c) => [...c, { question: text, progress: [], result: null }]);
    let result = null;
    try {
      for await (const event of events(text, history)) {
        if (event.type === "status") update((e) => ({ progress: [...e.progress, event.message] }));
        else result = event;
      }
    } catch (err) {
      result = { type: "error", message: "Could not reach the server. Please try again." };
    }
    update(() => ({ result: result || { type: "error", message: "No answer came back. Please try again." } }));
  }

  function submit(e) {
    e.preventDefault();
    ask(question);
  }

  return html`<main>
    <h1>COA Audit Explorer</h1>
    <p class="lede">
      Ask about the Commission on Audit's Audit Observations on the City of Manila, 2020–2024,
      whether the City acted on COA's recommendations, and the City's financial statements, in
      English, Filipino or Taglish. An Audit Observation is a deficiency COA found, not a finding
      of wrongdoing.
    </p>
    ${conversation.map(
      (exchange, i) => html`<div key=${i} ref=${i === conversation.length - 1 ? latest : null}>
        <${Exchange} exchange=${exchange} onAsk=${ask} />
      </div>`
    )}
    <form onSubmit=${submit}>
      <input
        value=${question}
        onInput=${(e) => setQuestion(e.target.value)}
        placeholder=${conversation.length
          ? "Ask a follow-up, e.g. What about 2022?"
          : "e.g. Did Manila act on COA's recommendations about cash advances?"}
        maxLength="1000"
        aria-label="Your question"
      />
      <button disabled=${busy}>${busy ? "Working…" : "Ask"}</button>
    </form>
    ${conversation.length > 0 &&
    html`<p>
      <button type="button" class="new-conversation" disabled=${busy} onClick=${() => setConversation([])}>
        New conversation
      </button>
    </p>`}
    ${conversation.length === 0 && examples.length > 0 &&
    html`<section class="examples">
      <h2>Try asking</h2>
      ${examples.map(
        (q) => html`<button type="button" class="question-chip" key=${q} onClick=${() => ask(q)}>${q}</button>`
      )}
    </section>`}
    <footer>
      <p>
        Independent project, not affiliated with COA. Answers are AI-generated from the 2020–2024 AARs; verify against the cited source.
      </p>
      <p>Questions are logged anonymously and deleted after 30 days.</p>
    </footer>
  </main>`;
}

ReactDOM.createRoot(document.getElementById("root")).render(html`<${App} />`);
