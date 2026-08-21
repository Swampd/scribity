# Parser Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a persistent Parser tab that opens Scribity's existing DRR Report Import view.

**Architecture:** Reuse the header's existing tab pattern and the existing `view` state. Add no state, data access, parsing behavior, or dependencies.

**Tech Stack:** React in `dashboard.html`, Tailwind CSS utility classes, existing browser test workflow.

## Global Constraints

- Modify only the header navigation in `dashboard.html`.
- Preserve the existing **Import DRR Report** create-menu command.
- Do not modify parser state, file selection, parsing, importing, saving, or document loading.
- Do not access or modify the user's document files.

---

### Task 1: Add and verify the Parser navigation tab

**Files:**
- Modify: `dashboard.html:2132-2138`

**Interfaces:**
- Consumes: existing `view` state and `setView(nextView)` React setter
- Produces: a header button labeled `Parser` that calls `setView('parser')`

- [x] **Step 1: Verify the current behavior lacks a persistent Parser tab**

Inspect the rendered header and confirm its persistent tabs are Library, Inspector, Draft, Render, and Sources while the Parser is reachable only from the create menu.

- [x] **Step 2: Add the minimal navigation button**

Add this button immediately after Sources:

```jsx
<button onClick={() => setView('parser')} className={`px-4 py-1.5 rounded-md text-xs font-bold uppercase tracking-wide transition-colors ${view === 'parser' ? 'bg-orange-600 text-white shadow' : 'text-slate-400 hover:text-white'}`}>Parser</button>
```

- [x] **Step 3: Verify the behavior**

Render the application with isolated temporary data. Confirm the Parser tab exists, clicking it displays `DRR Report Import`, the tab has the orange active class, and clicking Library returns to the Library view.

- [x] **Step 4: Run regression checks**

Run the existing unit tests, compile-check `scribity_server.py`, and run `git diff --check`. Confirm no user document files were accessed or modified.
