# ⚡ Handoff Guide: SigMap & Antigravity MCP Server Integration

This guide provides step-by-step instructions to integrate [SigMap](https://github.com/manojmallick/sigmap) as an MCP (Model Context Protocol) server for **Antigravity** across other web applications.

Implementing this configuration resolves the challenge of high token usage during agentic coding sessions by providing **Antigravity** with a compact codebase signature map (~97.5% prompt size reduction) and enabling it to query codebase structures on-demand.

---

## 📋 Prerequisites
Ensure the target web application has Node.js and `npm` installed. No local package installations are required since the server runs via `npx`.

---

## 🚀 Step-by-Step Setup Guide

### Step 1: Initialize SigMap in the Target Codebase
Navigate to the root directory of your target web application and generate the default SigMap configuration and ignore file scaffold:

```bash
npx -y sigmap --init
```

This creates two files in your project root:
1. `gen-context.config.json` — The main configuration parameters.
2. `.contextignore` — Defines which files and folders SigMap should ignore when scanning (e.g., node modules, build files, lockfiles).

### Step 2: Configure Exclusions and Strategies
Edit `gen-context.config.json` to optimize the scanning process for your application stack. Here is a recommended configuration for standard web apps (Next.js/React/Node):

```json
{
  "strategy": "hot-cold",
  "autoMaxTokens": true,
  "maxTokens": 10000,
  "exclude": [
    "node_modules/**",
    ".next/**",
    "out/**",
    "build/**",
    "dist/**",
    ".git/**",
    "*.log",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock"
  ],
  "adapters": ["copilot", "gemini"]
}
```

*   `strategy: "hot-cold"`: Instructs SigMap to prioritize recently modified files ("hot") and archive older code ("cold"), reducing prompt sizes by another 70–90%.
*   `exclude`: List all large, compiled, or dependency directories to prevent them from wasting token budget.

### Step 3: Run the Initial Scan
Generate the initial signature map of the codebase once to verify it scans correctly:

```bash
npx sigmap --report
```

This generates `.github/copilot-instructions.md` containing the signature map and logs a token reduction report. You should expect a ~95% to 98% reduction from your baseline codebase size.

---

## 🛠️ Configuring Antigravity MCP Server

To enable **Antigravity** to query your new signature map on-demand, register SigMap as an MCP server for **Antigravity**.

1. Locate the configuration directory for the **antigravity-cli** command. This is typically located at:
   `~/.gemini/antigravity-cli/`
2. Create or edit the configuration file named `mcp_config.json` within that directory:
   `~/.gemini/antigravity-cli/mcp_config.json`
3. Add the following JSON structure:

```json
{
  "mcpServers": {
    "sigmap": {
      "command": "npx",
      "args": [
        "-y",
        "sigmap",
        "--mcp"
      ]
    }
  }
}
```

Whenever you start an **Antigravity** session in your target codebase, **Antigravity** will automatically initialize this MCP server.

---

## 🔍 Verification & Usage

### 1. Verification of the MCP Server
When **Antigravity** launches, it starts the `sigmap` MCP server in the background over `stdio` JSON-RPC. To manually verify the TF-IDF query engine is working, run a local query from the project root:

```bash
npx sigmap --query "auth context logic"
```

This should return a ranked list of relevant files and their respective signatures.

### 2. Instructing Antigravity
With the MCP server registered, **Antigravity** can use the following tools natively:
*   `query`: Rank files by relevance to a natural language query.
*   `get_signatures`: Get signatures of specific classes or files.
*   `impact`: Map out transitive dependencies and impact of modifying a specific file.

---

## 🔄 Maintenance & Best Practices

To ensure **Antigravity** always has access to an up-to-date signature map, automate context generation:

*   **Git Commit Hook**: Run `npx sigmap --setup` to automatically install a git commit hook that rebuilds the signature map whenever changes are committed.
*   **Watch Mode**: During active development, you can run `npx sigmap --watch` in a separate terminal to dynamically regenerate signatures on file save.

---

## 🔗 Reference Examples (homma-research)
For reference, you can check how this is set up in our current repository:
*   Local MCP Config: [mcp_config.json](file:///home/jackc/.gemini/antigravity-cli/mcp_config.json)
*   Generated Signatures File: [.github/copilot-instructions.md](file:///home/jackc/projects/homma-research/.github/copilot-instructions.md)
*   Detailed Evaluation: [sigmap_analysis.md](file:///home/jackc/.gemini/antigravity-cli/brain/369290e9-ddcc-4f92-bafe-be2fd4d9f76a/sigmap_analysis.md)
