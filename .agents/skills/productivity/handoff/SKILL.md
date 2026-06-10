---
name: handoff
description: >
  Compact the current conversation and workspace state into an optimized HTML handoff file.
  Use when creating a handoff file, transferring context between subagents, completing a milestone,
  or when the user asks to "create a handoff report", "generate handoff.html", or "handoff task".
argument-hint: "What will the next session be used for?"
---

Write a structured `handoff.html` document instead of Markdown. HTML is easier and more optimized for LLM agents to parse, query, and read.

## Where to Save

- If working inside a subagent workspace: Save to the subagent's run directory (e.g., `.agents/<run_name>/handoff.html`).
- If working in the main workspace: Save to the root of the workspace or target folder as requested, or the OS temporary directory if transferring between global contexts.

## HTML Structure Requirements

Your handoff HTML MUST follow this semantic and clean structure (minimize CSS, maximize structured tags):

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Agent Handoff - [Task Name / Milestone]</title>
  <!-- LLM-optimized metadata tags -->
  <meta name="project" content="sonochron">
  <meta name="milestone" content="[Milestone # or N/A]">
  <meta name="status" content="[success | in_progress | failed]">
  <meta name="timestamp" content="[ISO-8601 Timestamp]">
  <meta name="last_active_files" content="[comma-separated absolute paths]">
</head>
<body>
  <header>
    <h1>Agent Handoff Report: [Task/Milestone Name]</h1>
    <p><strong>Generated on:</strong> [Date & Time] | <strong>Status:</strong> [Status]</p>
  </header>

  <main>
    <!-- 1. Key Discoveries, Facts, and logs -->
    <section id="observation">
      <h2>1. Observations & Findings</h2>
      <ul>
        <li>Current state description...</li>
        <li>Errors encountered and their exact log snippets...</li>
        <li>Database / environment inspection results...</li>
      </ul>
    </section>

    <!-- 2. Rationales and steps taken -->
    <section id="logic-chain">
      <h2>2. Logic Chain</h2>
      <ol>
        <li><strong>Step 1:</strong> Reason for doing this...</li>
        <li><strong>Step 2:</strong> Implementation details...</li>
      </ol>
    </section>

    <!-- 3. Exact changes and code locations -->
    <section id="implementation">
      <h2>3. Code & Asset Implementation</h2>
      <ul>
        <li>Created/Modified: <a href="file:///absolute/path/to/file">filename</a></li>
        <li>Created/Modified: <a href="file:///absolute/path/to/another_file#L10-L20">another_file (lines 10-20)</a></li>
      </ul>
    </section>

    <!-- 4. Constraints, limits, and assumptions -->
    <section id="caveats">
      <h2>4. Caveats & Assumptions</h2>
      <ul>
        <li>Dependencies or missing requirements...</li>
        <li>Assumptions made during development...</li>
      </ul>
    </section>

    <!-- 5. Clear instructions for the next agent -->
    <section id="next-steps">
      <h2>5. Next Steps / Action Plan</h2>
      <ul>
        <li>[ ] Action item 1...</li>
        <li>[ ] Action item 2...</li>
      </ul>
    </section>

    <!-- 6. Skills to load or trigger next -->
    <section id="suggested-skills">
      <h2>6. Suggested Skills</h2>
      <ul>
        <li><code>productivity/caveman</code> - for token-efficient updates</li>
        <li><code>qdrant/qdrant-search-quality</code> - if working on search capabilities</li>
      </ul>
    </section>
  </main>
</body>
</html>
```

Ensure all file links in the HTML file use the standard markdown/HTML absolute `file://` URI scheme (e.g. `<a href="file:///home/jackc/projects/sonochron/backend/app/main.py">main.py</a>`).
